#!/usr/bin/env python3
"""Answering interface for elang_reader.py — the "backend processor" side.

The solver (`elang_reader.py`) drives the browser and, for each article, writes
the passage + questions to `<ipc>/elang_current.json` and waits. This tool is the
other half of that protocol: read the pending article, then hand back answers.

It is a first-class part of the project (not scratch tooling) because the helper
exists for both an AI agent and a human, and because every run needs it.

Usage
-----
  python scripts/review.py brief
      One line: status, article number/name, question count, whether your
      answer is already waiting. Use this to poll while the solver runs.

  python scripts/review.py show
      The full passage and every question with its option labels.

  python scripts/review.py answer 0=A 1=C 2=B [...]
      Answers by option LETTER (0-based question index). Letters may be
      A-E, or a WORD for fill-in-the-blank types whose options are words.
      For a multi-blank fill question, give the value once per blank, comma
      separated, e.g. 3=A-poncho,B-junction,C-glut

  python scripts/review.py raw '[[0,1],[1,2],[2,"A-word"]]'
      Answers as raw JSON: [question_index, option_index_or_string].

  python scripts/review.py skip
      Tell the solver to submit this article as-is.

  python scripts/review.py clear
      Remove any stale answer file (the solver also does this per article).

IPC locations
-------------
Resolved exactly like `elang_reader.py`: `$ELANG_TMP_DIR` when set, otherwise
`C:/tmp` on Windows and `/tmp` elsewhere.
"""
import json
import os
import platform
import sys
from pathlib import Path

if os.getenv("ELANG_TMP_DIR", "").strip():
    IPC = Path(os.getenv("ELANG_TMP_DIR").strip())
elif platform.system() == "Windows":
    IPC = Path("C:/tmp")
else:
    IPC = Path("/tmp")

CURRENT = IPC / "elang_current.json"
SIGNAL = IPC / "elang_signal.json"
LETTERS = "ABCDEFGH"


def _load_current():
    try:
        with open(CURRENT, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"ERROR: cannot read {CURRENT}: {type(e).__name__}: {e}")
        return None


def _write_signal(payload):
    IPC.mkdir(parents=True, exist_ok=True)
    with open(SIGNAL, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    print(f"wrote {SIGNAL}: {json.dumps(payload, ensure_ascii=False)[:200]}")


def cmd_brief():
    d = _load_current()
    if not d:
        print(f"no pending article ({CURRENT} not present)")
        return 0
    qs = d.get("questions") or []
    print(f"status={d.get('status')} "
          f"#{d.get('article_number')} {d.get('article_name')!r} "
          f"questions={len(qs)} passage={len(d.get('passage') or '')}ch "
          f"answer_waiting={SIGNAL.exists()}")
    if d.get("status") != "waiting_for_ai":
        print("(the solver is not waiting for answers right now)")
    return 0


def cmd_show():
    d = _load_current()
    if not d:
        print(f"no pending article ({CURRENT} not present)")
        return 1
    print(f"=== #{d.get('article_number')} {d.get('article_name')} ===")
    print(f"status: {d.get('status')}")
    print("\n--- PASSAGE ---")
    print(d.get("passage") or "")
    print(f"\n--- QUESTIONS ({len(d.get('questions') or [])}) ---")
    for q in d.get("questions") or []:
        print(f"\n[q{q['index']}] kind={q.get('kind')} type_id={q.get('type_id')} "
              f"multi={q.get('multi')} blanks={q.get('blanks')}")
        print(f"   {q.get('question')}")
        for o in q.get("options") or []:
            print(f"     {o.get('label')}. {o.get('text')}")
        for i, sel in enumerate(q.get("select_options") or []):
            vals = ", ".join(str(o.get("value")) for o in (sel or [])[:12])
            print(f"     select[{i}]: {vals}")
        if q.get("kind") == "fill" and q.get("blanks"):
            print(f"     -> needs {q['blanks']} value(s), one per blank")
    return 0


def cmd_answer(pairs):
    """pairs: ['0=A', '1=C', '3=A-poncho,B-junction'] -> answers list."""
    answers = []
    for pair in pairs:
        if "=" not in pair:
            print(f"ERROR: expected qIdx=VALUE, got {pair!r}")
            return 1
        qi, val = pair.split("=", 1)
        qi = qi.strip()
        if not qi.isdigit():
            print(f"ERROR: question index must be a number, got {qi!r}")
            return 1
        val = val.strip()
        if "," in val:
            # multi-blank fill: one value per blank
            answers.append([int(qi), [v.strip() for v in val.split(",")]])
        elif len(val) == 1 and val.upper() in LETTERS:
            answers.append([int(qi), LETTERS.index(val.upper())])
        else:
            # a word (fill-in-the-blank option value)
            answers.append([int(qi), val])
    _write_signal({"status": "answers_ready", "answers": answers})
    return 0


def cmd_raw(blob):
    try:
        answers = json.loads(blob)
    except Exception as e:
        print(f"ERROR: bad JSON: {type(e).__name__}: {e}")
        return 1
    if not isinstance(answers, list):
        print("ERROR: expected a JSON list of [qIdx, value] pairs")
        return 1
    _write_signal({"status": "answers_ready", "answers": answers})
    return 0


def cmd_skip():
    _write_signal({"status": "skip"})
    return 0


def cmd_clear():
    removed = False
    if SIGNAL.exists():
        SIGNAL.unlink()
        removed = True
    print("cleared signal" if removed else "no signal to clear")
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 0
    cmd = sys.argv[1]
    if cmd == "brief":
        return cmd_brief()
    if cmd == "show":
        return cmd_show()
    if cmd == "answer":
        if len(sys.argv) < 3:
            print("ERROR: nothing to answer, e.g. answer 0=A 1=C")
            return 1
        return cmd_answer(sys.argv[2:])
    if cmd == "raw":
        if len(sys.argv) < 3:
            print("ERROR: raw needs a JSON argument")
            return 1
        return cmd_raw(sys.argv[2])
    if cmd == "skip":
        return cmd_skip()
    if cmd == "clear":
        return cmd_clear()
    print(f"unknown command: {cmd}\n")
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
