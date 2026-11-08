#!/usr/bin/env python3
"""Register this tool's MCP server with an agent, safely.

Why three branches
------------------
Each agent reads a DIFFERENT format, so there is no single "config file" to write:

| Agent       | File                              | Format                          |
|-------------|-----------------------------------|---------------------------------|
| Claude Code | `<project>/.mcp.json` (or `~/…`)  | JSON: `{"mcpServers": {...}}`   |
| DSH         | `~/.dsh/profiles/<p>/cordis.patch.yml` | YAML: a top-level LIST     |
| Codex       | `~/.codex/config.toml`            | TOML: `[mcp_servers.<name>]`    |

Safety properties (all of them matter — these are the user's live agent configs,
and `~/.codex/config.toml` holds API keys in plaintext)

* **idempotent**      re-running does not add a second entry
* **atomic**          written via a temp file then replaced
* **reversible**      a backup is taken first, and restored if the result fails
                      to re-parse
* **parse-verified**  the written file is read back and parsed; failure rolls back
* **quiet about contents**  only the ADDED lines are ever printed, never the file
                      body, because it may contain secrets

Usage
-----
    elang setup-mcp --host claude              # <project>/.mcp.json (walks up from cwd)
    elang setup-mcp --host claude --scope global
    elang setup-mcp --host dsh                 # edits the DSH profile patch
    elang setup-mcp --host codex
    elang setup-mcp --host all
    elang setup-mcp --host dsh --dry-run       # show what would change
    elang setup-mcp --print --host codex       # just print the entry

Notes
-----
The server must run OUTSIDE a file sandbox: Playwright reaches its driver through
`asyncio.create_subprocess_exec`, which needs a NAMED pipe on Windows, and
confined sandboxes deny `CreateFile("\\\\.\\pipe\\...")` with WinError 5. Measured,
and the sync API behaves the same. See the sandbox note in AGENTS.md.
"""
import argparse
import datetime
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HOME = Path(os.path.expanduser("~"))
SERVER_NAME = "elang"                     # -> tools appear as mcp__elang__*
CLAUDE_KEY = "elang-reading"              # key inside .mcp.json
DSH_ID = "mcp-elang"
DSH_PLUGIN = "@deepseek-ai/dsh-mcp-client"
TIMEOUT_MS = 120000
TIMEOUT_S = 120


# --------------------------------------------------------------- helpers

def elang_command():
    """The console script this package installs.

    Prefer the installed `elang` (works for a `uv tool install`, which has no repo
    checkout). Fall back to `python -m elang.cli` only when that module actually
    exists. Registering a command that cannot start leaves the host with a server
    that never connects, so report it instead of guessing.
    """
    exe = shutil.which("elang")
    if exe:
        return exe, ["mcp"]
    try:
        spec = importlib.util.find_spec("elang.cli")
    except (ImportError, ValueError):
        spec = None
    if spec is None:
        print("ERROR: no `elang` command on PATH and `elang.cli` is not "
              "importable; install the package first "
              "(uv tool install .)", file=sys.stderr)
        return None
    return sys.executable, ["-m", "elang.cli", "mcp"]


def _backup(path: Path):
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = path.with_name(path.name + f".bak-{ts}")
    shutil.copy2(path, bak)
    return bak


def _atomic_write(path: Path, text: str):
    """Write via a unique sibling temp file then replace.

    The temp file lives in the SAME directory so `os.replace` stays atomic. It is
    created with `mkstemp`, because a fixed name left debris behind after a
    failure and let two concurrent runs clobber each other's temp file.
    """
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".",
                                suffix=".tmp")
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        # Never leave the temp file behind, whatever went wrong.
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _apply(path: Path, new_text: str, verify, dry_run: bool, label: str,
           preview=None):
    """Backup -> write -> re-parse; restore on failure. Returns (ok, added).

    `preview` is the list of lines this change adds. Only that is printed: the
    existing body is never shown, because these files hold other servers' API
    keys. A textual diff of a re-serialized file used to leak all of them.
    """
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    if old == new_text:
        print(f"  [{label}] already up to date: {path}")
        return True, []

    added = list(preview or [])
    print(f"  [{label}] {path}")
    for line in added:
        print(f"      + {line}")
    if dry_run:
        print(f"  [{label}] --dry-run: nothing written")
        return True, added

    path.parent.mkdir(parents=True, exist_ok=True)
    bak = _backup(path) if path.exists() else None
    try:
        _atomic_write(path, new_text)
    except OSError as e:
        # A locked target (a running agent holds the config file) must not abort
        # the remaining hosts: report it and let the caller keep going.
        print(f"  [{label}] FAILED: {type(e).__name__}: {e}")
        return False, added

    try:
        verify(path)
    except Exception as e:
        # Put the original back so a bad edit cannot leave the agent broken.
        if bak is not None:
            shutil.copy2(bak, path)
            print(f"  [{label}] VERIFY FAILED, restored from {bak.name}")
        else:
            path.unlink(missing_ok=True)
            print(f"  [{label}] VERIFY FAILED, removed the new file")
        print(f"  [{label}] {type(e).__name__}: {e}")
        return False, added

    if bak:
        print(f"  [{label}] backup: {bak.name}")
    return True, added


# --------------------------------------------------------------- per host

def entry_claude():
    resolved = elang_command()
    if resolved is None:
        return None
    cmd, args = resolved
    return {"command": cmd, "args": args}


def _project_root() -> Path:
    """Nearest ancestor of cwd that looks like a project root, else cwd.

    An agent may be started in a subdirectory of the project. Registering
    `<cwd>/.mcp.json` then puts the file where the host never looks, so walk up
    the way the hosts themselves resolve a project.
    """
    start = Path.cwd().resolve()
    cur = start
    for _ in range(30):
        for marker in (".git", "pyproject.toml", "SKILL.md", ".mcp.json"):
            if (cur / marker).exists():
                return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return start


def patch_claude(scope, dry_run):
    path = ((HOME / ".claude" / ".mcp.json") if scope == "global"
            else (_project_root() / ".mcp.json"))
    entry = entry_claude()
    if entry is None:
        print("  [claude] cannot register: no runnable `elang` command")
        return False
    cfg = {}
    if path.exists():
        try:
            cfg = json.loads(path.read_text(encoding="utf-8")) or {}
        except Exception as e:
            print(f"  [claude] existing file is not valid JSON: "
                  f"{type(e).__name__}: {e}")
            return False
    servers = cfg.setdefault("mcpServers", {})
    servers[CLAUDE_KEY] = entry
    text = json.dumps(cfg, ensure_ascii=False, indent=2) + "\n"
    preview = json.dumps({"mcpServers": {CLAUDE_KEY: entry}},
                         ensure_ascii=False, indent=2).splitlines()

    def verify(p):
        back = json.loads(p.read_text(encoding="utf-8"))
        assert CLAUDE_KEY in back.get("mcpServers", {}), "entry missing after write"

    ok, _ = _apply(path, text, verify, dry_run, "claude", preview=preview)
    if ok and not dry_run:
        print("      restart Claude Code (or reload the project) to pick it up")
    return ok


def _yaml():
    try:
        import yaml
        return yaml
    except Exception:
        return None


def entry_dsh():
    resolved = elang_command()
    if resolved is None:
        return None
    cmd, args = resolved
    return {
        "id": DSH_ID,
        "name": DSH_PLUGIN,
        "config": {
            "serverName": SERVER_NAME,
            "transport": "stdio",
            "command": cmd,
            "args": args,
            "toolCallTimeoutMs": TIMEOUT_MS,
            # Surface a startup failure instead of silently shipping no tools.
            "failOnStartupError": True,
        },
    }


def _dsh_patch_path():
    profiles = Path(os.environ.get("DSH_HOME") or (HOME / ".dsh")) / "profiles"
    if not profiles.is_dir():
        return None
    # Prefer the active profile when DSH_PROFILE is set, else desktop, else the
    # only profile present.
    names = [os.environ["DSH_PROFILE"]] if os.environ.get("DSH_PROFILE") else []
    names += ["desktop"]
    names += [p.name for p in sorted(profiles.iterdir()) if p.is_dir()]
    for n in names:
        cand = profiles / n / "cordis.patch.yml"
        if cand.exists():
            return cand
    return None


def _dsh_indent(old):
    """Leading whitespace of the existing sequence items, or "" at the root."""
    m = re.search(r"(?m)^([ \t]*)- ", old)
    return m.group(1) if m else ""


def _dsh_render_block(yaml, entry, indent):
    """Render OUR entry as YAML lines at `indent`.

    Only our own entry is rendered and printed; the host config can contain other
    servers with credentials, so its body is never re-serialized or echoed.
    """
    text = yaml.safe_dump([entry], allow_unicode=True, sort_keys=False,
                          default_flow_style=False)
    return [indent + line if line.strip() else line
            for line in text.splitlines()]


def _dsh_append_text(old, block_lines):
    stripped = old.strip()
    if stripped in ("", "[]"):
        # Empty document or an empty list: the block alone is the list.
        return "\n".join(block_lines) + "\n"
    body = old if old.endswith("\n") else old + "\n"
    return body + "\n".join(block_lines) + "\n"


def _dsh_replace_text(yaml, old, entry, indent):
    """Replace the existing `- id: mcp-elang` item textually.

    Returns None when the block boundaries cannot be located, so the caller can
    fall back to a full re-serialization (which drops comments; it says so).
    """
    try:
        root = yaml.compose(old)
    except Exception:
        return None
    if not isinstance(root, yaml.nodes.SequenceNode):
        return None
    nodes = root.value
    target = None
    next_line = None
    for i, node in enumerate(nodes):
        if not isinstance(node, yaml.nodes.MappingNode):
            continue
        ids = [v for k, v in node.value if k.value == "id"]
        if ids and getattr(ids[0], "value", None) == DSH_ID:
            target = node
            if i + 1 < len(nodes):
                next_line = nodes[i + 1].start_mark.line
            break
    if target is None:
        return None
    lines = old.splitlines()
    start = target.start_mark.line
    end = next_line if next_line is not None else len(lines)
    # Leave trailing blank lines / comments with whatever follows them.
    while end > start and (lines[end - 1].strip() == ""
                           or lines[end - 1].lstrip().startswith("#")):
        end -= 1
    block = _dsh_render_block(yaml, entry, indent)
    new_lines = lines[:start] + block + lines[end:]
    return "\n".join(new_lines).rstrip("\n") + "\n"


def patch_dsh(scope, dry_run):
    if scope == "project":
        print("  [dsh] project scope is not supported for MCP registration yet; "
              "using the profile config")
    path = _dsh_patch_path()
    if path is None:
        print("  [dsh] could not find a cordis.patch.yml under "
              f"{HOME / '.dsh' / 'profiles'}")
        return False

    yaml = _yaml()
    entry = entry_dsh()
    if entry is None:
        print("  [dsh] cannot register: no runnable `elang` command")
        return False
    old = path.read_text(encoding="utf-8") if path.exists() else "[]"

    if yaml is not None:
        try:
            data = yaml.safe_load(old) if old.strip() else []
        except Exception as e:
            print(f"  [dsh] existing YAML does not parse: {type(e).__name__}: {e}")
            return False
        if data is None:
            data = []
        if not isinstance(data, list):
            print(f"  [dsh] expected a top-level list, found {type(data).__name__}")
            return False

        idx = next((i for i, e in enumerate(data)
                    if isinstance(e, dict) and e.get("id") == DSH_ID), None)
        if idx is not None and data[idx] == entry:
            print(f"  [dsh] already up to date: {path}")
            return True

        indent = _dsh_indent(old)
        block = _dsh_render_block(yaml, entry, indent)
        if idx is None:
            # Append textually: parsing + re-dumping would delete the operator's
            # comments and re-indent the whole profile.
            text = _dsh_append_text(old, block)
        else:
            text = _dsh_replace_text(yaml, old, entry, indent)
            if text is None:
                print("  [dsh] could not locate the existing entry textually; "
                      "rewriting the file (comments may be lost)")
                data[idx] = entry
                text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False,
                                      default_flow_style=False)
                block = text.splitlines()

        def verify(p):
            back = _yaml().safe_load(p.read_text(encoding="utf-8"))
            assert isinstance(back, list), "not a list after write"
            assert any(isinstance(e, dict) and e.get("id") == DSH_ID for e in back), \
                "entry missing after write"

        ok, _ = _apply(path, text, verify, dry_run, "dsh", preview=block)
        if ok and not dry_run:
            print("      restart DSH so the profile recomposes")
            print("      NOTE: the server needs to run OUTSIDE a file sandbox "
                  "(Playwright requires a named pipe)")
        return ok

    # ---- no pyyaml: append a minimal, correctly-indented block instead --------
    # Refusing to edit is worse than a careful append here: this file is a flat
    # sequence, the shape we append is fixed, and we re-parse nothing because we
    # cannot. So we say so explicitly.
    print("  [dsh] pyyaml is unavailable; falling back to a literal append.")
    print("        Install it for verified edits: pip install pyyaml")
    block = _dsh_yaml_block(entry)
    if DSH_ID in old:
        print(f"  [dsh] a '{DSH_ID}' entry already exists — remove it first, "
              f"or install pyyaml so it can be replaced in place.")
        return False
    text = old.rstrip("\n") + "\n" + block
    ok, _ = _apply(path, text, lambda p: None, dry_run, "dsh",
                   preview=block.splitlines())
    if ok and not dry_run:
        print("      restart DSH; verify the profile still loads")
    return ok


def _dsh_yaml_block(entry):
    """Render the DSH entry as YAML by hand (only used with no pyyaml)."""
    c = entry["config"]
    q = lambda s: "'" + str(s).replace("'", "''") + "'"
    lines = [
        f"  - id: {entry['id']}",
        f"    name: {q(entry['name'])}",
        "    config:",
        f"      serverName: {c['serverName']}",
        f"      transport: {c['transport']}",
        f"      command: {q(c['command'])}",
        f"      args: [{', '.join(q(a) for a in c['args'])}]",
        f"      toolCallTimeoutMs: {c['toolCallTimeoutMs']}",
        f"      failOnStartupError: {'true' if c['failOnStartupError'] else 'false'}",
    ]
    return "\n".join(lines) + "\n"


def entry_codex():
    resolved = elang_command()
    if resolved is None:
        return None
    cmd, args = resolved
    return {"command": cmd, "args": args, "startup_timeout_sec": TIMEOUT_S}


def _toml_quote(s):
    """TOML basic string with the characters that matter escaped."""
    out = str(s).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{out}"'


def _codex_block(entry):
    """Canonical rendering of the Codex table, used for both write and compare."""
    return "\n".join([
        f"[mcp_servers.{SERVER_NAME}]",
        f"command = {_toml_quote(entry['command'])}",
        "args = [" + ", ".join(_toml_quote(a) for a in entry["args"]) + "]",
        f"startup_timeout_sec = {entry['startup_timeout_sec']}",
    ]) + "\n"


def patch_codex(scope, dry_run):
    entry = entry_codex()
    if entry is None:
        print("  [codex] cannot register: no runnable `elang` command")
        return False
    path = (Path(os.environ.get("CODEX_HOME") or (HOME / ".codex"))
            / "config.toml")
    old = path.read_text(encoding="utf-8") if path.exists() else ""

    header = f"[mcp_servers.{SERVER_NAME}]"
    if header in old:
        # Idempotent when nothing would change: compare our canonical rendering
        # against the existing block. A re-run then reports "up to date" like the
        # other hosts. If it DIFFERS, a hand-edited table may exist, and rewriting
        # a live agent config (this file holds API keys) is not something to guess
        # at — say so instead.
        want = _codex_block(entry)
        start = old.index(header)
        rest = old[start + len(header):]
        nxt = rest.find("\n[")
        existing = (header + rest if nxt == -1
                    else header + rest[:nxt])
        existing = existing.rstrip("\n") + "\n"
        if existing == want:
            print(f"  [codex] already up to date: {path}")
            return True
        print(f"  [codex] {path}")
        print(f"      a differing {header} table already exists. Refusing to "
              f"rewrite a live config — edit it by hand, or remove that table "
              f"and re-run.")
        print(f"      wanted:\n" + "".join(f"        {l}\n" for l in want.splitlines()))
        return False

    block = _codex_block(entry)
    text = (old.rstrip("\n") + "\n\n" + block) if old.strip() else block

    def verify(p):
        try:
            import tomllib
        except Exception:
            return          # cannot verify; the caller still backs up
        with open(p, "rb") as f:
            back = tomllib.load(f)
        assert SERVER_NAME in back.get("mcp_servers", {}), \
            "entry missing after write"

    ok, _ = _apply(path, text, verify, dry_run, "codex",
                   preview=_codex_block(entry).splitlines())
    if ok and not dry_run:
        print("      restart Codex to pick it up")
    return ok


# --------------------------------------------------------------- main

HOSTS = {"claude": patch_claude, "dsh": patch_dsh, "codex": patch_codex}


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="claude",
                    help="claude | dsh | codex | all  (default: claude)")
    ap.add_argument("--scope", choices=("project", "global"), default="project",
                    help="where to register (claude: project or global; "
                         "dsh/codex: always their own config)")
    ap.add_argument("--dry-run", action="store_true",
                    help="show the change without writing")
    ap.add_argument("--print", dest="show", action="store_true",
                    help="print the entry and exit")
    args = ap.parse_args()

    if args.show:
        resolved = elang_command()
        if resolved is None:
            print("ERROR: cannot build an MCP entry without a runnable "
                  "`elang` command")
            return 1
        cmd, cmdargs = resolved
        print(json.dumps({
            "claude": {"mcpServers": {CLAUDE_KEY: entry_claude()}},
            "dsh": entry_dsh(),
            "codex": entry_codex(),
        }, ensure_ascii=False, indent=2))
        print(f"\n  resolved command: {cmd} {' '.join(cmdargs)}")
        return 0

    wanted = ([h.strip() for h in args.host.split(",") if h.strip()]
              if args.host != "all" else list(HOSTS))
    unknown = [h for h in wanted if h not in HOSTS]
    if unknown:
        print(f"ERROR: unknown host(s): {', '.join(unknown)}")
        print(f"       known: {', '.join(HOSTS)}")
        return 1

    print(f"MCP registration  (server name: {SERVER_NAME} -> "
          f"tools appear as mcp__{SERVER_NAME}__*)")
    print(f"  scope: {args.scope}{'   [dry-run]' if args.dry_run else ''}")
    print()

    rc = 0
    for h in wanted:
        if not HOSTS[h](args.scope, args.dry_run):
            rc = 1
        print()

    if rc == 0 and not args.dry_run:
        print("Registered. Restart (or reload) the agent so it reconnects.")
        print("Verify afterwards with:  elang doctor")
    return rc


if __name__ == "__main__":
    sys.exit(main())
