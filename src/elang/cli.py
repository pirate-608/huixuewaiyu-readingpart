"""Single entry point for the installed tool.

Design: this dispatcher does NOT reimplement anything. Each subcommand runs the
corresponding module's own `main()`, so behaviour is identical whether the user
runs `python scripts/elang_reader.py batch-all` from the repo or `elang run
batch-all` from an installed tool.

    elang doctor            environment / browser / credentials report
    elang init-env          create the .env template
    elang install-browser   download the Chromium build Playwright needs
    elang setup-mcp         write .mcp.json for MCP hosts
    elang install-skill     register the skill with agent roots
    elang run <args...>     drive the solver (batch-all / batch / solve / ...)
    elang mcp               run the MCP server on stdio
"""
import sys
from pathlib import Path

# Support both layouts: package-relative when installed, and the repo's scripts/
# directory when run from a checkout. `elang/__init__.py` already handles the
# installed case; this covers `python src/elang/cli.py` style invocation too.
_HERE = Path(__file__).resolve().parent
_REPO_SCRIPTS = _HERE.parent.parent / "scripts"
for _p in (str(_HERE), str(_REPO_SCRIPTS)):
    if Path(_p).is_dir() and _p not in sys.path:
        sys.path.insert(0, _p)

USAGE = __doc__

# subcommand -> (module name, human description)
SIMPLE = {
    "doctor": ("doctor", "report environment, browser and credential state"),
    "init-env": ("init_env", "create the .env template"),
    "install-browser": ("install_browser", "download the Chromium build Playwright needs"),
    "setup-mcp": ("setup_mcp", "write .mcp.json for MCP hosts"),
    "install-skill": ("install_skill", "register the skill with agent roots"),
}


def _run_module(modname, argv):
    """Import `modname` and call its main()."""
    try:
        mod = __import__(modname)
    except Exception as e:
        print(f"ERROR: cannot import {modname}: {type(e).__name__}: {e}",
              file=sys.stderr)
        return 1
    if not hasattr(mod, "main"):
        print(f"ERROR: {modname} has no main()", file=sys.stderr)
        return 1
    saved = sys.argv
    sys.argv = [f"elang {modname}"] + list(argv)
    try:
        rc = mod.main()
    except SystemExit as e:                     # modules call sys.exit themselves
        rc = e.code if isinstance(e.code, int) else 0
    finally:
        sys.argv = saved
    return rc or 0


def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0

    cmd, rest = argv[0], argv[1:]

    if cmd in SIMPLE:
        return _run_module(SIMPLE[cmd][0], rest)

    if cmd == "run":
        # pass everything through to the solver, e.g. `elang run batch-all`
        if not rest:
            print("ERROR: `elang run` needs solver arguments, e.g. "
                  "`elang run batch-all`", file=sys.stderr)
            return 1
        return _run_module("elang_reader", rest)

    if cmd == "mcp":
        return _run_module("elang_mcp", rest)

    if cmd == "list":
        print("subcommands:")
        for name, (_, desc) in SIMPLE.items():
            print(f"  {name:<15} {desc}")
        print(f"  {'run':<15} drive the solver (batch-all / batch / solve / ...)")
        print(f"  {'mcp':<15} run the MCP server on stdio")
        return 0

    print(f"unknown subcommand: {cmd}\n", file=sys.stderr)
    print(USAGE, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
