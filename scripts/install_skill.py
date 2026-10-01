#!/usr/bin/env python3
"""Register this skill with DSH, Codex and/or Claude Code.

Why one script instead of three
-------------------------------
All three agents use the SAME skill contract — a directory bundle containing
`SKILL.md` with YAML frontmatter (`name`, `description`) — and differ only in
which roots they scan. Verified against the DSH runtime:

| Scope   | Agent       | Root                                        |
|---------|-------------|---------------------------------------------|
| global  | DSH         | `~/.dsh/skills`        (rank 400)           |
| global  | DSH / Codex | `~/.agents/skills`     (rank 500)           |
| global  | Claude Code | `~/.claude/skills`                          |
| project | DSH         | `<project>/.dsh/skills`     (rank 100)      |
| project | DSH / Codex | `<project>/.agents/skills`  (rank 200)      |
| project | Claude Code | `<project>/.claude/skills`                  |

**DSH and Codex share `~/.agents/skills`**, so installing for both writes one
directory. `~`/`<dshHome>`/`<agentsHome>` honour `DSH_HOME` / `DSH_AGENTS_HOME`.

DSH scans roots **one level deep** and expects `<root>/<name>/SKILL.md`, so the
skill is installed as a directory named after it — never as a bare `SKILL.md`.

Global vs project
-----------------
* **global** — available in every project; nothing lands in your repo.
* **project** — lives in the project and wins over the global copy in every host
  (DSH ranks project roots 100/200 above global 400/500). Because it sits inside
  the project, it can be committed so teammates get it with the checkout.

Install strategies
------------------
`--copy`  (default) copy the payload. Works everywhere; re-run after changes.
`--link`  point the agent at this checkout. Source edits are live and nothing is
          duplicated, but only works from a repo (an installed tool has no repo)
          and requires symlink support (a Windows junction is used automatically
          when available).

Usage
-----
    install_skill.py --agent claude                  # global, Claude Code only
    install_skill.py --agent dsh,codex --scope project
    install_skill.py --scope project                 # every agent, this project
    install_skill.py --scope all                     # global + project
    install_skill.py --link                          # repo checkout, all agents
    install_skill.py --check                         # report only
    install_skill.py --uninstall --agent claude
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

# The Windows console defaults to GBK here; the docstring uses em dashes and an
# agent may run this with Chinese paths, so force UTF-8 rather than mojibake.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = Path(__file__).resolve().parent.parent
SKILL_NAME = "huixuewaiyu-readingpart"

# Payload entries as (source_key, destination_relative_path).
#
# `source_key` is looked up by `resolve_source()`:
#   * installed tool -> `<package>/share/<key>` and `<package>/data/<key>`
#     (packaged via pyproject force-include)
#   * repo checkout  -> `<repo>/<key>`
#
# The `scripts/` fallback exists only for a repo checkout, so a user who cloned
# the repo is never left without a runnable path; the contract still presents
# `elang <cmd>` as the primary interface.
PAYLOAD = [
    ("SKILL.md", "SKILL.md"),                              # the contract itself
    ("README.md", "README.md"),                            # user-facing overview
    ("SETUP.md", "SETUP.md"),                              # agent install guide
    ("references/answers.json", "references/answers.json"),  # answer bank
    ("references/parse_answers.py", "references/parse_answers.py"),
    (".env.example", ".env.example"),                      # credential template
    ("CLAUDE.md", "CLAUDE.md"),                            # agent-facing guidance
    ("MIGRATION_CHECKPOINT.md", "MIGRATION_CHECKPOINT.md"),
    ("MCP_DESIGN.md", "MCP_DESIGN.md"),
    ("DISTRIBUTION.md", "DISTRIBUTION.md"),
    ("scripts", "scripts"),                                # repo-only fallback
]

# Files packaged under `elang/share/` (see pyproject force-include).
_SHARE_FILES = {
    "SKILL.md", "README.md", "SETUP.md", ".env.example", "CLAUDE.md",
    "MIGRATION_CHECKPOINT.md", "MCP_DESIGN.md", "DISTRIBUTION.md",
    "references/parse_answers.py",
}

HOME = Path(os.path.expanduser("~"))


def _package_dirs():
    """Directories inside the installed package that carry payload data."""
    try:
        from importlib.resources import files as _res_files
        import elang as _pkg
        base = _res_files(_pkg)
        return [base / "share", base / "data"]
    except Exception:
        return []


def resolve_source(key):
    """Return a filesystem path for `key`, or None.

    Installed layout wins when present, because `elang install-skill` must work
    with no repo checkout. `Path(__file__).parent.parent` is NOT a valid repo root
    inside site-packages (it resolves to `Lib/`), which silently made every file
    look absent.
    """
    # 1. installed package data
    for base in _package_dirs():
        name = Path(key).name
        for cand in (base / key, base / name):
            try:
                if cand.is_file() or cand.is_dir():
                    return Path(str(cand))
            except Exception:
                continue
    # 2. repo layout
    cand = REPO / key
    if cand.exists():
        return cand
    return None


def find_project_root(start=None):
    """Nearest ancestor containing a project marker, or `start` itself.

    Mirrors how the hosts themselves locate a project root (DSH uses the nearest
    ancestor containing `.git`). Walking up matters because an agent may be
    started in a subdirectory of the project.
    """
    cur = Path(start or Path.cwd()).resolve()
    for _ in range(30):
        for marker in (".git", "pyproject.toml", "SKILL.md", ".dsh", ".agents"):
            if (cur / marker).exists():
                return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return Path(start or Path.cwd()).resolve()


def _dsh_home():
    return Path(os.environ.get("DSH_HOME") or (HOME / ".dsh"))


def _agents_home():
    return Path(os.environ.get("DSH_AGENTS_HOME") or (HOME / ".agents"))


def user_roots(project_root=None):
    """User-level (global) skill roots per agent, in each host's scan-rank order.

    Ranks come from DSH's `skill-filesystem` provider; Claude Code's convention is
    `~/.claude/skills`. Note DSH and Codex SHARE `~/.agents/skills`, so installing
    for both writes one directory, not two.
    """
    return {
        "dsh": [_dsh_home() / "skills", _agents_home() / "skills"],
        "codex": [_agents_home() / "skills"],
        "claude": [HOME / ".claude" / "skills"],
    }


def project_roots(project_root):
    """Project-level skill roots per agent, in scan-rank order.

    `project_root` is the nearest ancestor holding a project marker. Installing
    here keeps the skill with the project and takes precedence over the global
    copy in every host (DSH ranks project roots 100/200, global ones 400/500).
    """
    p = Path(project_root)
    return {
        "dsh": [p / ".dsh" / "skills", p / ".agents" / "skills"],
        "codex": [p / ".agents" / "skills"],
        "claude": [p / ".claude" / "skills"],
    }


ALL_AGENTS = ("dsh", "codex", "claude")


def detect_agents():
    """Agents whose configuration directory exists (cheap heuristic)."""
    found = []
    if _dsh_home().exists() or _agents_home().exists():
        found.append("dsh")
    if _agents_home().exists():
        found.append("codex")
    if (HOME / ".claude").exists():
        found.append("claude")
    return found


def make_link(target: Path, link: Path):
    """Create a directory link. Returns a description of what was used."""
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.exists() or link.is_symlink() or _is_junction(link):
        remove_path(link)
    if os.name == "nt":
        # A junction needs no elevation and behaves like a directory symlink.
        r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                           capture_output=True, text=True)
        if r.returncode == 0:
            return "junction"
        os.symlink(target, link, target_is_directory=True)
        return "symlink"
    os.symlink(target, link, target_is_directory=True)
    return "symlink"


def _is_junction(p: Path) -> bool:
    """True for a Windows directory junction (a reparse point, not a symlink)."""
    try:
        return p.is_junction()          # Python 3.12+
    except AttributeError:
        try:
            return bool(p.lstat().st_file_attributes & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT
        except Exception:
            return False
    except Exception:
        return False


def remove_path(p: Path):
    """Remove a link, junction, or directory tree.

    `rmdir` must be used ONLY for junctions: it removes the reparse point without
    touching the target, which is exactly right for a junction. Using it for an
    ordinary directory fails (rmdir only deletes EMPTY directories) and, because
    the result was never checked, the failure was silent — uninstall reported
    success while the files stayed on disk.
    """
    try:
        if p.is_symlink() or _is_junction(p):
            if os.name == "nt" and _is_junction(p):
                r = subprocess.run(["cmd", "/c", "rmdir", str(p)],
                                   capture_output=True, text=True)
                if r.returncode != 0:
                    raise RuntimeError(
                        (r.stderr or r.stdout or "rmdir failed").strip())
            else:
                p.unlink()
        elif p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()
    except Exception as e:
        print(f"    could not remove {p}: {type(e).__name__}: {e}")
        raise


def install_copy(dest: Path):
    """Copy the payload, creating intermediate directories.

    PAYLOAD contains nested destinations (`references/answers.json`), so each
    file's PARENT must exist first — `shutil.copy2` creates the file, not its
    directory. Missing that made the first nested entry raise FileNotFoundError
    and abort the rest, silently leaving only the first item in place.
    """
    dest.mkdir(parents=True, exist_ok=True)
    missing = []
    for key, rel in PAYLOAD:
        src = resolve_source(key)
        if src is None:
            missing.append(rel)
            continue
        dst = dest / rel
        try:
            if src.is_dir():
                if dst.exists():
                    shutil.rmtree(dst, ignore_errors=True)
                shutil.copytree(src, dst)
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        except Exception as e:
            print(f"    could not copy {rel}: {type(e).__name__}: {e}")
            missing.append(rel)
    return missing


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  install_skill.py --agent claude                 # global, Claude Code\n"
            "  install_skill.py --agent dsh,codex --scope project\n"
            "  install_skill.py --scope project                # every agent, this project\n"
            "  install_skill.py --check                        # report only\n"
        ))
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--link", action="store_true",
                      help="link to this repo instead of copying (needs a checkout)")
    mode.add_argument("--copy", action="store_true",
                      help="copy the payload (default)")
    mode.add_argument("--uninstall", action="store_true")
    ap.add_argument("--check", action="store_true", help="report only")

    ap.add_argument("--agent", "--hosts", dest="agent", default="",
                    help="comma list of agents: dsh, codex, claude "
                         "(default: every detected one, else all three)")
    ap.add_argument("--scope", choices=("global", "project", "all"), default="global",
                    help="global = user-level roots; project = the current "
                         "project's roots; all = both (default: global)")
    ap.add_argument("--project-root", default="",
                    help="project root for --scope project (default: nearest "
                         "ancestor with .git / pyproject.toml / SKILL.md)")
    ap.add_argument("--dir", default="",
                    help="install into this single skills root instead of "
                         "resolving agents/scopes")
    args = ap.parse_args()

    if not (args.link or args.copy or args.uninstall or args.check):
        args.copy = True        # copying is the sane default for distribution

    # ---- work out the target roots -------------------------------------------
    labelled = []               # [(agent_label, root)]
    if args.dir:
        labelled.append(("custom", Path(args.dir).expanduser().resolve()))
    else:
        wanted = [a.strip().lower() for a in args.agent.split(",") if a.strip()]
        if not wanted:
            wanted = detect_agents() or list(ALL_AGENTS)
        unknown = [a for a in wanted if a not in ALL_AGENTS]
        if unknown:
            print(f"ERROR: unknown agent(s): {', '.join(unknown)}")
            print(f"       known: {', '.join(ALL_AGENTS)}")
            return 1

        project_root = (Path(args.project_root).expanduser().resolve()
                        if args.project_root else find_project_root())

        scopes = (["global", "project"] if args.scope == "all" else [args.scope])
        # Collect which agents each root serves, then label once. DSH and Codex
        # genuinely share `~/.agents/skills`, so one directory serves both and
        # should read as `dsh+codex` rather than appearing twice.
        collected = {}          # (scope, root_key) -> {"root": Path, "agents": set}
        for scope in scopes:
            table = (user_roots() if scope == "global"
                     else project_roots(project_root))
            for agent in wanted:
                for root in table.get(agent, []):
                    slot = collected.setdefault(
                        (scope, str(root).lower()), {"root": root, "agents": set()})
                    slot["agents"].add(agent)
        for (scope, _key), slot in collected.items():
            label = "+".join(sorted(slot["agents"])) + f"/{scope}"
            labelled.append((label, slot["root"]))

    # ---- report the plan -----------------------------------------------------
    print(f"repo        : {REPO}")
    print(f"skill name  : {SKILL_NAME}")
    print(f"agents      : {args.agent or ', '.join(detect_agents() or ALL_AGENTS)}")
    print(f"scope       : {args.scope}" +
          (f"  (project root: {find_project_root()})"
           if args.scope in ("project", "all") and not args.dir else ""))
    print(f"mode        : {'uninstall' if args.uninstall else 'link' if args.link else 'copy'}")
    print(f"targets     : {len(labelled)}")
    print()

    if args.check:
        rc = 0
        for label, root in labelled:
            dest = root / SKILL_NAME
            if dest.is_symlink():
                state = "linked"
            elif dest.exists():
                state = "present"
            else:
                state = "absent"
            print(f"  [{label:<16}] {dest}  -> {state}")
        return rc

    rc = 0
    for label, root in labelled:
        dest = root / SKILL_NAME
        tag = f"[{label:<16}]"
        if args.uninstall:
            if dest.exists() or dest.is_symlink() or _is_junction(dest):
                try:
                    remove_path(dest)
                except Exception:
                    rc = 1
                    print(f"  {tag} FAILED to remove {dest}")
                    continue
                print(f"  {tag} removed {dest}")
            else:
                print(f"  {tag} nothing at {dest}")
            continue
        try:
            root.mkdir(parents=True, exist_ok=True)
            if args.link:
                # Link mode points a host at this checkout, so it only makes sense
                # when a repo is actually present (an installed tool has none).
                if not (REPO / "SKILL.md").exists():
                    print(f"  {tag} --link needs a repo checkout (no SKILL.md at "
                          f"{REPO}); use --copy instead")
                    rc = 1
                    continue
                how = make_link(REPO, dest)
                print(f"  {tag} {dest}  ({how})")
            else:
                missing = install_copy(dest)
                note = (f"   missing: {', '.join(missing)}" if missing else "")
                print(f"  {tag} {dest}  (copied){note}")
                if missing:
                    rc = 1
        except Exception as e:
            rc = 1
            print(f"  {tag} FAILED {dest}: {type(e).__name__}: {e}")

    print()
    print("Each host discovers `<root>/<name>/SKILL.md` one level deep.")
    if args.scope in ("global", "all"):
        print("Global roots are per-user; project roots live in the repo and can "
              "be committed so a teammate gets the skill with the checkout.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
