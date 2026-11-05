#!/usr/bin/env python3
"""Unit checks for the P1 robustness changes that do not need a browser.

Covers:
  * the process-level browser guard closes the context on success and on error
  * `request_ai_answers` clears the channel BEFORE publishing and tells the
    waiter not to clear it again
  * `wait_for_ai(clear_at_start=False)` consumes an answer published before the
    wait began, and drops one that belongs to another article
  * a stale captcha answer is removed when a new request is published
  * `answer_ipc._send` publishes atomically (no temp file left, valid JSON)

Run: python scripts/test_p1_safety.py
"""
import asyncio
import json
import os
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

# The IPC paths are resolved at import time, so redirect them first.
_SCRATCH = REPO / "temp"
_SCRATCH.mkdir(parents=True, exist_ok=True)
_IPC = _SCRATCH / f"elang-p1-{os.getpid()}-{int(time.time())}"
_IPC.mkdir(parents=True, exist_ok=True)
os.environ["ELANG_TMP_DIR"] = str(_IPC)

import answer_ipc            # noqa: E402
import elang_reader as er    # noqa: E402

results = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    results.append((name, bool(cond)))


class FakeContext:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


try:
    print("=== process-level browser guard ===")
    ctx = FakeContext()
    er._ACTIVE_CONTEXT = ctx

    async def boom():
        raise RuntimeError("boom")

    try:
        asyncio.run(er._run_guarded(boom()))
    except RuntimeError:
        pass
    check("context closed when the mode raises", ctx.closed is True)
    check("global cleared after a failure", er._ACTIVE_CONTEXT is None)

    ctx2 = FakeContext()
    er._ACTIVE_CONTEXT = ctx2

    async def ok():
        return 7

    value = asyncio.run(er._run_guarded(ok()))
    check("return value preserved", value == 7)
    check("context closed on success too", ctx2.closed is True)

    print("\n=== request publish order ===")
    captured = {}

    async def fake_wait(timeout=er.AI_TIMEOUT, expect_article_number=None,
                        clear_at_start=True):
        captured.update(
            timeout=timeout,
            expect=expect_article_number,
            clear=clear_at_start,
            signal_exists=Path(er.SIGNAL_FILE).exists(),
            current=json.loads(Path(er.CURRENT_FILE).read_text(encoding="utf-8")),
        )
        return {"status": "skip"}

    original_wait = er.wait_for_ai
    er.wait_for_ai = fake_wait
    try:
        Path(er.SIGNAL_FILE).write_text('{"status": "answers_ready"}',
                                        encoding="utf-8")
        got = asyncio.run(er.request_ai_answers({"article_number": 7,
                                                 "title": "t"}))
    finally:
        er.wait_for_ai = original_wait

    check("stale signal cleared before publishing", captured.get("signal_exists") is False)
    check("waiter is told not to clear again", captured.get("clear") is False)
    check("waiter knows the article id", captured.get("expect") == 7)
    check("CURRENT holds the new article",
          captured.get("current", {}).get("article_number") == 7)
    check("request result returned", got == {"status": "skip"})

    print("\n=== late-answer handling (wait_for_ai) ===")
    Path(er.SIGNAL_FILE).write_text(
        json.dumps({"status": "answers_ready", "article_number": 5,
                    "answers": [[0, 1]]}), encoding="utf-8")
    got = asyncio.run(er.wait_for_ai(timeout=3, expect_article_number=5,
                                     clear_at_start=False))
    check("answer published before the wait is accepted",
          got is not None and got.get("answers") == [[0, 1]], str(got))

    Path(er.SIGNAL_FILE).write_text(
        json.dumps({"status": "answers_ready", "article_number": 6,
                    "answers": [[0, 1]]}), encoding="utf-8")
    got = asyncio.run(er.wait_for_ai(timeout=2, expect_article_number=5,
                                     clear_at_start=False))
    check("answer for another article is dropped", got is None)
    check("the stale signal was removed", not Path(er.SIGNAL_FILE).exists())

    print("\n=== stale captcha answer ===")
    Path(er.CAPTCHA_ANSWER_FILE).write_text('{"captcha_code": "ABCD"}',
                                            encoding="utf-8")
    er._write_captcha_request(b"\x89PNG\r\n")
    check("stale answer removed when a new image is published",
          not Path(er.CAPTCHA_ANSWER_FILE).exists())
    check("captcha request written", Path(er.CAPTCHA_REQUEST_FILE).exists())

    print("\n=== atomic signal write ===")
    answer_ipc._send({"status": "skip"})
    sig = Path(er.SIGNAL_FILE)
    check("signal parses", json.loads(sig.read_text(encoding="utf-8"))["status"] == "skip")
    check("no temp file left behind", not sig.with_name(sig.name + ".tmp").exists())
finally:
    shutil.rmtree(_IPC, ignore_errors=True)

print("\n" + "=" * 58)
passed = sum(1 for _, ok in results if ok)
print(f"{passed}/{len(results)} checks passed")
for name, ok in results:
    if not ok:
        print(f"  FAILED: {name}")
sys.exit(0 if passed == len(results) else 1)
