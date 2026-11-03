#!/usr/bin/env python3
"""The answering side of `elang run` — the agent's half of the file IPC.

`elang run` drives the browser and, for an article the answer bank does not cover,
writes `<ipc>/elang_current.json` and waits. This module is the other half: it
shows the pending article, then writes `<ipc>/elang_signal.json` with the answers.

Why a first-class command rather than a helper script
-----------------------------------------------------
This interface was previously a throwaway (`review.py`, since archived), which is
exactly why `elang run` became unusable: the browser half existed and the
answering half did not. "The agent answers" is a supported mode, so it ships with
the tool.

It imports only `config`, never `elang_reader`, so it stays fast and does not
require Playwright to be importable.

Commands
--------
    elang pending              show the pending article (passage + questions)
    elang pending --brief      one line: status, title, question count
    elang pending --json       the raw request as JSON
    elang answer 0=A 1=C       answer by option LETTER (0-based question index)
    elang answer "5=A,B,C"     fill question: one value per blank, comma separated
    elang answer --raw '[[0,1],[1,2]]'
    elang skip                 submit the pending article without answering
    elang continue             resume after the 50-article checkpoint
    elang stop                 stop the run; progress is already saved
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CURRENT = config.ipc_file("elang_current.json")
SIGNAL = config.ipc_file("elang_signal.json")
LETTERS = "ABCDEFGH"


def _load():
    try:
        return json.loads(CURRENT.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"ERROR: cannot read {CURRENT}: {type(e).__name__}: {e}")
        return None


def _send(payload):
    SIGNAL.parent.mkdir(parents=True, exist_ok=True)
    SIGNAL.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"sent -> {SIGNAL}: {json.dumps(payload, ensure_ascii=False)[:200]}")


# ---------------------------------------------------------------- display

def cmd_pending(args):
    d = _load()
    if not d:
        print(f"no pending article ({CURRENT} not present)")
        return 0

    status = d.get("status")
    qs = d.get("questions") or []

    if getattr(args, "json", False):
        print(json.dumps(d, ensure_ascii=False, indent=2))
        return 0

    if getattr(args, "brief", False):
        print(f"status={status} #{d.get('article_number')} "
              f"{d.get('article_name')!r} questions={len(qs)} "
              f"passage={len(d.get('passage') or '')}ch "
              f"answer_sent={SIGNAL.exists()}")
        return 0

    if status != "waiting_for_ai":
        # The checkpoint pause uses the same file with a different status.
        print(f"status={status} (the run is not waiting for an article answer)")
        if status == "checkpoint":
            print(f"  articles submitted so far: {d.get('total_submitted')}")
            print("  resume with:  elang continue     stop with:  elang stop")
        return 0

    print(f"=== #{d.get('article_number')} {d.get('article_name')} ===")
    print("\n--- PASSAGE ---")
    print(d.get("passage") or "")
    print(f"\n--- QUESTIONS ({len(qs)}) ---")
    for q in qs:
        print(f"\n[q{q.get('index')}] kind={q.get('kind')} "
              f"type_id={q.get('type_id')} blanks={q.get('blanks')}")
        print(f"   {q.get('question')}")
        for o in q.get("options") or []:
            print(f"     {o.get('label')}. {o.get('text')}")
        for i, sel in enumerate(q.get("select_options") or []):
            vals = ", ".join(str(o.get("value")) for o in (sel or [])[:12])
            print(f"     select[{i}]: {vals}")
    print("\nAnswer with:  elang answer 0=A 1=C ...   "
          "(fill: one value per blank, comma separated)")
    return 0


# ---------------------------------------------------------------- answering

def _letter_to_index(letter, question):
    letter = letter.strip().upper()
    if len(letter) != 1 or not letter.isalpha():
        return None
    for i, o in enumerate(question.get("options") or []):
        lab = str(o.get("label") or "").strip().upper().rstrip(".")
        if lab == letter:
            return i
    idx = ord(letter) - ord("A")
    return idx if 0 <= idx < len(question.get("options") or []) else None


def _resolve_fill(raw, question, blank_i):
    """Resolve one fill value into what the page's select/input expects.

    Word-bank questions (type 5) bind to the option's VALUE, not its label, so a
    bare letter must be mapped through that blank's `select_options`. Free-text
    fills pass through unchanged.
    """
    raw = str(raw or "").strip()
    groups = question.get("select_options") or []
    grp = groups[blank_i] if blank_i < len(groups) else (groups[0] if groups else None)
    if not grp:
        return raw
    want = raw.upper()
    for o in grp:
        val = str(o.get("value") or "")
        lab = str(o.get("label") or "").strip().upper().rstrip(".")
        if val == raw:
            return val
        if lab == want or val.upper().startswith(want + "-"):
            return val
    return raw      # let the page decide; don't invent a value


def cmd_answer(args):
    if args.raw:
        try:
            answers = json.loads(args.raw)
        except Exception as e:
            print(f"ERROR: --raw is not valid JSON: {type(e).__name__}: {e}")
            return 1
        if not isinstance(answers, list):
            print("ERROR: --raw expects a list of [qIndex, value] pairs")
            return 1
        _send({"status": "answers_ready", "answers": answers})
        return 0

    if not args.pairs:
        print("ERROR: nothing to answer, e.g.  elang answer 0=A 1=C")
        return 1

    d = _load()
    if d is None:
        print(f"no pending article ({CURRENT} not present) — nothing to answer")
        return 1
    if d.get("status") != "waiting_for_ai":
        print(f"the run is not waiting for an article answer (status={d.get('status')});"
              f" use `elang continue` / `elang stop` for a checkpoint")
        return 1

    by_index = {q.get("index"): q for q in (d.get("questions") or [])}

    answers = []
    for pair in args.pairs:
        if "=" not in pair:
            print(f"ERROR: expected qIdx=VALUE, got {pair!r}")
            return 1
        qi_s, val = pair.split("=", 1)
        if not qi_s.strip().isdigit():
            print(f"ERROR: question index must be a number, got {qi_s!r}")
            return 1
        qi = int(qi_s)
        val = val.strip()

        if "," in val:
            q = by_index.get(qi)
            parts = [v.strip() for v in val.split(",") if v.strip()]
            if q is not None:
                parts = [_resolve_fill(p, q, i) for i, p in enumerate(parts)]
            answers.append([qi, parts])
            continue

        q = by_index.get(qi)
        if q is None:
            print(f"ERROR: q{qi} is not in the pending article "
                  f"(seen: {sorted(by_index)})")
            return 1
        if q.get("kind") == "choice":
            idx = _letter_to_index(val, q)
            if idx is None:
                print(f"ERROR: q{qi} has no option {val!r}")
                return 1
            answers.append([qi, idx])
        else:
            # Single value for a fill question: keep it a list so set_answers gets
            # one entry per blank.
            blanks = q.get("blanks") or 1
            if blanks > 1:
                print(f"ERROR: q{qi} has {blanks} blank(s); give {blanks} values "
                      f"comma separated")
                return 1
            answers.append([qi, [_resolve_fill(val, q, 0)]])

    answers.sort(key=lambda a: a[0])
    _send({"status": "answers_ready", "answers": answers})
    return 0


def cmd_skip(args):
    _send({"status": "skip"})
    return 0


def cmd_continue(args):
    _send({"status": "continue"})
    return 0


def cmd_stop(args):
    _send({"status": "stop"})
    return 0


VERBS = {
    "pending": cmd_pending,
    "answer": cmd_answer,
    "skip": cmd_skip,
    "continue": cmd_continue,
    "stop": cmd_stop,
}


def run(verb, argv):
    """Entry point used by the `elang` dispatcher."""
    ap = argparse.ArgumentParser(prog=f"elang {verb}",
                                 description=VERBS[verb].__doc__ or "")
    if verb == "pending":
        ap.add_argument("--brief", action="store_true")
        ap.add_argument("--json", dest="json", action="store_true")
    if verb == "answer":
        ap.add_argument("pairs", nargs="*")
        ap.add_argument("--raw", default="",
                        help='JSON list of [qIndex, value] pairs')
    args = ap.parse_args(argv)
    return VERBS[verb](args)


def main():
    """Standalone use: `python scripts/answer_ipc.py <verb> ...`"""
    argv = sys.argv[1:]
    if not argv or argv[0] not in VERBS:
        print(__doc__)
        return 0
    return run(argv[0], argv[1:])


if __name__ == "__main__":
    sys.exit(main())
