#!/usr/bin/env python3
"""Check that the documentation still describes the code as it is.

Documentation drifts silently. This test reads the root documents and compares
them against the code: which subcommands exist, which flags exist, which MCP tools
are registered, which files the tree claims, and whether the numbers the docs state
match each other.

It does not try to judge prose. It checks the mechanical claims that users copy and
run, because those are the ones that break.

Run: python scripts/test_docs_match_code.py
"""
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOCS = ["README.md", "SKILL.md", "SETUP.md", "CLAUDE.md", "SECURITY.md"]

# Flags that belong to other tools, quoted in the docs on purpose.
EXTERNAL_FLAGS = {
    "system-site-packages",   # pip / venv
    "no-verify",              # git commit
    "all", "hard",            # git filter-repo
    "force-with-lease",       # git push
    "with",                   # uv tool install --with (optional extras, e.g. ddddocr)
    "upgrade",                # pip install --upgrade pip
    "shared",                 # elang install-browser (present but checked below)
}

results = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    results.append((name, bool(cond)))


def read(name):
    return (REPO / name).read_text(encoding="utf-8")


def cli_verbs():
    """Subcommands the dispatcher accepts."""
    src = read("src/elang/cli.py")
    verbs = set(re.findall(r'^\s+"([a-z-]+)": \(', src, re.M))
    m = re.search(r"IPC_VERBS = \(([^)]*)\)", src)
    if m:
        verbs |= set(re.findall(r'"([a-z-]+)"', m.group(1)))
    verbs |= {"run", "mcp", "list", "help"}
    return verbs


def code_flags():
    """Every long option the code mentions as a string literal."""
    flags = set()
    for path in list(REPO.glob("scripts/*.py")) + list(REPO.glob("src/elang/*.py")):
        for m in re.finditer(r'"(--[a-z][a-z-]*)"', path.read_text(encoding="utf-8")):
            flags.add(m.group(1)[2:])
    return flags


def mcp_tools():
    src = read("scripts/elang_mcp.py")
    return set(re.findall(r"def (elang_[a-z_]+)\(", src))


print("=== documented subcommands exist ===")
verbs = cli_verbs()
mentioned = {}
for doc in DOCS:
    for i, line in enumerate(read(doc).splitlines(), 1):
        for m in re.finditer(r"\belang\s+([a-z][a-z-]*)", line):
            mentioned.setdefault(m.group(1), f"{doc}:{i}")
unknown = {v: where for v, where in mentioned.items() if v not in verbs}
check(f"all {len(mentioned)} documented subcommands exist", not unknown, str(unknown))

print("\n=== documented flags exist ===")
known = code_flags() | EXTERNAL_FLAGS
doc_flags = {}
for doc in DOCS:
    for i, line in enumerate(read(doc).splitlines(), 1):
        for m in re.finditer(r"(?<![\w-])--([a-z][a-z-]{2,})", line):
            doc_flags.setdefault(m.group(1), f"{doc}:{i}")
missing = {f: w for f, w in doc_flags.items() if f not in known}
check(f"all {len(doc_flags)} documented flags exist", not missing, str(missing))

print("\n=== MCP tools named in the docs are real ===")
tools = mcp_tools()
check("the server defines 10 tools", len(tools) == 10, f"found {len(tools)}")
for doc in ("README.md", "SKILL.md"):
    named = set(re.findall(r"\b(elang_(?:start|status|stop|list_subjects|"
                           r"list_lessons|open_next|get_captcha|solve_captcha|"
                           r"submit_answers|skip_article))\b", read(doc)))
    check(f"{doc}: no invented tool name", named <= tools, str(named - tools))
    check(f"{doc}: lists every tool", named == tools, str(tools - named))

print("\n=== relative links resolve ===")
root = REPO
bad = []
for doc in DOCS:
    for m in re.finditer(r"\]\(([^)#:]+\.(?:md|py|json|toml|example))\)", read(doc)):
        target = m.group(1)
        if target.startswith("http"):
            continue
        if not (root / target).exists():
            bad.append(f"{doc} -> {target}")
check("every relative link points at an existing file", not bad, str(bad))

print("\n=== README directory tree matches the repository ===")
readme = read("README.md")
m = re.search(r"## 目录结构\n\n```\n(.*?)```", readme, re.S)
check("README has a directory tree", m is not None)
if m:
    # The tree is indented with box characters, four columns per level, so a
    # nested entry is relative to the directory opened at the level above it.
    missing_paths = []
    dirs = {}
    for line in m.group(1).splitlines():
        mm = re.match(r"^([│├└─\s]*?)([^\s#]+)\s*(?:#.*)?$", line)
        if not mm:
            continue
        prefix, name = mm.group(1), mm.group(2)
        depth = len(prefix) // 4
        if depth == 0:                      # the repo root line itself
            dirs[0] = Path("")
            continue
        parent = dirs.get(depth - 1, Path(""))
        rel = parent / name.rstrip("/")
        if name.endswith("/"):
            dirs[depth] = rel
        if not (root / rel).exists():
            missing_paths.append(str(rel))
    check("every path in the tree exists", not missing_paths, str(missing_paths))

print("\n=== the docs agree on the corpus size ===")
# The site gives 11 subjects holding 220 articles. Both documents commit to those
# numbers, so a change on one side without the other fails here.
for doc in ("README.md", "SKILL.md"):
    text = read(doc)
    check(f"{doc} states 11 subjects", re.search(r"11\s*个", text) is not None)
    check(f"{doc} states 220 articles", "220" in text)

print("\n=== the supported platform is stated, not promised broadly ===")
# The tool is Windows-only on purpose (AGENTS.md rule 5). README used to promise
# "Windows / Linux / macOS" while every measurement had been made on Windows, so
# pin the honest statement: a Windows scope plus no cross-platform advertising.
def _claims_cross_platform(text):
    """True if a doc advertises cross-platform support (the rule forbidding it is fine)."""
    return any("跨平台" in line and "不要做跨平台兼容" not in line
               for line in text.splitlines())


# Accept the equivalent phrasings: the rule is that README states the scope, not
# that it uses one exact wording.
_check_win = [m for m in ("只支持 Windows", "仅支持 Windows") if m in read("README.md")]
check("README states Windows-only support", bool(_check_win),
      f"found: {_check_win or 'neither 只支持 Windows nor 仅支持 Windows'}")
check("no document promises cross-platform support",
      not any(_claims_cross_platform(read(d)) for d in DOCS))
check("the development guides forbid porting work",
      "不要做跨平台兼容" in read("AGENTS.md"))
toml = read("pyproject.toml")
check("package metadata is Windows-only",
      "Operating System :: Microsoft :: Windows" in toml
      and "OS Independent" not in toml)

print("\n=== archive/ stays out of the repository ===")
tracked = subprocess.run(["git", "ls-files", "archive"], cwd=str(REPO),
                         capture_output=True, text=True).stdout.strip()
check("archive is not tracked", not tracked, tracked[:60])
# A bare "archive" does not exist in a fresh clone, and git check-ignore cannot
# classify it as a directory, so probe a path inside the ignored directory.
ignored = subprocess.run(["git", "check-ignore", "archive/README.md"],
                         cwd=str(REPO), capture_output=True, text=True)
check("archive is gitignored", ignored.returncode == 0)
check("no current document links into archive",
      "](archive/" not in read("README.md"))

print("\n=== the two development guides are the same file ===")
a, b = REPO / "AGENTS.md", REPO / "CLAUDE.md"
check("AGENTS.md exists", a.exists())
if a.exists() and b.exists():
    check("AGENTS.md and CLAUDE.md are identical",
          a.read_text(encoding="utf-8") == b.read_text(encoding="utf-8"))

print("\n" + "=" * 58)
passed = sum(1 for _, ok in results if ok)
print(f"{passed}/{len(results)} checks passed")
for name, ok in results:
    if not ok:
        print(f"  FAILED: {name}")
sys.exit(0 if passed == len(results) else 1)
