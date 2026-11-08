#!/usr/bin/env python3
"""Unit checks for the server-provided answer key ("runtime auto-answering").

Fixtures are the REAL payload shapes captured from the live site
(`PcReadPraxis.$data.jobList`):

  type_id 1 : options_answer is a bare option label, e.g. "B"
  type_id 5 : options_answer is a JSON array of {title,label} where `title` is
              what goes into insertWordAnswers for that blank, and
              optionsArray1 mirrors it as [{label,title}]

No browser and no network: everything here is pure data transformation.

Run: python scripts/test_answer_key.py
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import elang_reader as er  # noqa: E402

results = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    results.append((name, bool(cond)))


def tf_job(job_id, answer):
    """A True/False single-choice job, as the site sends it."""
    job = {
        "id": job_id,
        "type_id": 1,
        "title": "<p>some statement</p>",
        "optionsArray": [
            {"label": "A", "title": "True", "is_check": 0},
            {"label": "B", "title": "False", "is_check": 0},
        ],
    }
    if answer is not None:
        job["options_answer"] = answer
    return job


def word_fill_job(job_id, blanks=7, answer_json=True):
    """The word-bank fill job measured on the live site (7 blanks)."""
    titles = ["D", "C", "B", "A", "F", "G", "E"][:blanks]
    job = {
        "id": job_id,
        "type_id": 5,
        "title": "<p>__（1）__ : a small box ...</p>",
        "titleChunks": [{"isInput": True} for _ in range(blanks)],
        "optionsArray": [
            {"label": "A", "title": "moniker"},
            {"label": "B", "title": "clientele"},
            {"label": "C", "title": "craze"},
            {"label": "D", "title": "carton"},
        ],
        "optionsArray1": [{"label": i, "title": t}
                          for i, t in enumerate(titles, start=1)],
    }
    if answer_json:
        job["options_answer"] = json.dumps(
            [{"title": t, "label": i, "score": 1}
             for i, t in enumerate(titles, start=1)])
    return job


print("=== choice questions ===")
key = er._answer_key_from_job(tf_job(9315, "B"))
check("a bare label becomes a choice key", key == {"kind": "choice", "labels": ["B"]}, str(key))

key = er._answer_key_from_job(tf_job(9315, "b"))
check("lowercase label is normalised", key and key.get("labels") == ["B"], str(key))

key = er._answer_key_from_job(tf_job(9315, None))
check("missing options_answer yields no key", key is None, str(key))

key = er._answer_key_from_job(tf_job(9315, "B,C"))
check("multi-label on a single-choice job is refused", key is None, str(key))

print("\n=== fill questions ===")
key = er._answer_key_from_job(word_fill_job(9317))
check("JSON answer becomes ordered fill values",
      key == {"kind": "fill", "values": ["D", "C", "B", "A", "F", "G", "E"]},
      str(key))

# optionsArray1 mirrors options_answer: it must produce the same values.
mirror_only = word_fill_job(9317, answer_json=False)
key = er._answer_key_from_job(mirror_only)
check("optionsArray1 alone is enough",
      key and key.get("values") == ["D", "C", "B", "A", "F", "G", "E"], str(key))

# A scrambled JSON order must be sorted by label, not taken as given.
scrambled = word_fill_job(9317, answer_json=False)
scrambled["options_answer"] = json.dumps([
    {"title": "E", "label": 7}, {"title": "D", "label": 1},
    {"title": "G", "label": 6}, {"title": "C", "label": 2},
    {"title": "F", "label": 5}, {"title": "B", "label": 3},
    {"title": "A", "label": 4},
])
key = er._answer_key_from_job(scrambled)
check("unordered JSON is sorted by label",
      key and key.get("values") == ["D", "C", "B", "A", "F", "G", "E"], str(key))

broken = word_fill_job(9317, answer_json=False)
broken["options_answer"] = "{not json"
key = er._answer_key_from_job(broken)
check("unparseable JSON falls back to optionsArray1",
      key and len(key.get("values") or []) == 7, str(key))

print("\n=== typed fill (type_id 2) keys from optionsArray ===")
# Type 2 ships no options_answer; the expected text is optionsArray[n].title,
# which is exactly what the app grades against (isFillRight(input, title)).
typed = {
    "id": 9453,
    "type_id": 2,
    "title": "<p>fill in</p>",
    "titleChunks": [{"isInput": True} for _ in range(4)],
    "optionsArray": [
        {"title": "carton"}, {"title": "craze"},
        {"title": "clientele"}, {"title": "transportation&transport"},
    ],
}
key = er._answer_key_from_job(typed)
check("type 2 reads optionsArray",
      key == {"kind": "fill", "values": ["carton", "craze", "clientele",
                                        "transportation"]}, str(key))
check("'&' alternatives collapse to the first",
      key and key["values"][3] == "transportation")

typed_no_opts = dict(typed, optionsArray=[])
check("type 2 without optionsArray yields no key",
      er._answer_key_from_job(typed_no_opts) is None)

typed_blank = dict(typed, optionsArray=[{"title": "a"}, {"title": ""}])
check("type 2 with an empty expected value yields no key",
      er._answer_key_from_job(typed_blank) is None)

print("\n=== multi-select (type_id 4) ===")
# options_answer holds the chosen labels joined by commas; the app grades by
# comparing that same joined string, and its selectOption() TOGGLES for type 4.
multi_job = {
    "id": 9600,
    "type_id": 4,
    "title": "<p>choose all that apply</p>",
    "optionsArray": [
        {"label": "A", "title": "first", "is_check": 0},
        {"label": "B", "title": "second", "is_check": 0},
        {"label": "C", "title": "third", "is_check": 0},
        {"label": "D", "title": "fourth", "is_check": 0},
    ],
}
multi_job["options_answer"] = "A,C"
key = er._answer_key_from_job(multi_job)
check("a comma list becomes a multi key",
      key == {"kind": "multi", "labels": ["A", "C"]}, str(key))

key = er._answer_key_from_job(dict(multi_job, options_answer="a , c"))
check("spacing and case are normalised", key == {"kind": "multi", "labels": ["A", "C"]},
      str(key))

check("a single label is still a valid multi key",
      er._answer_key_from_job(dict(multi_job, options_answer="B"))
      == {"kind": "multi", "labels": ["B"]})

check("empty multi answer is refused",
      er._answer_key_from_job(dict(multi_job, options_answer="")) is None)
check("non-label multi answer is refused",
      er._answer_key_from_job(dict(multi_job, options_answer="yes,no")) is None)

qs = er._build_questions([multi_job], [])
answers, why = er._answers_from_keys(qs)
check("multi key converts to a list of option indexes",
      answers == [[0, [0, 2]]], f"{answers} / {why}")

bad = dict(multi_job, options_answer="A,Z")
answers, why = er._answers_from_keys(er._build_questions([bad], []))
check("a label outside the options is rejected", answers is None, str(why))

print("\n=== unsupported shapes are refused, not guessed ===")
free = dict(tf_job(9401, "anything"), type_id=3)
check("free text (type 3) is refused", er._answer_key_from_job(free) is None)

empty = word_fill_job(9318, answer_json=False)
empty["options_array"] = []
empty.pop("optionsArray1", None)
check("no key source at all is refused", er._answer_key_from_job(empty) is None)

print("\n=== _build_questions carries the key ===")
jobs = [tf_job(9315, "B"), word_fill_job(9317)]
qs = er._build_questions(jobs, [])
check("choice question has a key", qs[0]["answer_key"] is not None, str(qs[0]["answer_key"]))
check("fill question has a key", qs[1]["answer_key"] is not None, str(qs[1]["answer_key"]))
check("fill blanks counted", qs[1]["blanks"] == 7, str(qs[1]["blanks"]))

print("\n=== _answers_from_keys ===")
answers, why = er._answers_from_keys(qs)
check("all-keyed article converts", answers is not None, str(why))
check("choice answer is the option index", answers and answers[0] == [0, 1], str(answers))
check("fill answer is one values list", answers and answers[1][0] == 1, str(answers))
check("fill values preserved in order",
      answers and answers[1][1] == ["D", "C", "B", "A", "F", "G", "E"],
      str(answers[1][1] if answers else None))

# Partial keying must be rejected: half-keyed means half-guessed.
partial = [tf_job(9315, "B"), word_fill_job(9319, answer_json=False)]
partial[1].pop("optionsArray1", None)
partial_qs = er._build_questions(partial, [])
answers, why = er._answers_from_keys(partial_qs)
check("partially keyed article is rejected", answers is None, str(why))
check("rejection names the problem", "no answer key" in (why or ""), str(why))

# A label the question does not offer must not be turned into a guess.
bad = er._build_questions([tf_job(9315, "Z")], [])
answers, why = er._answers_from_keys(bad)
check("label outside the options is rejected", answers is None, str(why))

# Fewer keyed values than blanks must be rejected.
short = word_fill_job(9320, blanks=7, answer_json=False)
short["optionsArray1"] = short["optionsArray1"][:3]
short.pop("options_answer", None)
short_qs = er._build_questions([short], [])
answers, why = er._answers_from_keys(short_qs)
check("key shorter than the blank count is rejected", answers is None, str(why))

print("\n=== fill values resolve through this blank's options ===")
select_job = {
    "id": 9500,
    "type_id": 7,
    "title": "fill",
    "titleChunks": [{"isInput": True}, {"isInput": True}],
    "optionsArray1": [{"label": 1, "title": "B"}, {"label": 2, "title": "A"}],
}
select_q = er._build_questions([select_job], [])
select_q[0]["select_options"] = [
    [{"label": "A", "value": "A-swimming hole"}, {"label": "B", "value": "B-desert"}],
    [{"label": "A", "value": "A-sand"}, {"label": "B", "value": "B-rock"}],
]
answers, why = er._answers_from_keys(select_q)
check("bare letters map to option values",
      answers == [[0, ["B-desert", "A-sand"]]], f"{answers} / {why}")

print("\n" + "=" * 58)
passed = sum(1 for _, ok in results if ok)
print(f"{passed}/{len(results)} checks passed")
for name, ok in results:
    if not ok:
        print(f"  FAILED: {name}")
sys.exit(0 if passed == len(results) else 1)