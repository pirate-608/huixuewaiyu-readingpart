# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Playwright automation that completes English reading exercises on 慧学外语 (elang.zju.edu.cn). The Python script drives an Edge browser, extracts passages and questions from the SPA, then coordinates with an AI agent via file-based IPC (`C:/tmp/`) to answer and submit them. This repo is also a Claude Code Skill installed to `~/.claude/skills/huixuewaiyu-readingpart/`.

## Commands

```bash
# Install (also copies skill files to ~/.claude/skills/)
bash install.sh                          # Linux/macOS/Git Bash
powershell -File install.ps1             # Windows PowerShell

# Run
python scripts/elang_reader.py batch-all            # All 11 categories (~291 articles)
python scripts/elang_reader.py batch-all 3          # Resume from category 3
python scripts/elang_reader.py batch "<learn-url>"  # Single category
python scripts/elang_reader.py solve "<praxis-url>" # Single article

# Dependencies
pip install -r requirements.txt
playwright install chromium
```

The script requires a `.env` file with `CAS_USERNAME` and `CAS_PASSWORD` (ZJU CAS credentials). If missing, it prompts interactively on first run.

## Architecture

### One Python file, three modes

`scripts/elang_reader.py` (~1000 lines) is the entire automation script. No other Python modules. It uses `asyncio` + Playwright's async API throughout.

Three CLI entry points map to three async functions:
- `mode_solve(url)` — single article
- `mode_batch(learn_url)` — single category
- `mode_batch_all(start_cat)` — all 11 categories with checkpoint/resume

### File IPC protocol (the core integration point)

The script and AI communicate via JSON files in `C:/tmp/` (hardcoded — not portable to non-Windows):

| File | Writer | Purpose |
|------|--------|---------|
| `C:/tmp/elang_current.json` | Script | Current article content + `status: "waiting_for_ai"` |
| `C:/tmp/elang_signal.json` | AI | Answers (`status: "answers_ready"`) or commands (`skip`, `continue`, `stop`) |
| `C:/tmp/elang_checkpoint.json` | Script | Resume state: `completed_categories[]`, `total_submitted` |

**Flow per article:**
1. Script writes `elang_current.json` with passage text, questions array, options
2. Script polls for `elang_signal.json` (up to `AI_TIMEOUT=120s`)
3. AI reads `elang_current.json`, answers, writes `elang_signal.json` with `[[qIdx, optIdx], ...]`
4. Script calls Vue methods to submit, then moves to next article

Signal status values: `answers_ready` (with `answers` array), `skip` (skip and submit empty), `continue` (at 50-article checkpoint), `stop` (save progress and exit).

### Vue component method calls (how answers are submitted)

The elang site is a Vue SPA. The script doesn't click DOM elements to answer — it traverses the Vue component tree from `document.querySelector('#app').__vue__` to find components with `check_answer(qIdx, optIdx)` and `to_submit()` methods, then calls them directly via `page.evaluate()`. This is the key insight that makes the automation reliable.

### Article list extraction (dual strategy)

1. **Vue data first**: Recursively walks `$children` to find `$data.listData` (or `articles`/`items`/`resources`/`records`) — gives completion status via `status === 2`
2. **Text fallback**: Parses `document.body.innerText`, filtering out date patterns and Chinese UI words, detects "..." prefix as completion marker

### CAPTCHA handling

After ~10 consecutive articles, a 4-digit numeric CAPTCHA appears in a `.Verify-box` popup. The `_captcha_seen` global flag tracks this — once seen, the script proactively checks on every subsequent article entry. Solved via `ddddocr` OCR with a manual fallback (waits up to 300s for user to solve).

### Checkpoint/resume

After each category completes, `elang_checkpoint.json` is updated with `completed_categories` (category IDs) and `total_submitted` count. Every 50 articles (`CHECKPOINT_INTERVAL`), the script pauses and waits for the AI to write `{"status": "continue"}` or `{"status": "stop"}` to the signal file. Delete the checkpoint file to start fresh.

### Navigation quirk

Due to CAS redirect behavior, navigating to a learn URL may first land on `/#/home`. The script detects this and retries the navigation (second `page.goto` call lands correctly). This is handled in `mode_batch_all` lines 820-830.

## Key constants (tunables in `elang_reader.py`)

- `AI_TIMEOUT = 120` — seconds to wait for AI per article
- `CHECKPOINT_INTERVAL = 50` — pause every N articles
- `CAPTCHA_TIMEOUT = 300` — seconds for manual captcha fallback
- `BACK_RETRIES = 8`, `CAT_LOAD_RETRIES = 12` — navigation robustness

## Auto-skip conditions

Articles are skipped when: already completed (Vue status or text marker), no questions found in DOM, questions have no clickable options (fill-in-blank type), or navigation fails to produce a valid URL with `log_id`/`resources_id`.

## Requirements

- Python 3.8+, Edge browser (Playwright uses `channel="msedge"`)
- `playwright`, `python-dotenv`, `ddddocr`, `Pillow`
- ZJU CAS account with access to elang.zju.edu.cn
