#!/usr/bin/env python3
"""Get a browser this tool can launch, reusing an installed Chrome when there is one.

Why a dedicated command
-----------------------
`uv tool install` creates an isolated PYTHON environment but does nothing about
browser BINARIES, which live in a cache of their own. So a freshly installed tool
has no browser and the first launch fails with "Executable doesn't exist".

Two ways to get one
-------------------
1. **An installed Chrome/Edge** (detected, nothing downloaded). Measured on a real
   machine with Chrome 157 and Playwright 1.60: `launch_persistent_context` with
   `executable_path` works headless and headed, runs the site's Vue code, and can
   share one profile directory with the bundled build in either direction.
   Reusing it costs 0 bytes instead of ~683 MB.
2. **The tool's own chromium build**, downloaded into `~/.elang/browsers`.
   Self-contained and version-matched to the Playwright that runs it.

The default is: use whatever is already available, prefer the bundled build, and
only download when neither exists. `--bundled` forces the download.

Why the tool's own directory by default
---------------------------------------
Measured on a real machine: Playwright's shared cache had grown to 1374 MB holding
two generations of chromium (1217 and 1223, each with a full and a headless-shell
build), because different Playwright versions share one directory. Installing into
`~/.elang/browsers` keeps this tool self-contained and bounded. `--shared` uses
the shared cache instead, to reuse whatever is already there.

Why `--no-shell` is NOT used
----------------------------
`playwright install chromium` fetches TWO artifacts: the full chromium and
`chrome-headless-shell`. Headless launches use the shell, so skipping it makes
every headless launch fail with a missing `chrome-headless-shell.exe` — verified
the hard way. Both are installed.

Usage:
    python scripts/install_browser.py             # reuse what exists, else download
    python scripts/install_browser.py --bundled   # always use the tool's own build
    python scripts/install_browser.py --shared    # download into Playwright's cache
    python scripts/install_browser.py --force     # reinstall even when usable
    python scripts/install_browser.py --check     # report only
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bundled", "--download", dest="bundled", action="store_true",
                    help="install the tool's own chromium build even when an "
                         "installed Chrome/Edge could be reused")
    ap.add_argument("--shared", action="store_true",
                    help="install into Playwright's shared cache instead of the "
                         "tool's own (reuses what is already there)")
    ap.add_argument("--force", action="store_true",
                    help="install even when a usable browser already exists")
    ap.add_argument("--check", action="store_true", help="report only")
    args = ap.parse_args()

    print("-- browser situation --")
    print("  " + config.describe_browser().replace("\n", "\n  "))

    choice = config.browser_choice()

    if args.check:
        if choice["mode"] == "none":
            print("\n  MISSING: no browser found.")
            print("  Install one with:  elang install-browser")
            return 1
        print(f"\n  OK: {choice['mode']} browser available")
        print(f"      {choice['label']}"
              f"{' v' + choice['version'] if choice['version'] else ''}")
        print(f"      ({choice['reason']})")
        return 0

    # An installed Chrome/Edge means zero download. Say so once, and explain how
    # to get the bundled build instead — silently preferring a system browser
    # would be surprising, so the reason is always printed.
    if choice["mode"] == "system" and not args.bundled:
        version = f" v{choice['version']}" if choice["version"] else ""
        print(f"\n  Reusing the installed browser: {choice['label']}{version}")
        print(f"  {choice['path']}")
        print(f"  ({choice['reason']})")
        print("\n  Nothing to download.")
        print("  To install the tool's own chromium build instead:")
        print("     elang install-browser --bundled")
        return 0

    # `--force` means "install into the chosen directory even if one is usable".
    # Without it, an existing usable build is reused and nothing is downloaded —
    # the shared cache on a real machine already held a matching build, so
    # re-downloading ~683 MB would have been pure waste.
    if config.has_browser() and not args.force:
        print("\n  Already usable — nothing to install.")
        print("  (use --force to install a second copy anyway, "
              "e.g. to make this tool self-contained)")
        return 0

    # Where to put the build. An explicit PLAYWRIGHT_BROWSERS_PATH wins, because
    # that is where Playwright will look later; otherwise --shared or the private
    # cache. Honouring the variable prevents an install that the next run cannot
    # see.
    override = (os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "").strip()
    if override and override != "0":
        target = Path(override)
    elif args.shared:
        target = config.shared_browsers_dir()
    else:
        target = config.BROWSERS_DIR
    print(f"\n-- installing chromium into {target} --")
    target.mkdir(parents=True, exist_ok=True)
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(target)

    # Both artifacts, deliberately (see the module docstring): headless launches
    # use chrome-headless-shell, so skipping it breaks every headless run.
    cmd = [sys.executable, "-m", "playwright", "install", "chromium"]
    print("  $ " + " ".join(cmd))
    r = subprocess.run(cmd)
    if r.returncode != 0:
        print("\n  FAILED.")
        print("  A network/TLS error here is usually transient — run the command")
        print("  again; it resumes whatever is still missing.")
        return r.returncode

    print("\n-- installed --")
    for sub in sorted(target.glob("chromium*")):
        print(f"  {sub.name}")

    if not config.has_browser():
        print("\n  WARNING: no chromium build found after install.")
        return 1
    print("\n  OK. Verify with:  elang doctor")
    return 0


if __name__ == "__main__":
    sys.exit(main())
