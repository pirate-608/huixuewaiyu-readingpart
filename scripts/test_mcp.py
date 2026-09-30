#!/usr/bin/env python3
"""Drive the MCP server over the real stdio protocol.

Calling the tool functions in-process would not prove the protocol layer works
(schemas, JSON serialisation, transport). This spawns `elang_mcp.py` as a
subprocess and talks MCP to it.

NOTE: the SERVER must be able to start a browser, which the DSH file sandbox
forbids (named pipes). So the browser-touching tools will fail here unless the
test itself runs outside the sandbox. The protocol steps —
initialize / list_tools / call_tool — are still worth verifying.

Usage:
    python scripts/test_mcp.py            # protocol only (no browser calls)
    python scripts/test_mcp.py --browser  # also exercise elang_start
"""
import asyncio
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


async def main():
    do_browser = "--browser" in sys.argv
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except Exception as e:
        print(f"ERROR: mcp client import failed: {type(e).__name__}: {e}")
        return 1

    # The server inherits OUR environment. Passing env=None would drop the
    # ELANG_* overrides (notably ELANG_PROFILE_DIR), which then silently falls back
    # to the default profile under the user's home.
    child_env = os.environ.copy()
    server = StdioServerParameters(
        command=sys.executable,
        args=[str(HERE / "elang_mcp.py")],
        env=child_env,
    )
    print(f"[test] child ELANG_PROFILE_DIR={child_env.get('ELANG_PROFILE_DIR')}")
    print(f"[test] child ELANG_TMP_DIR={child_env.get('ELANG_TMP_DIR')}")
    print(f"[test] child TEMP={child_env.get('TEMP')}")

    print("[test] starting server over stdio...")
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("[test] initialize OK")

            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            print(f"[test] {len(names)} tools: {names}")

            # every tool must declare an input schema
            for t in tools.tools:
                schema = getattr(t, "inputSchema", None)
                has = bool(schema and schema.get("properties") is not None)
                print(f"  - {t.name:<22} schema={'yes' if has else 'NO'}")

            # a read-only call that must not need a browser to *parse*
            print("\n[test] calling elang_status (no browser yet)...")
            res = await session.call_tool("elang_status", {})
            text = "".join(c.text for c in res.content if hasattr(c, "text"))
            print(f"  isError={res.isError}")
            print(f"  {text[:300]}")

            if do_browser:
                print("\n[test] calling elang_start (starts a browser)...")
                res = await session.call_tool("elang_start",
                                              {"dry_run": True, "limit": 1})
                text = "".join(c.text for c in res.content
                               if hasattr(c, "text"))
                print(f"  isError={res.isError}")
                try:
                    env = json.loads(text)
                    print(f"  state={env.get('state')} "
                          f"blocking={env.get('blocking')} "
                          f"next={env.get('next_actions')}")
                except Exception:
                    print(f"  raw: {text[:400]}")

                print("\n[test] calling elang_stop...")
                res = await session.call_tool("elang_stop", {})
                text = "".join(c.text for c in res.content
                               if hasattr(c, "text"))
                print(f"  isError={res.isError} {text[:200]}")

    print("\n[test] protocol round-trip complete")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
