#!/usr/bin/env python3
"""Generate a working MCP registration for this checkout.

Machine-specific absolute paths must not live in git, so `.mcp.json` is generated
from `.mcp.json.example` (which is committed) by resolving:

  {{PYTHON}}   the interpreter that can `import mcp` — the workspace venv is
               preferred, otherwise the running interpreter
  {{SCRIPT}}   this checkout's scripts/elang_mcp.py
  {{IPC_DIR}}  where IPC artifacts go (default: <repo>/temp/ipc)

Usage
-----
    python scripts/setup_mcp.py               # write ./.mcp.json
    python scripts/setup_mcp.py --print       # show it, change nothing
    python scripts/setup_mcp.py --host dsh    # also print host-specific notes

Notes
-----
The server must run OUTSIDE a file sandbox: Playwright reaches its driver through
`asyncio.create_subprocess_exec`, which on Windows needs a NAMED pipe, and
confined sandboxes deny `CreateFile("\\\\.\\pipe\\...")` with WinError 5. Measured,
and the sync API is no different. See MCP_DESIGN.md §7.1.
"""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TEMPLATE = REPO / ".mcp.json.example"
OUT = REPO / ".mcp.json"

HOST_NOTES = {
    "claude": [
        "Claude Code reads ./.mcp.json from the project root (this file).",
        "Or register it explicitly:",
        "  claude mcp add elang-reading -- <python> <repo>/scripts/elang_mcp.py",
    ],
    "dsh": [
        "DSH composes MCP servers through its cordis profile.",
        "Add an entry to your profile's cordis.patch.yml with the same",
        "command/args/env values, then restart DSH so the profile recomposes.",
        "Grant the server full file access once: its transport needs a named pipe.",
    ],
    "codex": [
        "Codex reads the same skill roots as DSH (~/.agents/skills).",
        "Register the MCP server with the command/args/env below using that",
        "host's own MCP configuration.",
    ],
}


def pick_python():
    """Choose an interpreter that can actually `import mcp`.

    The workspace venv comes first: it is created with `--system-site-packages`, so
    it inherits `mcp` from the system interpreter, and it never depends on the
    user's skill directory. A skill venv built with `--without-pip` cannot install
    `mcp` itself, which is exactly why it must not be preferred here.
    """
    bindir = "Scripts" if os.name == "nt" else "bin"
    exe = "python.exe" if os.name == "nt" else "python"
    candidates = [
        REPO / ".venv" / bindir / exe,
        Path(sys.executable),
    ]
    for c in candidates:
        if not c.exists():
            continue
        try:
            import importlib.util as u
            if u.find_spec("mcp") is not None:
                return str(c)
        except Exception:
            pass
    for c in candidates:
        if c.exists():
            return str(c)
    return sys.executable


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--print", dest="show", action="store_true",
                    help="print the config instead of writing it")
    ap.add_argument("--host", default="",
                    help="also print registration notes: claude,dsh,codex")
    ap.add_argument("--ipc-dir", default="", help="override the IPC directory")
    args = ap.parse_args()

    if not TEMPLATE.exists():
        print(f"ERROR: template missing: {TEMPLATE}")
        return 1

    python = pick_python()
    script = REPO / "scripts" / "elang_mcp.py"
    ipc = Path(args.ipc_dir).expanduser() if args.ipc_dir else (REPO / "temp" / "ipc")

    if not script.exists():
        print(f"ERROR: server script missing: {script}")
        return 1

    text = TEMPLATE.read_text(encoding="utf-8")
    # Substitute into the PARSED structure, not the raw text: on Windows the
    # resolved paths contain backslashes (D:\...), and injecting those into JSON
    # text produces invalid escapes. Building the object and re-serialising lets
    # json handle the escaping.
    try:
        cfg = json.loads(text)
    except Exception as e:
        print(f"ERROR: template is not valid JSON: {type(e).__name__}: {e}")
        return 1

    entry = cfg["mcpServers"]["elang-reading"]
    entry["command"] = python
    entry["args"] = [str(script)]
    entry["env"] = dict(entry.get("env") or {})
    entry["env"]["ELANG_TMP_DIR"] = str(ipc)

    text = json.dumps(cfg, ensure_ascii=False, indent=2) + "\n"

    if args.show:
        print(text)
    else:
        OUT.write_text(text, encoding="utf-8")
        print(f"wrote {OUT}")
        for k, v in entry.items():
            print(f"  {k}: {v}")

    # Sanity: the interpreter must be able to import mcp AND be able to start a
    # browser. Both have bitten us:
    #   * a venv built with --without-pip cannot install mcp at all
    #   * a venv built with --system-site-packages only *looks* fine, because the
    #     import is satisfied by the user's global packages
    # So check the interpreter's OWN site-packages, not just importability.
    problems = []
    import subprocess
    probe = (
        "import importlib.util as u, json, sys;"
        "spec=u.find_spec('mcp');"
        "origin=(spec.origin or '') if spec else '';"
        "print(json.dumps({'exe':sys.executable,"
        "'mcp':bool(spec),'origin':origin,"
        "'playwright':bool(u.find_spec('playwright'))}))"
    )
    try:
        out = subprocess.run([python, "-c", probe], capture_output=True,
                             text=True, timeout=60)
        info = json.loads(out.stdout.strip().splitlines()[-1])
        print(f"\n  interpreter : {info['exe']}")
        print(f"  mcp         : {info['mcp']}  {info['origin']}")
        print(f"  playwright  : {info['playwright']}")
        if not info["mcp"]:
            problems.append("cannot import `mcp`")
        if not info["playwright"]:
            problems.append("cannot import `playwright`")
        # warn when the dependency comes from outside the interpreter's own tree
        if info["mcp"] and info["origin"]:
            own = str(Path(python).parent.parent).lower()
            if own not in info["origin"].lower():
                problems.append(
                    f"`mcp` resolves OUTSIDE this interpreter ({info['origin']}) — "
                    f"it is coming from a global install, which will not travel "
                    f"to another machine")
    except Exception as e:
        problems.append(f"probe failed: {type(e).__name__}: {e}")

    if problems:
        print("\nWARNING: this interpreter is not self-contained:")
        for p in problems:
            print(f"  - {p}")
        print("  Create an isolated venv and install requirements into it:")
        print("    uv venv .venv")
        print("    uv pip install --python .venv/Scripts/python.exe -r requirements.txt")
        print("    .venv/Scripts/python.exe -m playwright install chromium")
        rc = 1
    else:
        rc = 0

    hosts = [h.strip() for h in args.host.split(",") if h.strip()]
    for h in hosts:
        notes = HOST_NOTES.get(h)
        if notes:
            print(f"\n[{h}]")
            for n in notes:
                print(f"  {n}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
