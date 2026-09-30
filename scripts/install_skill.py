#!/usr/bin/env python3
"""Install this repo as a skill for DSH, Codex, and Claude Code.

Why one script instead of three
------------------------------
All three hosts use the SAME skill contract — a directory bundle containing
`SKILL.md` with YAML frontmatter (`name`, `description`) — and they differ only
in which roots they scan. Verified against the DSH runtime:

| Host        | Root                                                |
|-------------|-----------------------------------------------------|
| DSH (user)  | `~/.dsh/skills`          (rank 400, skips `.system`)|
| DSH (user)  | `~/.agents/skills`       (rank 500)                 |
| DSH (proj)  | `<projectRoot>/.dsh/skills`      (rank 100)         |
| DSH (proj)  | `<projectRoot>/.agents/skills`   (rank 200)         |
| Codex       | `~/.agents/skills`                                  |
| Claude Code | `~/.claude/skills`                                  |

DSH scans roots **one level deep** and expects `<root>/<name>/SKILL.md`, so the
skill must be installed as a directory named after the skill — not as a bare
`SKILL.md` at the root.

Two install strategies
----------------------
`--link`  create a directory link back to this repo. Edits take effect at once
          and nothing is duplicated; requires symlink support (POSIX, or Windows
          with Developer Mode / admin; a Windows junction is used automatically
          when available).
`--copy`  copy `SKILL.md`, `scripts/`, `references/`, `assets/`. Works
          everywhere, but must be re-run after changing the source.

Usage
-----
    python scripts/install_skill.py --link            # link into every host found
    python scripts/install_skill.py --copy            # copy instead
    python scripts/install_skill.py --hosts dsh,codex
    python scripts/install_skill.py --check           # report only
    python scripts/install_skill.py --uninstall
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

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
    "SKILL.md", ".env.example", "CLAUDE.md", "MIGRATION_CHECKPOINT.md",
    "MCP_DESIGN.md", "DISTRIBUTION.md", "references/parse_answers.py",
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


def user_roots():
    """User-level roots per host, in scan-rank order."""
    dsh_home = Path(os.environ.get("DSH_HOME") or (HOME / ".dsh"))
    agents_home = Path(os.environ.get("DSH_AGENTS_HOME") or (HOME / ".agents"))
    return {
        "dsh": [dsh_home / "skills", agents_home / "skills"],
        "codex": [agents_home / "skills"],
        "claude": [HOME / ".claude" / "skills"],
    }


def which_hosts():
    """Hosts whose home directory exists (cheap heuristic, not authoritative)."""
    found = []
    if (HOME / ".dsh").exists() or (HOME / ".agents").exists():
        found.append("dsh")
    if (HOME / ".agents").exists():
        found.append("codex")
    if (HOME / ".claude").exists():
        found.append("claude")
    return found


def make_link(target: Path, link: Path):
    """Create a directory link. Returns a description of what was used."""
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.exists() or link.is_symlink():
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


def remove_path(p: Path):
    """Remove a link, junction, or directory without following it."""
    try:
        if p.is_symlink():
            p.unlink()
        elif os.name == "nt" and p.is_dir():
            # rmdir removes a junction itself, not its target
            subprocess.run(["cmd", "/c", "rmdir", str(p)],
                           capture_output=True, text=True)
        elif p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
    except Exception as e:
        print(f"    could not remove {p}: {type(e).__name__}: {e}")


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


def host_of(root: Path):
    s = str(root).replace("\\", "/")
    if "/.dsh/" in s:
        return "dsh"
    if "/.agents/" in s:
        return "dsh+codex"
    if "/.claude/" in s:
        return "claude"
    return "?"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--link", action="store_true", help="link to this repo")
    mode.add_argument("--copy", action="store_true", help="copy the payload")
    mode.add_argument("--uninstall", action="store_true")
    ap.add_argument("--check", action="store_true", help="report only")
    ap.add_argument("--hosts", default="",
                    help="comma list: dsh,codex,claude (default: all detected)")
    ap.add_argument("--dir", default="",
                    help="install into this single skills root instead")
    args = ap.parse_args()

    if not args.link and not args.copy and not args.uninstall and not args.check:
        args.link = True  # sensible default for development

    roots = []
    if args.dir:
        roots.append(Path(args.dir).expanduser().resolve())
    else:
        wanted = ([h.strip() for h in args.hosts.split(",") if h.strip()]
                  or which_hosts())
        if not wanted:
            wanted = ["dsh", "codex", "claude"]
        seen = set()
        for h in wanted:
            for r in user_roots().get(h, []):
                key = str(r)
                if key not in seen:
                    seen.add(key)
                    roots.append(r)

    print(f"repo        : {REPO}")
    print(f"skill name  : {SKILL_NAME}")
    print(f"hosts       : {args.hosts or ', '.join(which_hosts()) or 'all'}")
    print(f"targets     : {len(roots)}")
    print()

    if args.check:
        for r in roots:
            dest = r / SKILL_NAME
            state = ("linked" if dest.is_symlink()
                     else "present" if dest.exists() else "absent")
            print(f"  [{host_of(r):<10}] {dest}  -> {state}")
        return 0

    rc = 0
    for r in roots:
        dest = r / SKILL_NAME
        if args.uninstall:
            if dest.exists() or dest.is_symlink():
                remove_path(dest)
                print(f"  [{host_of(r):<10}] removed {dest}")
            else:
                print(f"  [{host_of(r):<10}] nothing at {dest}")
            continue
        try:
            r.mkdir(parents=True, exist_ok=True)
            if args.link:
                # link mode only makes sense from a checkout: it points the host at
                # this repo. There is nothing to link to when running installed.
                if not (REPO / "SKILL.md").exists():
                    print(f"  [{host_of(r):<10}] --link needs a repo checkout "
                          f"(no SKILL.md at {REPO}); use --copy instead")
                    rc = 1
                    continue
                how = make_link(REPO, dest)
                print(f"  [{host_of(r):<10}] {dest}  ({how})")
            else:
                missing = install_copy(dest)
                note = f"  ({len(missing)} missing: {', '.join(missing)})" if missing else ""
                print(f"  [{host_of(r):<10}] {dest}  (copied){note}")
                if missing:
                    rc = 1
        except Exception as e:
            rc = 1
            print(f"  [{host_of(r):<10}] FAILED {dest}: {type(e).__name__}: {e}")

    print()
    print("Each host discovers `<root>/<name>/SKILL.md` one level deep.")
    if args.link:
        print("Linked: source edits are live; re-run after adding new files.")
    else:
        print("Copied: re-run this script after changing the source.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
