#!/usr/bin/env python3
"""Tests for the answering half of `elang run` (`elang pending` / `elang answer`).

No browser and no network: it fabricates the request file the solver writes, then
checks the signal file each command produces.

Run: python scripts/test_answer_ipc.py
"""
import json
import os
import subprocess
import sys
import shutil
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable
SCRIPT = REPO / "scripts" / "answer_ipc.py"

results = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    results.append((name, bool(cond)))


def run(ipc, *args):
    env = os.environ.copy()
    env["ELANG_TMP_DIR"] = str(ipc)
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run([PY, str(SCRIPT)] + list(args), capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=env)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def signal(ipc):
    p = Path(ipc) / "elang_signal.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def write_request(ipc, status="waiting_for_ai", questions=None):
    qs = questions if questions is not None else [
        {"index": 0, "kind": "choice", "type_id": 1, "blanks": 0,
         "question": "Pick one",
         "options": [{"label": "A", "text": "alpha"}, {"label": "B", "text": "beta"}],
         "select_options": []},
        {"index": 1, "kind": "fill", "type_id": 5, "blanks": 2,
         "question": "Two blanks",
         "options": [{"label": "A", "text": "a"}, {"label": "B", "text": "b"}],
         "select_options": [[{"label": "A", "value": "A-alpha"},
                             {"label": "B", "value": "B-beta"}]] * 2},
    ]
    d = {"status": status, "article_number": 7, "article_name": "Test Article",
         "title": "Test Article", "passage": "A passage about a bridge.",
         "questions": qs, "total_submitted": 50}
    (Path(ipc) / "elang_current.json").write_text(
        json.dumps(d, ensure_ascii=False), encoding="utf-8")


ipc = Path(tempfile.mkdtemp(prefix="elangtest-", dir=str(REPO / "temp")))
try:
    (REPO / "temp").mkdir(exist_ok=True)
    print(f"ipc sandbox: {ipc}")

    print("\n=== pending ===")
    rc, out = run(ipc, "pending", "--brief")
    check("no request -> says so", rc == 0 and "no pending article" in out, out.strip())

    write_request(ipc)
    rc, out = run(ipc, "pending", "--brief")
    check("brief reports status", rc == 0 and "status=waiting_for_ai" in out, out.strip())
    check("brief includes question count", "questions=2" in out)

    rc, out = run(ipc, "pending")
    check("full view shows the passage", "A passage about a bridge." in out)
    check("full view shows the word bank", "A-alpha" in out)

    rc, out = run(ipc, "pending", "--json")
    check("--json is parseable", isinstance(json.loads(out), dict))

    print("\n=== answer by letter ===")
    rc, out = run(ipc, "answer", "0=B")
    sig = signal(ipc)
    check("choice letter -> option index", sig == {"status": "answers_ready",
                                                   "answers": [[0, 1]]}, str(sig))

    print("\n=== fill: letters map to option VALUES ===")
    rc, out = run(ipc, "answer", "0=A", "1=A,B")
    sig = signal(ipc)
    check("fill values resolved",
          sig is not None and sig["answers"] == [[0, 0], [1, ["A-alpha", "B-beta"]]],
          str(sig))

    print("\n=== --raw passthrough ===")
    rc, out = run(ipc, "answer", "--raw", '[[1,["B-beta","A-alpha"]],[0,1]]')
    sig = signal(ipc)
    check("raw answers used verbatim",
          sig is not None and sig["answers"] == [[1, ["B-beta", "A-alpha"]], [0, 1]],
          str(sig))

    print("\n=== rejections (exit 1, nothing sent) ===")
    Path(ipc, "elang_signal.json").unlink(missing_ok=True)
    rc, out = run(ipc, "answer", "9=A")
    check("unknown question index rejected", rc == 1 and "not in the pending" in out)
    check("nothing written on rejection", signal(ipc) is None)

    rc, out = run(ipc, "answer", "0=Z")
    check("unknown option letter rejected", rc == 1 and "no option" in out)

    rc, out = run(ipc, "answer", "1=A")
    check("partial fill answers rejected", rc == 1 and "2 blank" in out)

    rc, out = run(ipc, "answer")
    check("empty answer rejected", rc == 1)

    rc, out = run(ipc, "answer", "0")
    check("malformed pair rejected", rc == 1 and "qIdx=VALUE" in out)

    print("\n=== control verbs ===")
    for verb, status in (("skip", "skip"), ("continue", "continue"), ("stop", "stop")):
        run(ipc, verb)
        sig = signal(ipc)
        check(f"{verb} -> status={status}",
              sig == {"status": status}, str(sig))

    print("\n=== checkpoint pause uses the same file ===")
    write_request(ipc, status="checkpoint")
    Path(ipc, "elang_signal.json").unlink(missing_ok=True)
    rc, out = run(ipc, "pending")
    check("checkpoint status explained", "checkpoint" in out and "elang continue" in out)
    check("checkpoint view is not mistaken for an article",
          "PASSAGE" not in out)

    print("\n" + "=" * 58)
    passed = sum(1 for _, ok in results if ok)
    print(f"{passed}/{len(results)} checks passed")
    for name, ok in results:
        if not ok:
            print(f"  FAILED: {name}")
    sys.exit(0 if passed == len(results) else 1)
finally:
    shutil.rmtree(ipc, ignore_errors=True)
