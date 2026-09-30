#!/usr/bin/env python3
"""Explicit state machine over the elang browser automation (MCP Level 1).

Why this module exists
----------------------
`elang_reader.py` drives the browser correctly but only as a *batch script*: it
writes the pending article to a file and then blocks in `wait_for_ai()` until the
answering side notices. Both halves end up polling each other, and the "next thing
to do" is never expressed anywhere — it has to be inferred from logs.

This module turns the same primitives into an explicit state machine:

  * every method RETURNS immediately, describing the new state,
  * nothing waits for answers,
  * each return value names the actions that are valid next.

That single change removes the timeout dance: an article can sit in
`awaiting_answers` indefinitely because no one is blocked on it.

This is Level 1 of the MCP plan (see MCP_DESIGN.md §3): it needs no MCP
dependency, and the eventual MCP server becomes a thin wrapper that exposes these
same methods as tools.

Usage (interactive driving, for testing):

    python scripts/elang_session.py demo --subject 25
"""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import elang_reader as er  # noqa: E402


# ---------------------------------------------------------------- states
class State:
    IDLE = "idle"
    RUNNING = "running"
    AWAITING_CAPTCHA = "awaiting_captcha"
    AWAITING_ANSWERS = "awaiting_answers"
    SUBMITTED = "submitted"
    FINISHED = "finished"
    ERROR = "error"


# actions the caller may invoke, per state
NEXT = {
    State.IDLE: ["start", "list_subjects"],
    State.RUNNING: ["open_next", "list_lessons", "status", "stop"],
    State.AWAITING_CAPTCHA: ["get_captcha", "solve_captcha", "skip_article", "status"],
    State.AWAITING_ANSWERS: ["submit_answers", "skip_article", "status"],
    State.SUBMITTED: ["open_next", "status", "stop"],
    State.FINISHED: ["status", "start"],
    State.ERROR: ["status", "start"],
}


class AnswerError(ValueError):
    """Raised when submitted answers are structurally invalid."""


class ElangSession:
    """A long-lived solver session. One session == one browser == one run.

    Deliberately single-run: two sessions sharing a browser was the cause of a
    real failure where two scripts fought over one captcha dialog.
    """

    def __init__(self, dry_run=False, limit=None, headless=False):
        self.dry_run = dry_run
        self.limit = limit
        self.headless = headless

        self.state = State.IDLE
        self.error = None

        self._pw = None
        self.context = None
        self.page = None

        # run bookkeeping
        self.subjects = []          # [{id, name, resource_num}]
        self.lessons = []           # current subject's article list
        self.subject = None         # current subject dict
        self.article = None         # current article info dict
        self.content = None         # {questions, passage, title, ...}
        self.submitted = 0
        self.done_subjects = set()

    # ------------------------------------------------------------ envelope
    def envelope(self, **extra):
        """Uniform return shape. `blocking` is always False by design."""
        out = {
            "state": self.state,
            "blocking": False,
            "next_actions": NEXT.get(self.state, ["status"]),
        }
        if self.error:
            out["error"] = self.error
        if self.subject:
            out["subject"] = {"id": self.subject.get("id"),
                              "name": self.subject.get("name")}
        if self.article:
            out["article"] = {
                "index": self.article.get("index"),
                "resources_id": self.article.get("id"),
                "title": self.article.get("name"),
                "log_id": self.article.get("log_id"),
            }
        out.update(extra)
        return out

    def _fail(self, msg):
        self.state = State.ERROR
        self.error = msg
        print(f"[session] ERROR: {msg}")
        return self.envelope()

    # ------------------------------------------------------------ lifecycle
    async def start(self):
        """Open the browser and get to a logged-in state."""
        try:
            self._pw = await er.async_playwright().start()
            self.context, self.page, restored = await er.open_browser(self._pw)
            ok = await er.ensure_logged_in(
                self.page, "https://elang.zju.edu.cn/#/pc/read/index", restored)
            if not ok:
                return self._fail("login failed")
            self.state = State.RUNNING
            self.error = None
            return self.envelope()
        except Exception as e:
            return self._fail(f"{type(e).__name__}: {e}")

    async def stop(self):
        """Close the browser. Never kills processes by name."""
        try:
            if self.context is not None:
                await self.context.close()
        except Exception as e:
            print(f"[session] context close failed: {type(e).__name__}: {e}")
        try:
            if self._pw is not None:
                await self._pw.stop()
        except Exception:
            pass
        self.context = None
        self.page = None
        self._pw = None
        self.state = State.IDLE
        return self.envelope()

    # ------------------------------------------------------------ discovery
    async def list_subjects(self):
        """Read the subject list from #/pc/read/index."""
        if self.page is None:
            return self._fail("session not started")
        ok = await er._wait_until(self.page, er.JS_PIN_INDEX_VM_AND_CHECK,
                                  timeout_s=30, interval_ms=400,
                                  label="PcReadIndex listData")
        if not ok:
            return self._fail("subject list did not load")
        raw = await self.page.evaluate("""() => {
            const vm = window.__elangIndexVm;
            if (!vm) return [];
            return (vm.$data.listData || []).map(x => ({
                id: x.id, name: x.name || '',
                resource_num: Number(x.resource_num || 0),
            })).filter(x => x.id != null && x.resource_num > 0);
        }""")
        seen, uniq = set(), []
        for c in raw:
            if c["name"] not in seen:
                seen.add(c["name"])
                uniq.append(c)
        self.subjects = uniq
        return self.envelope(subjects=uniq)

    async def list_lessons(self, subject_id):
        """Load one subject's article list."""
        if self.page is None:
            return self._fail("session not started")
        subj = next((s for s in self.subjects if str(s["id"]) == str(subject_id)), None)
        if subj is None:
            subj = {"id": subject_id, "name": f"subject {subject_id}"}
        self.subject = subj

        await er.ensure_fresh_token(
            self.page, "https://elang.zju.edu.cn/#/pc/read/index")
        url = f"https://elang.zju.edu.cn/#/pc/read/learn?subject_id={subject_id}"
        await er.navigate_to(self.page, url)
        self.lessons = await er.get_article_list(self.page)
        if not self.lessons:
            return self._fail(f"no articles for subject {subject_id}")
        self.state = State.RUNNING
        self.error = None
        pending = sum(1 for a in self.lessons if not a.get("isCompleted"))
        return self.envelope(
            lessons=[{"index": a.get("index"), "id": a.get("id"),
                      "name": a.get("name"), "isCompleted": a.get("isCompleted")}
                     for a in self.lessons],
            pending=pending,
        )

    # ------------------------------------------------------------ advancing
    async def open_next(self):
        """Advance to the next unfinished article.

        Ends in `awaiting_captcha` or `awaiting_answers`, or `finished` when the
        subject has no unfinished articles left. Never waits for answers.
        """
        if self.page is None:
            return self._fail("session not started")

        pending = [a for a in self.lessons if not a.get("isCompleted")]
        if self.limit is not None and self.submitted >= self.limit:
            self.state = State.FINISHED
            return self.envelope(reason=f"limit {self.limit} reached")

        # skip articles we could not open; never loop forever on them
        for art in pending:
            self.article = dict(art)
            log_id, rid, url = await er.click_article(
                self.page, art.get("name"), art)
            if not log_id or not rid:
                print(f"[session] could not open {art.get('name')!r}; skipping")
                continue
            self.article["log_id"] = log_id
            self.article["resources_id"] = rid

            # captcha first, then answer: questions only load once it is passed
            content = await er.extract_page_content(self.page, timeout_s=8, quick=True)
            if content.get("blocked"):
                self.state = State.AWAITING_CAPTCHA
                self.error = None
                return self.envelope(captcha_pending=True)
            if not content.get("questions"):
                content = await er.extract_page_content(self.page)
            if content.get("blocked"):
                self.state = State.AWAITING_CAPTCHA
                self.error = None
                return self.envelope(captcha_pending=True)
            if not content.get("questions"):
                print(f"[session] no questions for {art.get('name')!r}; skipping")
                continue

            self.content = content
            self.state = State.AWAITING_ANSWERS
            self.error = None
            return self.envelope(
                article={
                    "index": art.get("index"),
                    "resources_id": rid,
                    "log_id": log_id,
                    "title": content.get("title") or art.get("name"),
                    "passage": content.get("passage"),
                    "questions": self._describe_questions(content["questions"]),
                },
                hint="Answer every question, then call submit_answers. "
                     "Fill questions need one value per blank.",
            )

        self.state = State.FINISHED
        return self.envelope(reason="no unfinished articles left")

    @staticmethod
    def _describe_questions(questions):
        """Question shape for the caller, with an explicit answer format."""
        out = []
        for q in questions:
            kind = q.get("kind")
            fmt = ("letter" if kind == "choice"
                   else "value_per_blank" if kind == "fill" else "unsupported")
            out.append({
                "qIndex": q.get("index"),
                "kind": kind,
                "type_id": q.get("type_id"),
                "multi": q.get("multi"),
                "blanks": q.get("blanks"),
                "text": q.get("question"),
                "options": [{"label": o.get("label"), "text": o.get("text")}
                            for o in (q.get("options") or [])],
                "select_options": q.get("select_options"),
                "answer_format": fmt,
            })
        return out

    # ------------------------------------------------------------ captcha
    async def get_captcha(self):
        """Return the pending captcha image. Never retries or refreshes."""
        if self.page is None:
            return self._fail("session not started")
        state = await er._captcha_state(self.page)
        img = (state or {}).get("imageBase64") or ""
        if not img:
            return self._fail("no captcha image available")
        png = er._decode_data_uri(img)
        out = er._save_captcha_image(png, "captcha_current.png")
        return self.envelope(
            captcha={"image_path": out, "chars_expected": 4,
                     "image_base64": img},
            hint="Read the 4 characters, then call solve_captcha(code).",
        )

    async def solve_captcha(self, code):
        """Submit a captcha code and advance."""
        if self.page is None:
            return self._fail("session not started")
        code = er.re.sub(r"[^0-9A-Za-z]", "", str(code or ""))
        if len(code) < 4:
            return self._fail(f"captcha code must be 4 characters, got {code!r}")
        ok = await er._submit_captcha(self.page, code[:4])
        if not ok:
            self.state = State.AWAITING_CAPTCHA
            return self.envelope(captcha_pending=True, reason="code rejected")
        content = await er.extract_page_content(self.page)
        if not content.get("questions"):
            self.state = State.AWAITING_CAPTCHA
            return self.envelope(captcha_pending=True,
                                 reason="questions still not available")
        self.content = content
        self.state = State.AWAITING_ANSWERS
        self.error = None
        return self.envelope(
            article={"title": content.get("title"), "passage": content.get("passage"),
                     "questions": self._describe_questions(content["questions"])},
        )

    # ------------------------------------------------------------ answering
    def validate(self, answers):
        """Reject structurally invalid answers BEFORE touching the browser.

        Validating here is what makes an `echo` possible, and an echo is what makes
        a silent mis-answer (a blank that never got filled) visible instead of
        mysterious.
        """
        if self.content is None:
            raise AnswerError("no article is loaded")
        qs = self.content["questions"]
        by_index = {q["index"]: q for q in qs}

        if not isinstance(answers, list):
            raise AnswerError("answers must be a list")

        seen = set()
        for item in answers:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                raise AnswerError(f"each answer must be [qIndex, value], got {item!r}")
            qi, val = item
            qi = int(qi)
            if qi not in by_index:
                raise AnswerError(f"qIndex {qi} is out of range (0..{len(qs) - 1})")
            if qi in seen:
                raise AnswerError(f"qIndex {qi} given more than once")
            seen.add(qi)

            q = by_index[qi]
            if q["kind"] == "choice":
                n = len(q.get("options") or [])
                if not isinstance(val, int) or not (0 <= val < n):
                    raise AnswerError(
                        f"q{qi} is a choice question with {n} option(s); "
                        f"value must be an option index 0..{n - 1}, got {val!r}")
            elif q["kind"] == "fill":
                blanks = q.get("blanks") or 0
                vals = val if isinstance(val, list) else [val]
                if blanks and len(vals) != blanks:
                    raise AnswerError(
                        f"q{qi} needs {blanks} value(s), one per blank; got "
                        f"{len(vals)}")
            else:
                raise AnswerError(
                    f"q{qi} has type_id {q.get('type_id')} which this tool cannot "
                    f"answer automatically")
        return True

    async def submit_answers(self, answers):
        """Record answers, then submit. Validates and echoes what landed."""
        if self.state != State.AWAITING_ANSWERS:
            return self._fail(f"not awaiting answers (state={self.state})")
        try:
            self.validate(answers)
        except AnswerError as e:
            # A validation failure is the CALLER's problem, not a session failure:
            # stay in awaiting_answers so a corrected submission can follow.
            self.error = str(e)
            return {
                "state": self.state,
                "blocking": False,
                "next_actions": NEXT.get(self.state, []),
                "error": str(e),
                "validation_failed": True,
            }

        res = await er.set_answers(self.page, answers)
        echo = await self._read_back(answers)
        submit_result = await er.submit(self.page, dry_run=self.dry_run)

        self.submitted += 1
        self.state = State.SUBMITTED
        self.error = None
        incomplete = [k for k, v in echo.items() if not v.get("filled")]
        return self.envelope(
            result={
                "submitted": not self.dry_run,
                "dry_run": self.dry_run,
                "set_answers": res,
                "submit": submit_result,
                "echo": echo,
                "incomplete": incomplete,
                "questions_total": len(self.content["questions"]),
            },
            warning=(f"these questions did not read back as answered: {incomplete}"
                     if incomplete else None),
        )

    async def _read_back(self, answers):
        """Read what actually landed in the component, per question."""
        given = {int(q): v for q, v in answers}
        qs = self.content["questions"]
        try:
            landed = await self.page.evaluate("""(jobs) => {
                const vm = window.__elangPraxisVm;
                if (!vm) return null;
                const M = (vm.$options && vm.$options.methods) || {};
                const out = {};
                for (const j of jobs) {
                    const job = (vm.$data.jobList || [])[j];
                    if (!job) { out[j] = null; continue; }
                    const fill = vm.$data.insertWordAnswers
                        ? (vm.$data.insertWordAnswers[job.id] || null) : null;
                    let answered = null;
                    try { answered = M.isAnswered ? !!M.isAnswered.call(vm, job) : null; }
                    catch (e) {}
                    out[j] = {
                        type_id: job.type_id,
                        selected: job.selectedAnswer !== undefined
                                  ? job.selectedAnswer : null,
                        fill: fill,
                        isAnswered: answered,
                    };
                }
                return out;
            }""", [q["index"] for q in qs])
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}

        echo = {}
        for q in qs:
            qi = q["index"]
            info = (landed or {}).get(str(qi)) or (landed or {}).get(qi) or {}
            if q["kind"] == "choice":
                echo[str(qi)] = {
                    "kind": "choice",
                    "given": given.get(qi),
                    "isAnswered": info.get("isAnswered"),
                    "filled": bool(info.get("isAnswered")),
                }
            else:
                vals = info.get("fill")
                expected = q.get("blanks") or 0
                assigned = len([v for v in (vals or []) if str(v or "").strip()])
                echo[str(qi)] = {
                    "kind": "fill",
                    "given": given.get(qi),
                    "assigned": assigned,
                    "blanks": expected,
                    "values": vals,
                    "isAnswered": info.get("isAnswered"),
                    "filled": bool(info.get("isAnswered")) or
                              (expected > 0 and assigned >= expected),
                }
        return echo

    async def skip_article(self):
        """Submit the current article as-is."""
        if self.state not in (State.AWAITING_ANSWERS, State.AWAITING_CAPTCHA):
            return self._fail(f"nothing to skip (state={self.state})")
        if self.state == State.AWAITING_CAPTCHA:
            return self._fail("cannot skip while a captcha is pending")
        result = await er.submit(self.page, dry_run=self.dry_run)
        self.submitted += 1
        self.state = State.SUBMITTED
        return self.envelope(result={"submitted": not self.dry_run, "submit": result})

    def status(self):
        return self.envelope(
            submitted=self.submitted,
            completed_subjects=sorted(self.done_subjects),
            lessons=len(self.lessons),
            pending=sum(1 for a in self.lessons if not a.get("isCompleted")),
        )


# ---------------------------------------------------------------- demo CLI
async def demo(subject_id):
    """Drive the state machine by hand, printing each envelope as JSON."""
    s = ElangSession()
    print(json.dumps(await s.start(), ensure_ascii=False, indent=2)[:800])
    if s.state == State.ERROR:
        return 1
    await s.list_subjects()
    print(f"[demo] {len(s.subjects)} subjects")
    print(json.dumps(await s.list_lessons(subject_id),
                     ensure_ascii=False)[:600])
    env = await s.open_next()
    print(json.dumps({k: v for k, v in env.items() if k != "article"},
                     ensure_ascii=False))
    if "article" in env:
        a = env["article"]
        print(f"[demo] article: {a['title']} ({len(a['questions'])} questions)")
    print("[demo] stopping without submitting (state machine demo)")
    await s.stop()
    return 0


def main():
    args = sys.argv[1:]
    if not args or args[0] != "demo":
        print(__doc__)
        return 0
    subject = "25"
    if "--subject" in args:
        i = args.index("--subject")
        if i + 1 < len(args):
            subject = args[i + 1]
    return asyncio.run(demo(subject))


if __name__ == "__main__":
    sys.exit(main())
