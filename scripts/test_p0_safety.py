#!/usr/bin/env python3
"""Unit checks for the safety-critical paths added in the P0 hardening pass.

No browser and no network. Covers:
  * `doctor`'s JSON credential redaction (no secret may reach a transcript)
  * atomic JSON writes and tolerant checkpoint loading
  * the "did the answers actually land" predicate
  * signal/answer identity matching (a late answer must not hit the next article)
  * `setup.py`'s exit code when a step fails

Run: python scripts/test_p0_safety.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

# elang_reader resolves its IPC paths at import time, so redirect it first.
_SCRATCH = REPO / "temp"
_SCRATCH.mkdir(parents=True, exist_ok=True)
_IPC = Path(tempfile.mkdtemp(prefix="elang-safety-", dir=str(_SCRATCH)))
os.environ["ELANG_TMP_DIR"] = str(_IPC)

import doctor          # noqa: E402
import elang_reader as er  # noqa: E402

results = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    results.append((name, bool(cond)))


try:
    print("=== doctor: JSON credential redaction ===")
    fake = {
        "username": "test-user",
        "password": "hunter2-secret",
        "env_file": "C:/work/.env",
        "env_file_exists": True,
        "source": "workspace",
        "username_from": "file:CAS_USERNAME",
        "password_from": "file:CAS_PASSWORD",
        "ok": True,
    }
    red = doctor._redact_credentials(fake)
    blob = json.dumps(red, ensure_ascii=False)
    check("password value is not in the redacted report", "hunter2-secret" not in blob)
    check("username value is not in the redacted report", "test-user" not in blob)
    check("redacted report keeps the set flags",
          red.get("username_set") is True and red.get("password_set") is True)
    check("redacted report keeps ok and the source",
          red.get("ok") is True and red.get("source") == "workspace")

    print("\n=== atomic write / tolerant checkpoint ===")
    target = _IPC / "atomic.json"
    er._atomic_write_json(target, {"a": [1, 2], "b": "\u4e2d\u6587"})
    check("file written and parses",
          json.loads(target.read_text(encoding="utf-8"))["a"] == [1, 2])
    check("no temp file left behind", not (target.parent / "atomic.json.tmp").exists())

    cp = Path(er.CHECKPOINT_FILE)
    check("missing checkpoint -> empty dict", er._load_checkpoint() == {})
    cp.write_text('{"total_submitted": 5, "completed_categories": [26]}',
                  encoding="utf-8")
    check("valid checkpoint restored", er._load_checkpoint().get("total_submitted") == 5)
    cp.write_text("{ this is not json", encoding="utf-8")
    check("corrupt checkpoint -> empty dict, no raise", er._load_checkpoint() == {})
    cp.write_text('["not", "a", "dict"]', encoding="utf-8")
    check("non-dict checkpoint -> empty dict", er._load_checkpoint() == {})

    print("\n=== answers actually applied ===")
    questions = [{"index": 0}, {"index": 1}, {"index": 2}]
    check("all questions answered", er._answers_applied(
        {"choice": 2, "fill": 1, "notes": []}, questions))
    check("missing one answer rejected", not er._answers_applied(
        {"choice": 1, "fill": 1, "notes": []}, questions))
    check("explicit error rejected", not er._answers_applied(
        {"error": "PcReadPraxis not found"}, questions))
    check("'no job' note rejected", not er._answers_applied(
        {"choice": 3, "fill": 0, "notes": ["q1: no job"]}, questions))

    print("\n=== signal identity ===")
    check("no expected id accepts anything", er._signal_matches(
        {"article_number": 3}, None))
    check("matching article accepted", er._signal_matches(
        {"article_number": 3}, 3))
    check("different article rejected", not er._signal_matches(
        {"article_number": 3}, 4))
    check("legacy signal without an id accepted", er._signal_matches({}, 4))

    print("\n=== setup.py exit code ===")
    if os.name == "nt":
        env = os.environ.copy()
        env["PATH"] = os.environ.get("SystemRoot", r"C:\Windows") + r"\System32"
        probe = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "setup.py"),
             "--check", "--no-skill"],
            cwd=str(_IPC), env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120)
        check("a failing step makes setup exit non-zero", probe.returncode == 1,
              f"rc={probe.returncode}")
    else:
        print("  [SKIP] Windows-only check")
finally:
    shutil.rmtree(_IPC, ignore_errors=True)

print("\n" + "=" * 58)
passed = sum(1 for _, ok in results if ok)
print(f"{passed}/{len(results)} checks passed")
for name, ok in results:
    if not ok:
        print(f"  FAILED: {name}")
sys.exit(0 if passed == len(results) else 1)
