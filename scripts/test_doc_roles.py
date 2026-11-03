#!/usr/bin/env python3
"""Enforce the two-audience documentation split.

This project has two agent roles and their documents must not be mixed:

  执行 agent (runs the skill to answer questions)
      SKILL.md, SETUP.md, .env.example, README.md   <- shipped with the skill

  开发 agent (works on this project)
      CLAUDE.md, MIGRATION_CHECKPOINT.md, MCP_DESIGN.md, DISTRIBUTION.md,
      SETUP_DESIGN.md, AGENTS.md                    <- repo only, NEVER shipped

The rule that actually matters: an installed skill directory must not receive
development documents. Before this split it received a 2000+ line development
log, design notes and distribution plans.

Run: python scripts/test_doc_roles.py
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

EXEC_DOCS = {"SKILL.md", "SETUP.md", ".env.example", "README.md"}
DEV_DOCS = {
    "CLAUDE.md", "AGENTS.md", "MIGRATION_CHECKPOINT.md", "MCP_DESIGN.md",
    "DISTRIBUTION.md", "SETUP_DESIGN.md",
}
# Forbidden in anything that ships: development-only documents and the deep
# implementation notes that belong in CLAUDE.md.
forbidden_payload = sorted(DEV_DOCS) + ["scripts", "references", "archive"]

results = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    results.append((name, bool(cond)))


print("=== skill payload carries execution docs only ===")
import install_skill  # noqa: E402

payload_srcs = {src for src, _dest in install_skill.PAYLOAD}
check("payload is a subset of the execution docs",
      payload_srcs <= EXEC_DOCS, str(sorted(payload_srcs - EXEC_DOCS)))
check("SKILL.md is in the payload", "SKILL.md" in payload_srcs)
check("no development doc is copied",
      not (payload_srcs & DEV_DOCS), str(sorted(payload_srcs & DEV_DOCS)))
check("no implementation tree is copied",
      not any(s in ("scripts", "references", "archive") for s in payload_srcs))
check("no payload entry can be 'missing' from a wheel install",
      all(install_skill.resolve_source(src) is not None for src in payload_srcs),
      str([s for s in payload_srcs if install_skill.resolve_source(s) is None]))

print("\n=== wheel ships the same set (elang/share/) ===")
pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
share = [line.split("=")[0].strip().strip('"')
         for line in pyproject.splitlines()
         if '= "elang/share/' in line]
check("share/ has only execution docs",
      set(share) <= EXEC_DOCS, str(sorted(set(share) - EXEC_DOCS)))
check("share/ matches the payload",
      set(share) == payload_srcs, f"share={sorted(share)} payload={sorted(payload_srcs)}")

print("\n=== role-specific docs declare their audience ===")
# A 读者 banner belongs on the documents whose audience could be confused: the two
# skill-facing docs and the development-only ones. README is a general entry point
# and .env.example is a template, so neither carries one.
BANNERED = ({"SKILL.md", "SETUP.md"} | DEV_DOCS)
for name in sorted(BANNERED):
    p = REPO / name
    if not p.exists():
        check(f"{name} exists", False)
        continue
    head = "\n".join(p.read_text(encoding="utf-8").splitlines()[:12])
    check(f"{name} declares its audience", "读者" in head)

print("\n=== banners point at the right role ===")
for name in sorted({"SKILL.md", "SETUP.md"}):
    head = "\n".join((REPO / name).read_text(encoding="utf-8").splitlines()[:12])
    check(f"{name} says 执行 agent", "执行 agent" in head,
          "found: " + next((l for l in head.splitlines() if "读者" in l), "?"))
for name in sorted(DEV_DOCS):
    head = "\n".join((REPO / name).read_text(encoding="utf-8").splitlines()[:12])
    check(f"{name} says 开发 agent", "开发 agent" in head,
          "found: " + next((l for l in head.splitlines() if "读者" in l), "?"))

print("\n=== README stays a general entry point ===")
readme = (REPO / "README.md").read_text(encoding="utf-8")
check("README has no 读者 banner", "**读者" not in readme)
check("README has no role-split section", "两种 agent" not in readme)
check("README does not assign docs to agent roles", "开发 agent" not in readme)

print("\n=== the execution contract carries no dev-only material ===")
skill = (REPO / "SKILL.md").read_text(encoding="utf-8")
for name in sorted(DEV_DOCS):
    # Mentioning a dev doc is only allowed as an absolute repo URL (SKILL.md ships
    # alone, so a relative link would dangle).
    rel = f"]({name})"
    check(f"SKILL.md has no relative link to {name}", rel not in skill)
check("SKILL.md does not tell the run agent to read the checkpoint log",
      "MIGRATION_CHECKPOINT" not in skill)
for term in ("PcReadPraxis", "PcReadLearn", "PcReadIndex", "__elangPraxisVm"):
    check(f"SKILL.md omits DOM/Vue internals ({term})", term not in skill)

print("\n" + "=" * 58)
passed = sum(1 for _, ok in results if ok)
print(f"{passed}/{len(results)} checks passed")
for name, ok in results:
    if not ok:
        print(f"  FAILED: {name}")
sys.exit(0 if passed == len(results) else 1)
