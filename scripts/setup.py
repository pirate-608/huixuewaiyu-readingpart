#!/usr/bin/env python3
"""Set up this repo: install the tool, register the skill, report state.

Architecture
------------
Two separate artifacts, deliberately:

  * **the tool** — a normal Python package installed by `uv tool install` into its
    own isolated environment (`elang` on PATH). It owns the MCP server and the
    solver. Its dependencies never touch the system interpreter.
  * **the skill** — documentation only: the contract telling an agent which
    commands to run. `install_skill.py` places it where DSH / Codex / Claude Code
    discover skills.

So this script does NOT create a project venv, and does NOT pip-install anything:
`uv tool install` already produced a self-contained environment. A repo checkout
may still keep a `.venv` for development, but that is not what end users need.

Usage:
    python scripts/setup.py              # install tool + register skill + report
    python scripts/setup.py --check      # report only, change nothing
    python scripts/setup.py --no-tool    # skip tool installation
    python scripts/setup.py --no-skill   # skip skill registration
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def run(cmd, timeout=1800):
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, ((r.stdout or "") + (r.stderr or "")).strip()
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def elang_cmd():
    """The installed console script, if the tool is present."""
    return shutil.which("elang")


def install_tool(check_only):
    print("\n[1/3] tool")
    existing = elang_cmd()
    if existing:
        print(f"  already installed: {existing}")
        if check_only:
            return True
        print("  reinstalling from this checkout (uv tool install --force)")
    elif check_only:
        print("  NOT installed (no `elang` on PATH)")
        print("  install with: uv tool install git+<repo-url>")
        return False

    if not shutil.which("uv"):
        print("  FAILED: `uv` not found on PATH.")
        print("  Install uv first: https://docs.astral.sh/uv/")
        print("  (A plain venv also works: python -m venv .venv, then run "
              "scripts/elang_reader.py from the repo.)")
        return False

    ok, out = run(["uv", "tool", "install", "--force", str(REPO)])
    for line in out.splitlines()[-8:]:
        print("  " + line)
    if not ok:
        return False
    print(f"  installed -> {elang_cmd()}")
    return True


def register_skill(check_only):
    print("\n[2/3] skill")
    script = REPO / "scripts" / "install_skill.py"
    if not script.exists():
        print("  install_skill.py missing; skipping")
        return False
    py = sys.executable
    args = [py, str(script), "--copy"] + (["--check"] if check_only else [])
    ok, out = run(args)
    for line in out.splitlines():
        print("  " + line)
    return ok


def report():
    print("\n[3/3] state")
    elang = elang_cmd()
    if not elang:
        print("  tool not installed; cannot report.")
        print("  Run `python scripts/setup.py` to install it, or use the repo "
              "checkout directly via scripts/doctor.py.")
        return False
    ok, out = run([elang, "doctor"])
    for line in out.splitlines():
        print("  " + line)
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="report only")
    ap.add_argument("--no-tool", action="store_true")
    ap.add_argument("--no-skill", action="store_true")
    args = ap.parse_args()

    print("=" * 64)
    print("  elang reading solver — setup")
    print("=" * 64)
    print(f"repo: {REPO}")

    if not args.no_tool:
        install_tool(args.check)
    if not args.no_skill:
        register_skill(args.check)
    report()

    print("\n" + "=" * 64)
    print("Next steps")
    print("=" * 64)
    print("  1. Credentials (if missing):")
    print("       elang init-env          # creates a template in the workspace root")
    print("  2. Confirm everything is ready:")
    print("       elang doctor            # follow any command it prints")
    print("  3. Use it:")
    print("       elang run batch-all     # or ask your agent to run the skill")
    return 0


if __name__ == "__main__":
    sys.exit(main())
