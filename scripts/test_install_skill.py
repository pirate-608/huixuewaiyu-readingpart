#!/usr/bin/env python3
"""Test `install-skill` state reporting (copy / link / check / uninstall).

Uses throwaway project roots; the real agent skill directories are never touched.
The important regression: `--check` used to exit 0 even when every target was
absent, and a junction (link mode on Windows) was reported as merely "present".

Run: python scripts/test_install_skill.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable
SCRIPT = REPO / "scripts" / "install_skill.py"
SKILL = "huixuewaiyu-readingpart"
results = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    results.append((name, bool(cond)))


def run(root, *args):
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run([PY, str(SCRIPT), "--agent", "dsh", "--scope", "project",
                        "--project-root", str(root)] + list(args),
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


scratch = REPO / "temp"
scratch.mkdir(parents=True, exist_ok=True)
tmp = Path(tempfile.mkdtemp(prefix="elang-skill-", dir=str(scratch)))
copy_root = tmp / "copy-project"
link_root = tmp / "link-project"

try:
    print("=== --check on an empty project must fail ===")
    copy_root.mkdir()
    rc, out = run(copy_root, "--check")
    check("absent targets -> exit 1", rc == 1, f"rc={rc}")
    check("says absent", "absent" in out, out.strip()[-100:])

    print("\n=== --copy installs the payload ===")
    rc, out = run(copy_root, "--copy")
    check("copy -> exit 0", rc == 0, f"rc={rc}\n{out[-300:]}")
    for rel in (Path(".dsh") / "skills" / SKILL,
                Path(".agents") / "skills" / SKILL):
        check(f"payload present under {rel}", (copy_root / rel / "SKILL.md").is_file())

    rc, out = run(copy_root, "--check")
    check("check after copy -> exit 0", rc == 0, f"rc={rc}")
    check("reports present", "present" in out)

    print("\n=== --link then --check recognises a link ===")
    link_root.mkdir()
    rc, out = run(link_root, "--link")
    if rc == 0:
        rc, out = run(link_root, "--check")
        check("check after link -> exit 0", rc == 0, f"rc={rc}")
        check("reports linked (junction counts)", "linked" in out, out.strip()[-120:])
        rc, out = run(link_root, "--uninstall")
        check("uninstall -> exit 0", rc == 0, f"rc={rc}")
        check("uninstall removed the link",
              not (link_root / ".dsh" / "skills" / SKILL).exists())
        check("uninstall did not touch the repo", (REPO / "SKILL.md").is_file())
    else:
        print(f"  [SKIP] link mode unavailable here: {out.strip()[-200:]}")

    print("\n=== --check after uninstall fails again ===")
    rc, out = run(link_root, "--check")
    check("uninstall then check -> exit 1", rc == 1, f"rc={rc}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n" + "=" * 58)
passed = sum(1 for _, ok in results if ok)
print(f"{passed}/{len(results)} checks passed")
for name, ok in results:
    if not ok:
        print(f"  FAILED: {name}")
sys.exit(0 if passed == len(results) else 1)
