#!/usr/bin/env python3
"""Exercise ElangSession's validation and echo without a real submission.

Deliberately includes INVALID inputs first: validation must reject them before
any browser call, and must leave the session in `awaiting_answers` so a corrected
submission can follow.

Usage:
    python scripts/test_session.py                 # direct (needs a browser)
    python scripts/test_session.py --validation-only
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from elang_session import ElangSession, State, AnswerError  # noqa: E402


def show(title, obj):
    print(f"\n--- {title} ---")
    print(json.dumps(obj, ensure_ascii=False, indent=2)[:900])


async def main():
    s = ElangSession(dry_run=True)

    # ---------------------------------------------------------- start
    env = await s.start()
    show("start", env)
    if s.state == State.ERROR:
        return 1

    await s.list_subjects()
    print(f"[test] {len(s.subjects)} subjects")

    env = await s.list_lessons(25)
    if s.state == State.ERROR:
        show("list_lessons FAILED", env)
        return 1
    print(f"[test] subject {env['subject']['name']}: "
          f"{len(env['lessons'])} lessons, {env['pending']} pending")

    env = await s.open_next()
    if "article" not in env:
        show("open_next", env)
        return 1
    art = env["article"]
    print(f"[test] article: {art['title']!r}, {len(art['questions'])} questions")
    for q in art["questions"]:
        print(f"        q{q['qIndex']}: {q['kind']} fmt={q['answer_format']} "
              f"blanks={q['blanks']} options={len(q['options'] or [])}")

    fill_q = next((q for q in art["questions"] if q["kind"] == "fill"), None)
    choice_q = next((q for q in art["questions"] if q["kind"] == "choice"), None)

    # ---------------------------------------------------------- validation
    print("\n=== validation (must reject before touching the browser) ===")

    cases = []
    if fill_q:
        cases.append(("fill: too few blanks",
                      [[fill_q["qIndex"], ["A-x"]]]))
        cases.append(("fill: too many blanks",
                      [[fill_q["qIndex"], ["A-x"] * ((fill_q["blanks"] or 0) + 3)]]))
    if choice_q:
        cases.append(("choice: index out of range",
                      [[choice_q["qIndex"], 99]]))
    cases.append(("qIndex out of range",
                  [[999, 0]]))
    cases.append(("duplicate qIndex",
                  [[0, 0], [0, 1]]))

    for label, bad in cases:
        env = await s.submit_answers(bad)
        rejected = env.get("validation_failed")
        print(f"  {label:<28} rejected={rejected}  "
              f"state={env['state']}  msg={str(env.get('error'))[:70]}")

    print(f"\n  session still usable? state={s.state} "
          f"(expected {State.AWAITING_ANSWERS})")

    # ---------------------------------------------------------- valid submit
    print("\n=== valid submission (dry-run) ===")
    answers = []
    for q in art["questions"]:
        if q["kind"] == "choice":
            answers.append([q["qIndex"], 0])
        elif q["kind"] == "fill":
            opts = (q.get("select_options") or [[]])[0]
            vals = [o.get("value") for o in opts if o.get("value")][:q["blanks"]]
            answers.append([q["qIndex"], vals])
    print(f"[test] submitting {len(answers)} answers:")
    for a in answers:
        print(f"        {a}")

    env = await s.submit_answers(answers)
    res = env.get("result") or {}
    print(f"\n  state={env['state']} submitted={res.get('submitted')} "
          f"dry_run={res.get('dry_run')}")
    if res.get("warning"):
        print(f"  WARNING: {res['warning']}")
    show("echo (what actually landed)", res.get("echo"))
    show("set_answers result", res.get("set_answers"))
    print(f"\n  incomplete: {res.get('incomplete')}")

    show("status", s.status())
    await s.stop()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
