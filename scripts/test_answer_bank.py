#!/usr/bin/env python3
"""Answer-bank regression tests.

Covers the four defects that made the bank contribute nothing:

  1. the data says format "letter" while the gate tested "letters" -> 67 entries
     were silently rejected
  2. letter-only entries were rejected for any article containing a fill question
     (the old `all_choice` gate), and fill answers were never applied at all
  3. word-level fuzzy matching was dead code: it split the NORMALISED title, which
     has every space stripped, so each title was a single token
  4. the loader reported a bare entry count, implying all were usable

Run: python scripts/test_answer_bank.py
"""
"""Verify the answer-bank mapper: format handling, fill resolution, rejection.

Uses the real answers.json plus synthetic question shapes, so it exercises the
actual data without touching the site.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import elang_reader as er  # noqa: E402

er._load_answer_bank()
fails = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    if not cond:
        fails.append(name)


def choice(i, n=2):
    return {"index": i, "kind": "choice", "type_id": 1,
            "options": [{"label": chr(65 + k), "text": ""} for k in range(n)]}


def fill(i, blanks, sels=None):
    return {"index": i, "kind": "fill", "type_id": 5, "blanks": blanks,
            "select_options": sels or [],
            "options": [{"label": chr(65 + k), "text": ""} for k in range(blanks)]}


print("=== format: letter, all-choice article ===")
ans = {"format": "letter", "letters": ["B", "A", "D"]}
qs = [choice(0), choice(1, 4), choice(2, 4)]
got, why = er._bank_answers_for(ans, qs)
check("letter: accepted", got is not None, why or "")
check("letter: values", got == [[0, 1], [1, 0], [2, 3]], str(got))

print("\n=== format: letter (singular) is accepted — the original bug ===")
check("'letter' is a supported format", er._bank_format_supported({"format": "letter"}))
check("'letters' still accepted", er._bank_format_supported({"format": "letters"}))

print("\n=== format: letter_and_fill ===")
ans2 = {"format": "letter_and_fill",
        "letters": ["A", "B"],
        "fill_in_blank": [{"index": 1, "answer": "cargo"},
                          {"index": 2, "answer": "malfunctions"}]}
qs2 = [choice(0), choice(1), fill(2, 2)]
got, why = er._bank_answers_for(ans2, qs2)
check("letter_and_fill: accepted", got is not None, why or "")
check("letter_and_fill: fill values grouped",
      got is not None and [a for a in got if a[0] == 2] == [[2, ["cargo", "malfunctions"]]],
      str(got))

print("\n=== fill answer that is a bare LETTER maps through select options ===")
ans3 = {"format": "letter_and_fill", "letters": [],
        "fill_in_blank": [{"index": 1, "answer": "C"}, {"index": 2, "answer": "A"}]}
sels = [{"value": "A-avocation"}, {"value": "B-trinket"},
        {"value": "C-lather, rinse and repeat"}]
qs3 = [fill(0, 2, sels=[sels, sels])]
got, why = er._bank_answers_for(ans3, qs3)
check("letter fill resolved to option value",
      got == [[0, ["C-lather, rinse and repeat", "A-avocation"]]], str(got) or why)

print("\n=== unresolvable bare letter is REJECTED, not guessed ===")
bad = {"format": "fill_in_blank", "fill_in_blank": [{"index": 1, "answer": "Z"}]}
got, why = er._bank_answers_for(bad, [fill(0, 1, sels=[sels])])
check("unresolvable letter rejected", got is None and "could not resolve" in (why or ""), why or "")

print("\n=== count mismatches are rejected with a reason ===")
got, why = er._bank_answers_for({"format": "letter", "letters": ["A"]},
                                [choice(0), choice(1)])
check("too few letters rejected", got is None and "choice answer" in (why or ""), why or "")

got, why = er._bank_answers_for({"format": "letter", "letters": ["A", "B"]},
                                [choice(0), choice(1), fill(2, 1)])
check("letter-only bank cannot cover a fill question",
      got is None and "fill answer" in (why or ""), why or "")

print("\n=== unknown format rejected ===")
got, why = er._bank_answers_for({"format": "weird"}, [choice(0)])
check("unknown format rejected", got is None and "unsupported" in (why or ""), why or "")

print("\n=== fuzzy matching now works (was dead code) ===")
# Exact-ish and word-overlap lookups against real titles
for probe, expect in [
    ("The Widernet Project", "exact"),
    ("Underwater Concert", "exact"),
]:
    a, info = er._match_answer_bank(probe)
    check(f"match {probe!r}", a is not None, info or "no match")

a, info = er._match_answer_bank("underwater concert 2024")
check("word overlap finds a title with extra words", a is not None, info or "no match")

a, info = er._match_answer_bank("Completely Unrelated Article Name")
check("unrelated title does not match", a is None, info or "")


print("\n=== MCP path consults the bank (it used to ignore it entirely) ===")
from elang_session import ElangSession  # noqa: E402

sess = ElangSession()
content = {"title": "The Widernet Project",
           "questions": [choice(0, 4), choice(1, 4), choice(2, 4), choice(3, 4)]}
note, answers = sess._bank_lookup(content, {"name": "The Widernet Project"})
check("session finds a bank match", answers is not None, note or "no note")
check("session returns usable answers",
      answers is not None and len(answers) == 4, str(answers))

content2 = {"title": "The Widernet Project",
            "questions": [choice(0, 4), choice(1, 4), fill(2, 1)]}
note2, answers2 = sess._bank_lookup(content2, {"name": "The Widernet Project"})
check("session reports a near miss instead of applying it",
      answers2 is None and note2 and "matched" in note2, note2 or "")

content3 = {"title": "Completely Unrelated Article Name", "questions": [choice(0)]}
note3, answers3 = sess._bank_lookup(content3, {"name": "x"})
check("session returns nothing for an unknown title",
      note3 is None and answers3 is None)

print("\n" + "=" * 58)
if fails:
    print(f"{len(fails)} FAILED: {fails}")
    sys.exit(1)
print("all mapper checks passed")
