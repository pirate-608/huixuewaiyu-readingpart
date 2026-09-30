#!/usr/bin/env python3
"""MCP server for 慧学外语 reading automation (MCP Level 2).

This is a THIN wrapper: every tool delegates to `ElangSession` (see
`elang_session.py`, MCP Level 1). No browser logic lives here. That separation is
deliberate — when something misbehaves you can tell whether the fault is in the
protocol layer or in the solver, instead of guessing.

Design notes
------------
* **No tool ever blocks waiting for answers.** Every call returns the current
  state plus `next_actions`. An article can sit in `awaiting_answers`
  indefinitely; the timeout dance of the old batch mode is gone.
* **One session per server process.** A single browser, a single run. Running two
  sessions against one browser previously caused two scripts to fight over one
  captcha dialog.
* **The server must run OUTSIDE the DSH file sandbox.** Measured: Playwright's
  driver transport goes through `asyncio.create_subprocess_exec`, which needs a
  NAMED pipe on Windows, and the sandbox denies `CreateFile("\\\\.\\pipe\\...")`
  with WinError 5. The sync API is no different (it wraps asyncio). See
  MCP_DESIGN.md §7.1 / MIGRATION_CHECKPOINT.md §24.

Run:
    python scripts/elang_mcp.py            # stdio transport (normal MCP)
    python scripts/elang_mcp.py --selftest # list the tools and exit
"""
import asyncio
import contextlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


@contextlib.contextmanager
def quiet_stdout():
    """Send anything written to stdout to STDERR instead.

    This is mandatory for stdio transport, not cosmetic. MCP frames JSON-RPC
    messages on **stdout**, one per line, so a single stray `print()` corrupts the
    protocol — the client then fails with:

        Invalid JSON: expected value at line 1 column 2
          input_value='[elang] credentials from...'

    The solver modules print progress lines everywhere (deliberately, they are
    useful when run as a CLI), so rather than strip those out we redirect stdout
    for the duration of a tool call. Diagnostics still appear on stderr, where the
    host shows them.
    """
    saved = sys.stdout
    try:
        sys.stdout = sys.stderr
        yield
    finally:
        sys.stdout = saved


from elang_session import ElangSession, State  # noqa: E402

# The MCP Python SDK renamed its high-level server class in 2.x:
#   mcp 1.x : from mcp.server.fastmcp import FastMCP
#   mcp 2.x : from mcp.server.mcpserver import MCPServer
# Support both rather than pinning, so the server runs on whatever a user's
# environment happens to provide. The decorator surface we use (`@server.tool()`)
# is the same in both.
FastMCP = None
MCPServer = None
_SDK_ERR = None
try:
    from mcp.server.fastmcp import FastMCP  # mcp 1.x
except Exception as e1:
    try:
        from mcp.server.mcpserver import MCPServer  # mcp 2.x
        FastMCP = MCPServer
    except Exception as e2:
        _SDK_ERR = f"1.x: {type(e1).__name__}: {e1} | 2.x: {type(e2).__name__}: {e2}"

try:
    from mcp.server.fastmcp.utilities.types import Image  # noqa: F401  (1.x)
except Exception:
    try:
        from mcp.server.mcpserver.utilities.types import Image  # noqa: F401  (2.x)
    except Exception:
        Image = None


# ---------------------------------------------------------------- session
class Server:
    """Holds the single ElangSession and serialises access to it.

    Concurrency: the browser is single-threaded from our point of view, so every
    tool takes the same lock. This makes it impossible for two tool calls to
    interleave mid-navigation — the exact situation that previously produced
    contradictory readings from one page.
    """

    def __init__(self):
        self.session = None
        self.lock = asyncio.Lock()

    async def ensure(self):
        if self.session is None:
            self.session = ElangSession()
            await self.session.start()
        return self.session


SRV = Server()


def _envelope(env):
    """Serialise the state machine's envelope for MCP (JSON-safe)."""
    return json.dumps(env, ensure_ascii=False, indent=2)


def build_server():
    if FastMCP is None:
        print("ERROR: no usable MCP server class in the installed `mcp` package.",
              file=sys.stderr)
        if _SDK_ERR:
            print(f"  tried: {_SDK_ERR}", file=sys.stderr)
        print("  Install a supported version:  pip install 'mcp>=1.2'", file=sys.stderr)
        return None

    mcp = FastMCP("elang-reading")

    def quiet(fn):
        """Wrap a tool so any progress printing cannot corrupt the protocol."""
        import functools

        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            with quiet_stdout():
                return await fn(*args, **kwargs)
        return wrapper

    # ------------------------------------------------------------ lifecycle
    @mcp.tool()
    @quiet
    async def elang_start(dry_run: bool = False, limit: int = 0) -> str:
        """Open the browser and log in. Must be called before other tools.

        Args:
            dry_run: open the submit dialog but never post the paper.
            limit: stop after this many articles (0 = no limit).
        """
        async with SRV.lock:
            if SRV.session is not None:
                await SRV.session.stop()
            SRV.session = ElangSession(dry_run=dry_run,
                                       limit=(limit or None))
            env = await SRV.session.start()
            return _envelope(env)

    @mcp.tool()
    @quiet
    async def elang_status() -> str:
        """Current state and progress. Never performs an action.

        Deliberately does NOT start a session: a status probe must be safe to call
        at any time, so with nothing running it simply reports `idle`.
        """
        async with SRV.lock:
            if SRV.session is None:
                return _envelope({
                    "state": State.IDLE,
                    "blocking": False,
                    "next_actions": ["elang_start"],
                    "hint": "no session yet; call elang_start first",
                })
            return _envelope(SRV.session.status())

    @mcp.tool()
    @quiet
    async def elang_stop() -> str:
        """Close the browser and end the session."""
        async with SRV.lock:
            if SRV.session is None:
                return _envelope({"state": "idle", "blocking": False,
                                  "next_actions": ["elang_start"]})
            env = await SRV.session.stop()
            SRV.session = None
            return _envelope(env)

    # ------------------------------------------------------------ discovery
    @mcp.tool()
    @quiet
    async def elang_list_subjects() -> str:
        """List the reading subjects on the index page."""
        async with SRV.lock:
            s = await SRV.ensure()
            return _envelope(await s.list_subjects())

    @mcp.tool()
    @quiet
    async def elang_list_lessons(subject_id: str) -> str:
        """List one subject's articles, with completion status."""
        async with SRV.lock:
            s = await SRV.ensure()
            return _envelope(await s.list_lessons(subject_id))

    # ------------------------------------------------------------ advancing
    @mcp.tool()
    @quiet
    async def elang_open_next() -> str:
        """Advance to the next unfinished article.

        Returns the passage and questions when it reaches `awaiting_answers`, or a
        captcha notice when it reaches `awaiting_captcha`. Never waits for input.
        """
        async with SRV.lock:
            s = await SRV.ensure()
            return _envelope(await s.open_next())

    # ------------------------------------------------------------ captcha
    @mcp.tool()
    @quiet
    async def elang_get_captcha() -> str:
        """Describe the pending captcha and save its image to disk.

        Does NOT retry or refresh: a wrong submission makes the app replace the
        image, so retry decisions belong to the caller, not here.
        """
        async with SRV.lock:
            s = await SRV.ensure()
            env = await s.get_captcha()
            return _envelope(env)

    @mcp.tool()
    @quiet
    async def elang_solve_captcha(code: str) -> str:
        """Submit a 4-character captcha code."""
        async with SRV.lock:
            s = await SRV.ensure()
            return _envelope(await s.solve_captcha(code))

    # ------------------------------------------------------------ answering
    @mcp.tool()
    @quiet
    async def elang_submit_answers(answers: list) -> str:
        """Record answers for the current article and submit it.

        `answers` is a list of [qIndex, value]:
          * choice: value is the 0-based option index
          * fill:   value is a list with ONE ENTRY PER BLANK
        qIndex is the 0-based index shown by elang_open_next.

        Invalid answers are rejected before the browser is touched, and the
        session stays in `awaiting_answers` so a corrected call can follow.
        """
        async with SRV.lock:
            s = await SRV.ensure()
            return _envelope(await s.submit_answers(answers))

    @mcp.tool()
    @quiet
    async def elang_skip_article() -> str:
        """Submit the current article without answering it."""
        async with SRV.lock:
            s = await SRV.ensure()
            return _envelope(await s.skip_article())

    return mcp


def main():
    if "--selftest" in sys.argv:
        mcp = build_server()
        if mcp is None:
            return 1
        tools = asyncio.run(mcp.list_tools())
        print(f"[selftest] {len(tools)} tools registered:")
        for t in tools:
            first = (t.description or "").strip().splitlines()
            print(f"  - {t.name}: {first[0] if first else ''}")
        print(f"[selftest] state machine states: "
              f"{[v for k, v in vars(State).items() if not k.startswith('_')]}")
        return 0

    mcp = build_server()
    if mcp is None:
        return 1
    mcp.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
