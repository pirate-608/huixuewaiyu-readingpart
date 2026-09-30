#!/usr/bin/env python3
"""Install the Chromium build that this tool's Playwright version expects.

Why a dedicated command
-----------------------
`uv tool install` creates an isolated PYTHON environment but does nothing about
browser BINARIES, which live in a cache of their own. So a freshly installed tool
has no browser and the first launch fails with "Executable doesn't exist".

Why it installs into the tool's OWN directory
---------------------------------------------
Measured on a real machine, Playwright's shared cache had grown to 1374 MB holding
two generations of chromium (1217 and 1223, each with a full and a headless-shell
build), because different Playwright versions share one directory. Installing into
`~/.elang/browsers` keeps this tool self-contained and bounded.

`--shared` installs into Playwright's shared cache instead, which reuses whatever
is already there at the cost of that shared-directory growth.

Why `--no-shell` is NOT used
----------------------------
`playwright install chromium` fetches TWO artifacts: the full chromium and
`chrome-headless-shell`. Headless launches use the shell, so skipping it makes
every headless launch fail with a missing `chrome-headless-shell.exe` — verified
the hard way. Both are installed.

Usage:
    python scripts/install_browser.py             # into the tool's own cache
    python scripts/install_browser.py --shared    # into Playwright's shared cache
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
    ap.add_argument("--shared", action="store_true",
                    help="install into Playwright's shared cache instead of the "
                         "tool's own (reuses what is already there)")
    ap.add_argument("--force", action="store_true",
                    help="install even when a usable browser already exists")
    ap.add_argument("--check", action="store_true", help="report only")
    args = ap.parse_args()

    print("-- browser situation --")
    print("  " + config.describe_browser().replace("\n", "\n  "))

    usable = config.has_browser()

    if args.check:
        if usable:
            print("\n  OK: a browser build is available.")
            return 0
        print("\n  MISSING: no chromium build found.")
        print("  Install it with:  elang install-browser")
        return 1

    # `--force` means "install into the chosen directory even if one is usable".
    # Without it, an existing usable build is reused and nothing is downloaded —
    # the shared cache on a real machine already held a matching build, so
    # re-downloading ~683 MB would have been pure waste.
    if usable and not args.force:
        print("\n  Already usable — nothing to install.")
        print("  (use --force to install a second copy anyway, "
              "e.g. to make this tool self-contained)")
        return 0

    target = config.shared_browsers_dir() if args.shared else config.BROWSERS_DIR
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
