#!/usr/bin/env python3
"""Guard the repository against committed private data.

This repo is public. Two kinds of leakage are checked:

  1. **Secrets** — API keys, private keys, tokens.
  2. **Personal / local-machine data** — a student id, a user's home directory, a
     developer's local checkout path. Even harmless-looking snippets pin the repo
     to one machine and expose who wrote it.

A real incident motivated this: a student id (学号) and `C:\\Users\\<name>` paths were
committed in a development log while the repository was public.

Only TRACKED files are scanned — that is what "committed" means. `.env` is untracked
and gitignored, and is the one place credentials are supposed to live.

Run: python scripts/test_no_secrets.py
"""
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# (name, compiled regex, why)
SECRET_PATTERNS = [
    ("openai-style key", re.compile(r"\bsk-[A-Za-z0-9]{16,}"), "live API key"),
    ("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"), "live token"),
    ("aws access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "live key"),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
     "private key material"),
    ("slack token", re.compile(r"\bxox[abp]-[A-Za-z0-9-]{10,}"), "live token"),
    # Only a LITERAL dotenv-style assignment counts: `CAS_PASSWORD=<value>` with no
    # space before `=`, and a plain ASCII value. That excludes Python
    # (`CAS_PASSWORD = os.getenv(...)`), shell/PowerShell interpolation (`$pass`),
    # f-strings (`{_pwd}`) and the Chinese placeholder (`你的密码`).
    ("cas password value",
     re.compile(r"(?<![A-Za-z0-9_])CAS_PASSWORD=([A-Za-z0-9!@#%^&*()_+\-=.,:;?/]{6,})"),
     "a real password written into a file"),
]

# Personal / machine-specific data.
PRIVACY_PATTERNS = [
    ("windows home dir", re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[A-Za-z0-9_.-]+"),
     "names a local user account"),
    ("posix home dir", re.compile(r"/home/[a-z][a-z0-9_.-]{1,}"), "local user account"),
    ("local checkout", re.compile(r"[A-Za-z]:[\\/]+(projects|dev|src|code)[\\/]"),
     "local checkout path"),
    ("machine python path", re.compile(r"[A-Za-z]:[\\/]+Python3\d{1,2}[\\/]"),
     "machine-specific interpreter"),
    ("cn student id", re.compile(r"\b(?:3[0-9]{9})\b"),
     "looks like a ZJU student id (10 digits starting with 3)"),
]

# Files allowed to match, with the reason. Keep this list tiny and justified.
ALLOW = {
    # Test fixtures deliberately contain fake C:\ paths for the config writer.
    "scripts/test_setup_mcp.py": {"local checkout"},
}

SKIP_SUFFIX = {".pdf", ".png", ".jpg", ".ico", ".whl", ".pyc"}

results = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    results.append((name, bool(cond)))


def tracked_files():
    out = subprocess.run(["git", "ls-files"], cwd=str(REPO), capture_output=True,
                         text=True, encoding="utf-8", errors="replace")
    if out.returncode != 0:
        print("ERROR: git ls-files failed; run from the repository")
        sys.exit(2)
    return [f for f in out.stdout.splitlines() if f.strip()]


def scan(files, patterns, label):
    findings = []
    for rel in files:
        path = REPO / rel
        if path.suffix.lower() in SKIP_SUFFIX or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        allowed = ALLOW.get(rel, set())
        for i, line in enumerate(text.splitlines(), start=1):
            for pname, rx, why in patterns:
                if pname in allowed:
                    continue
                if rx.search(line):
                    findings.append((rel, i, pname, why, line.strip()[:110]))
    print(f"\n=== {label} ===")
    check(f"no {label.lower()} in tracked files", not findings,
          f"{len(findings)} hit(s)")
    for rel, line_no, pname, why, snippet in findings:
        print(f"      {rel}:{line_no}  [{pname}] {why}")
        print(f"        {snippet}")
    return findings


files = tracked_files()
print(f"tracked files: {len(files)}")

f1 = scan(files, SECRET_PATTERNS, "secrets")
f2 = scan(files, PRIVACY_PATTERNS, "personal data")

print("\n=== .env must never be tracked ===")
check(".env is untracked", ".env" not in files)
check(".mcp.json is untracked", ".mcp.json" not in files)
check(".env.example is tracked", ".env.example" in files)
ignored = subprocess.run(["git", "check-ignore", ".env"], cwd=str(REPO),
                         capture_output=True, text=True)
check(".env is gitignored", ignored.returncode == 0)

print("\n=== the .env template carries no real value ===")
tpl = (REPO / ".env.example").read_text(encoding="utf-8")
check("template username is a placeholder",
      "CAS_USERNAME=你的学号" in tpl or "CAS_USERNAME=<" in tpl)
check("template password is a placeholder",
      "CAS_PASSWORD=你的密码" in tpl or "CAS_PASSWORD=<" in tpl)

print("\n" + "=" * 58)
passed = sum(1 for _, ok in results if ok)
print(f"{passed}/{len(results)} checks passed")
if f1 or f2:
    print("\nFix by replacing the value with a placeholder (SECURITY.md records the")
    print("redaction precedent), then re-run. Note that a past commit still")
    print("contains it — redacting HEAD does not rewrite history.")
for name, ok in results:
    if not ok:
        print(f"  FAILED: {name}")
sys.exit(0 if passed == len(results) else 1)
