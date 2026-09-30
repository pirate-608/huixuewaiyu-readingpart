#!/usr/bin/env python3
"""Launch the MCP server exactly as `.mcp.json` specifies, and drive it.

This is the end-to-end check that the generated registration is CORRECT — not
just well-formed JSON. It reads `.mcp.json`, spawns the server with that exact
command/args/env, and runs a real sequence:

    initialize -> list_tools -> elang_status -> elang_start
              -> elang_list_subjects -> elang_stop

Run it OUTSIDE a file sandbox: the stdio client itself needs a named pipe on
Windows (asyncio.create_subprocess_exec -> CreateFile("\\\\.\\pipe\\...")), which
confined sandboxes deny.

Usage:
    python scripts/test_mcp_e2e.py            # config + protocol only
    python scripts/test_mcp_e2e.py --browser  # also start a real browser
"""
import asyncio
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CFG = REPO / ".mcp.json"

# The console here is GBK; the browser errors carry characters it cannot encode,
# which would crash the test instead of reporting the failure.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


async def main():
    do_browser = "--browser" in sys.argv
    if not CFG.exists():
        print(f"ERROR: {CFG} not found. Run: python scripts/setup_mcp.py")
        return 1

    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    entry = cfg["mcpServers"]["elang-reading"]
    print("[e2e] registration from .mcp.json:")
    print(f"      command: {entry['command']}")
    print(f"      args   : {entry['args']}")
    print(f"      env    : {entry.get('env')}")

    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except Exception as e:
        print(f"ERROR: mcp client import failed: {type(e).__name__}: {e}")
        return 1

    # merge the registration's env over our own, exactly as a host would
    child_env = os.environ.copy()
    child_env.update(entry.get("env") or {})
    # The browser needs a temp dir it can actually create in. Measured on this
    # machine: mkdtemp under %LOCALAPPDATA%\Temp hangs (>25s) because that path is
    # outside the workspace and every operation is intercepted by the file policy;
    # pointing TEMP/TMP inside the workspace makes it 0.07s. Playwright surfaces
    # the same problem as `EPERM: operation not permitted, mkdtemp`.
    # Force the override (setdefault would not replace an inherited TEMP).
    pwtmp = REPO / "temp" / "pwtmp"
    pwtmp.mkdir(parents=True, exist_ok=True)
    child_env["TEMP"] = str(pwtmp)
    child_env["TMP"] = str(pwtmp)
    # Same class of problem for the browser profile: the default lives under the
    # user's home, which this sandboxed run cannot write (Chrome reports
    # "Lock file can not be created! Error code: 5"). Point it inside the
    # workspace for the test. A real deployment runs the server unsandboxed, where
    # the home-dir default is correct — hence this is a TEST-only override.
    profile = REPO / "temp" / "profile"
    profile.mkdir(parents=True, exist_ok=True)
    child_env["ELANG_PROFILE_DIR"] = str(profile)

    server = StdioServerParameters(command=entry["command"],
                                   args=entry["args"],
                                   env=child_env)


    async def text_of(session, name, args=None):
        res = await session.call_tool(name, args or {})
        body = "".join(c.text for c in res.content if hasattr(c, "text"))
        # mcp 2.x renamed `isError` -> `is_error`
        is_err = getattr(res, "isError", None)
        if is_err is None:
            is_err = getattr(res, "is_error", False)
        return bool(is_err), body

    print("\n[e2e] starting server exactly as registered...")
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("[e2e] initialize OK")

            tools = await session.list_tools()
            print(f"[e2e] {len(tools.tools)} tools available")

            err, body = await text_of(session, "elang_status")
            env = json.loads(body)
            print(f"[e2e] elang_status -> state={env.get('state')} "
                  f"isError={err} (must not start a browser)")

            if not do_browser:
                print("\n[e2e] OK (protocol verified; pass --browser for full run)")
                return 0

            err, body = await text_of(session, "elang_start",
                                      {"dry_run": True, "limit": 1})
            env = json.loads(body)
            print(f"[e2e] elang_start  -> state={env.get('state')} "
                  f"blocking={env.get('blocking')} isError={err}")
            if env.get("state") == "error":
                print(f"       error: {env.get('error')}")
                return 1
            if env.get("blocking"):
                print("       PROBLEM: a tool reported blocking=True")
                return 1

            err, body = await text_of(session, "elang_list_subjects")
            env = json.loads(body)
            subs = env.get("subjects") or []
            print(f"[e2e] elang_list_subjects -> {len(subs)} subjects, "
                  f"isError={err}")
            for s in subs[:5]:
                print(f"         id={s['id']:<5} {s['name']} ({s['resource_num']})")

            err, body = await text_of(session, "elang_stop")
            env = json.loads(body)
            print(f"[e2e] elang_stop -> state={env.get('state')} isError={err}")

    print("\n[e2e] end-to-end OK: the registered config drives the solver")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
