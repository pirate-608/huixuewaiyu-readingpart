#!/usr/bin/env python3
"""Report this tool's runtime state, and print the commands to fix what is missing.

Design note — why this only REPORTS and never auto-installs a browser:

Browser binaries live in a version-keyed shared cache, and which build is needed
depends on the Playwright version in whatever environment the tool runs in. Rather
than hard-code a path or pin a build (which goes stale and varies per machine),
this prints the exact command and lets the caller decide. An agent running the
skill can read the output and run the command itself.

Usage:
    python scripts/doctor.py
    python scripts/doctor.py --json
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402


def check_imports():
    import importlib.util as u
    mods = {}
    for m in ("playwright", "dotenv", "mcp", "ddddocr"):
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


def check_browser():
    """Can Playwright launch? Report the executable and which cache it came from."""
    result = {"ok": False, "executable": None, "error": None,
              "browsers_path": os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "(default)",
              "sources": None}
    try:
        result["sources"] = config.describe_browser()
        result["usable_anywhere"] = config.has_browser()
    except Exception:
        pass
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        result["error"] = f"cannot import playwright: {type(e).__name__}: {e}"
        return result
    try:
        with sync_playwright() as pw:
            result["executable"] = pw.chromium.executable_path
            exists = Path(result["executable"]).exists()
            result["binary_exists"] = exists
            if not exists:
                result["error"] = "browser binary not present at that path"
                return result
            b = pw.chromium.launch(headless=True)
            b.close()
            result["ok"] = True
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {str(e)[:300]}"
    return result


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
        "credentials": creds,
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
        fixes.append('elang install-browser')
        if os.name == "nt":
            fixes.append(
                "if a launch then fails with EPERM/mkdtemp, point TEMP at a\n"
                "     writable dir first, e.g.:\n"
                '       $env:TEMP="D:\\tmp"; $env:TMP="D:\\tmp"'
            )
    if not creds["ok"]:
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
