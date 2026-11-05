#!/usr/bin/env python3
"""Report this tool's runtime state, and print the commands to fix what is missing.

Design note — why this only REPORTS and never auto-installs a browser:

Browser binaries live in a version-keyed shared cache, and which build is needed
depends on the Playwright version in whatever environment the tool runs in. Rather
than hard-code a path or pin a build (which goes stale and varies per machine),
this prints the exact command and lets the caller decide. An agent running the
skill can read the output and run the command itself.

This also reports WHICH browser `elang run` would launch, and launch-tests that
one: an installed Chrome is a legitimate choice that needs no download, so the
check must not be tied to the bundled build's path.

Usage:
    python scripts/doctor.py
    python scripts/doctor.py --json
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402


def check_imports():
    import importlib.util as u
    mods = {}
    for m in ("playwright", "mcp", "ddddocr"):
        spec = u.find_spec(m)
        origin = (spec.origin or "") if spec else None
        mods[m] = {"found": bool(spec), "origin": origin}
    return mods


def check_self_contained(mods):
    """Are the deps inside this interpreter's own tree, or borrowed from global?

    Borrowed deps are the fragile case: they work here and vanish on another
    machine. A venv built with --system-site-packages looks healthy for exactly
    this reason.
    """
    own = str(Path(sys.prefix)).lower()
    borrowed = []
    for name, info in mods.items():
        if info["found"] and info["origin"] and own not in info["origin"].lower():
            borrowed.append(f"{name} -> {info['origin']}")
    return borrowed


LAUNCH_TIMEOUT_S = 60


def _apply_private_browsers_path():
    """Point Playwright at the tool's private cache, as `elang_reader` does.

    `elang_reader.open_browser()` sets `PLAYWRIGHT_BROWSERS_PATH` before building
    its choice, so without the same step here a bundled build that only exists in
    `~/.elang/browsers` looks missing. An explicit override wins; "0" is treated
    as unset, matching `config.browser_search_paths()`.
    """
    override = (os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "").strip()
    if override in ("", "0") and config.BROWSERS_DIR.is_dir():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(config.BROWSERS_DIR)


def _launch_probe(choice, kwargs, out):
    """Launch once, in THIS thread, with its own Playwright context.

    Playwright's sync API is bound to the thread that created it, so the
    background probe must not borrow the caller's `pw` object; it creates its own
    context instead. `out` is a plain dict read by the caller after the join:
    `executable`, `ok`, `error`.
    """
    if choice.get("mode") == "none":
        # No driver needed to diagnose "nothing to launch", and the reason is the
        # actionable part of the message.
        reason = (choice.get("reason")
                  or "no bundled chromium and no installed Chrome/Edge")
        out["error"] = "no browser: " + reason
        return
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        out["error"] = f"cannot import playwright: {type(e).__name__}: {e}"
        return
    try:
        with sync_playwright() as pw:
            if kwargs.get("executable_path"):
                out["executable"] = kwargs["executable_path"]
                if not Path(out["executable"]).exists():
                    out["error"] = "browser executable not present at that path"
                    return
            elif kwargs.get("channel"):
                out["executable"] = f"channel={kwargs['channel']}"
            else:
                out["executable"] = pw.chromium.executable_path
                if not Path(out["executable"]).exists():
                    out["error"] = "browser binary not present at that path"
                    return
            b = pw.chromium.launch(headless=True, **kwargs)
            b.close()
            out["ok"] = True
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {str(e)[:300]}"


def check_browser():
    """Can Playwright launch the browser `elang run` would pick?"""
    _apply_private_browsers_path()
    result = {"ok": False, "executable": None, "error": None,
              "browsers_path": os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "(default)",
              "sources": None, "choice": None, "launch_kwargs": None}
    try:
        result["sources"] = config.describe_browser()
        result["usable_anywhere"] = config.has_browser()
        result["choice"] = config.browser_choice()
        result["launch_kwargs"] = config.browser_launch_kwargs(result["choice"])
    except Exception:
        pass

    # A launch against a blocked temp directory can hang indefinitely, and a
    # diagnosis command must not do that. Run it on a worker thread with a
    # wall-clock bound; the JSON shape is unchanged.
    probe = {}
    worker = threading.Thread(
        target=_launch_probe,
        args=(result.get("choice") or {}, result.get("launch_kwargs") or {}, probe),
        name="doctor-launch-probe",
        daemon=True,
    )
    worker.start()
    worker.join(LAUNCH_TIMEOUT_S)
    if worker.is_alive():
        if probe.get("executable"):
            result["executable"] = probe["executable"]
        result["error"] = f"launch timed out after {LAUNCH_TIMEOUT_S}s"
        return result
    result["executable"] = probe.get("executable")
    result["error"] = probe.get("error")
    result["ok"] = bool(probe.get("ok"))
    return result


def _redact_credentials(creds):
    """A JSON-safe view of the credential state with NO secret values.

    `elang doctor --json` is meant to be run by agents and captured in
    transcripts, so the username and password must never appear in it. The
    human-readable path already prints only set/MISSING; this keeps the two
    consistent.
    """
    return {
        "ok": creds.get("ok", False),
        "env_file": creds.get("env_file"),
        "env_file_exists": creds.get("env_file_exists"),
        "source": creds.get("source"),
        "username_from": creds.get("username_from"),
        "password_from": creds.get("password_from"),
        "username_set": bool(creds.get("username")),
        "password_set": bool(creds.get("password")),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    mods = check_imports()
    borrowed = check_self_contained(mods)
    browser = check_browser()
    creds = config.load_credentials()

    report = {
        "interpreter": sys.executable,
        "python": sys.version.split()[0],
        "in_venv": sys.prefix != sys.base_prefix,
        "prefix": sys.prefix,
        "modules": mods,
        "borrowed_modules": borrowed,
        "browser": browser,
        "credentials": _redact_credentials(creds),
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if (browser["ok"] and creds["ok"] and not borrowed) else 1

    print("=" * 64)
    print("interpreter :", sys.executable)
    print("python      :", report["python"], "| in venv:", report["in_venv"])
    print("=" * 64)

    print("\n-- modules --")
    for name, info in mods.items():
        state = "ok" if info["found"] else "MISSING"
        print(f"  {name:<12} {state}")
    if borrowed:
        print("\n  WARNING: these come from OUTSIDE this interpreter's tree, so they")
        print("           will not travel to another machine:")
        for b in borrowed:
            print(f"    - {b}")

    print("\n-- browser --")
    if browser.get("sources"):
        print("  " + browser["sources"].replace("\n", "\n  "))
    print(f"  executable  : {browser['executable']}")
    print(f"  launch      : {'ok' if browser['ok'] else 'FAILED'}")
    if browser["error"]:
        print(f"  error       : {browser['error']}")

    print("\n-- credentials --")
    print("  " + config.describe().replace("\n", "\n  "))

    # ---- what to do about it ----
    # The browser fix is emitted as a copy-pasteable block including TEMP/TMP.
    # Playwright creates its temp profile with mkdtemp, and a temp directory the
    # process cannot create in fails with `EPERM ... mkdtemp` — which reads like
    # a Playwright bug but is really a permissions/location problem. Measured on
    # this machine: %LOCALAPPDATA%\Temp hung for >25s while a workspace temp took
    # 0.07s. Naming the variables here saves the caller from rediscovering that.
    fixes = []
    if not browser["ok"]:
        fixes.append("elang install-browser  (downloads chromium, or reuses an "
                     "installed Chrome)")
        if os.name == "nt":
            fixes.append(
                "if a launch then fails with EPERM/mkdtemp, point TEMP at a\n"
                "     writable dir first, e.g.:\n"
                '       $env:TEMP="D:\\tmp"; $env:TMP="D:\\tmp"'
            )
    if not creds["ok"]:
        # `scripts/init_env.py` only exists in a repo checkout. An installed tool
        # has the `elang` console script, so point at that subcommand instead.
        if shutil.which("elang"):
            fixes.append("elang init-env")
        else:
            fixes.append(f'"{sys.executable}" scripts/init_env.py')

    print("\n" + "=" * 64)
    if not fixes and not borrowed:
        print("All good.")
        return 0
    print("TO FIX:")
    for f in fixes:
        print(f"  {f}")
    if borrowed:
        print("  (reinstall into an isolated environment, e.g.")
        print("     uv venv .venv && uv pip install --python .venv/Scripts/python.exe -r requirements.txt)")
    print("=" * 64)
    return 1


if __name__ == "__main__":
    sys.exit(main())
