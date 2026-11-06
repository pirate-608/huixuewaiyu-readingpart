#!/usr/bin/env python3
"""Checks for the read-only-article path ("暂无练习题，请先阅读文章。").

Some articles ship no exercises at all. The site renders a dedicated empty state
and relabels its submit button "完成阅读"; submitting posts a placeholder record
({job_id: 0, type_id: 999, is_right: 1}). Those articles must be COMPLETED.

The old engine treated "no questions" as "skip", which left such articles forever
unfinished, prevented the subject from ever being marked complete, and burned a
full extract timeout on every attempt.

Run: python scripts/test_read_only_article.py
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import elang_reader as er  # noqa: E402

results = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    results.append((name, bool(cond)))


def page(**over):
    base = {"jobs": [], "blocks": [], "imageLen": 0, "loading": False,
            "noExercises": True}
    base.update(over)
    return base


print("=== the empty state IS a read-only article ===")
check("loaded page showing the empty state",
      er._page_has_no_exercises(page()) is True)

print("\n=== the three ways it must NOT be treated as read-only ===")
check("a pending captcha is not a read-only article",
      er._page_has_no_exercises(page(imageLen=7414)) is False,
      "captcha gate also renders an empty jobList")

check("a still-loading page is not read-only",
      er._page_has_no_exercises(page(loading=True)) is False,
      "questions may just not have arrived yet")

check("no empty state on screen is not read-only",
      er._page_has_no_exercises(page(noExercises=False)) is False)

check("no data at all is not read-only",
      er._page_has_no_exercises(None) is False)

print("\n=== an empty answer set is valid for a zero-question article ===")
# This is what MCP submit_answers([]) relies on.
check("zero answers for zero questions counts as applied",
      er._answers_applied({"choice": 0, "fill": 0, "notes": []}, []) is True)

check("still rejects a missing component",
      er._answers_applied({"error": "PcReadPraxis not found"}, []) is False)

# And the key path must decline rather than claim success on an empty article.
answers, why = er._answers_from_keys([])
check("no questions yields no key answers", answers is None, str(why))

print("\n=== a single reading is never enough (the empty state flashes) ===")
# Measured: on a normal 6-question article the empty state is on screen briefly
# while the questions are in flight, so one reading misclassified it as
# read-only. The engine must require several consecutive confirmations.
check("confirmation window needs more than one poll",
      er.READ_ONLY_CONFIRM_POLLS >= 2, f"{er.READ_ONLY_CONFIRM_POLLS} polls")
check("quick mode never declares read-only",
      "if not quick and _page_has_no_exercises(data):" in
      (REPO / "scripts" / "elang_reader.py").read_text(encoding="utf-8"))

print("\n=== extract_page_content returns the flag ===")
# The timeout branch (blocked=False, no image) is where a missed empty state ends
# up; it must still be reported as no_exercises so the caller completes it.
src = (REPO / "scripts" / "elang_reader.py").read_text(encoding="utf-8")
session_src = (REPO / "scripts" / "elang_session.py").read_text(encoding="utf-8")
check("timeout branch sets no_exercises",
      'out["no_exercises"] = bool(no_ex_polls >= READ_ONLY_CONFIRM_POLLS' in src)
check("early return on the empty state uses the predicate",
      "no_ex_polls += 1" in src and "_page_has_no_exercises(data)" in src)
check("batch path completes read-only articles",
      '"completed_no_exercises"' in src)
check("MCP path exposes them instead of skipping",
      "no_exercises=True" in session_src)

print("\n" + "=" * 58)
passed = sum(1 for _, ok in results if ok)
print(f"{passed}/{len(results)} checks passed")
for name, ok in results:
    if not ok:
        print(f"  FAILED: {name}")
sys.exit(0 if passed == len(results) else 1)