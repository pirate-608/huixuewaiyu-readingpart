---
name: huixuewaiyu-readingpart
description: Automate English reading exercises on 慧学外语 (elang.zju.edu.cn). Use this skill whenever the user wants to complete reading comprehension questions on elang.zju.edu.cn, mentions "慧学外语", "elang", "英文阅读", or needs help with ZJU English reading homework. Triggers on URLs containing elang.zju.edu.cn, mentions of 慧学外语阅读, or requests to batch-complete reading exercises.
---

# 慧学外语阅读自动答题

Automates English reading exercises on elang.zju.edu.cn via Playwright + Vue component method calls.

## Mode detection — read this first

This skill has two distinct modes. **Determine which mode applies before doing anything else:**

| Condition | Mode | Your role |
|-----------|------|-----------|
| User asks to **start** / **run** / **launch** / **刷题** / **开始**, or provides a learn/praxis URL without JSON context | **Mode 1: Orchestrator** | Run the Python script via Bash. The script will drive the browser and write `C:/tmp/elang_current.json` when it needs answers. |
| `C:/tmp/elang_current.json` exists and contains `"status": "waiting_for_ai"` — or — the user explicitly pastes article content and asks you to answer | **Mode 2: Backend processor** | Read the JSON, answer the questions, and produce the `C:/tmp/elang_signal.json` payload. Do NOT run the Python script. |

**If you are unsure**, ask the user: "Are you starting a new automation run, or continuing an already-running script that needs answers?"

---

## Mode 1: Orchestrator (start the automation)

### Quick Start

```bash
# Install
bash install.sh        # macOS / Linux / Git Bash
powershell -File install.ps1   # Windows PowerShell

# Run
python scripts/elang_reader.py batch-all
```

### Commands

```bash
# ALL 11 categories (~291 articles), resumable via checkpoint
python scripts/elang_reader.py batch-all

# Single category
python scripts/elang_reader.py batch "https://elang.zju.edu.cn/#/read/learn?subject_id=14"

# Single article
python scripts/elang_reader.py solve "<praxis-url>"
```

Categories: 道路与交通(3), 历史与文化(22), 文学与艺术(12), 职业与发展(18), 运动与娱乐(6), 学习与教育(59), 商业与经济(26), 科技与创新(38), 社会与政治(36), 自然与农业(22), 家庭与生活(49) — ~291 articles total.

### What happens

1. Opens Edge browser — auto-fills ZJU CAS login (credentials from `.env`)
2. Navigates category pages, extracts article lists (Vue data + text fallback)
3. For each uncompleted article: clicks in, extracts passage + questions via DOM
4. Writes content to `C:/tmp/elang_current.json` → **the script now pauses and waits**
5. At this point, you (the AI) switch to **Mode 2** to read and answer
6. Script calls Vue `check_answer(qIdx, optIdx)` + `to_submit()` to submit
7. Returns to learn page, continues; saves checkpoint after each category
8. CAPTCHA auto-solved via ddddocr (4-digit numeric)
9. **Every 50 articles**: pauses for user confirmation — write `{"status": "continue"}` or `{"status": "stop"}`

### Configuration (.env)

Copy `.env.example` to `.env` and fill credentials:

```
CAS_USERNAME=你的学号
CAS_PASSWORD=你的密码
```

These are stored locally and never transmitted.

### Resume

Delete `C:/tmp/elang_checkpoint.json` to start fresh. Categories in `completed_categories` are skipped on re-run.

---

## Mode 2: Backend processor (answer questions)

**Only enter this mode when `C:/tmp/elang_current.json` exists with `"status": "waiting_for_ai"`, or the user explicitly asks you to answer article questions.**

### Step 1: Read the article

```bash
cat /tmp/elang_current.json   # Linux/macOS
type C:\tmp\elang_current.json  # Windows
```

The JSON contains:
- `passage` — the reading passage text
- `questions` — array of `{index, title, question, options: [{label, text}]}`
- `article_name`, `article_number` — metadata

### Step 2: Answer and write signal

Write your answers to `C:/tmp/elang_signal.json`:

If you have file-writing tools, write the JSON there. Otherwise, output only the JSON payload in a code block so the user can copy it into that file.

```json
// Submit answers as [question_index, option_index] tuples (0=A, 1=B, 2=C, 3=D, 4=E; for True/False, 0=True, 1=False). If the format cannot be mapped, use {"status": "skip"}.
{"status": "answers_ready", "answers": [[0, 0], [1, 2], [2, 1], [3, 3], [4, 0]]}

// Skip article (fill-in-blank, broken, etc.)
{"status": "skip"}

// Checkpoint confirmation (every 50 articles)
{"status": "continue"}

// Stop after current category
{"status": "stop"}
```

Each answer entry is `[qIdx, optIdx]` where `qIdx` is the 0-based question index and `optIdx` is the 0-based option index (0=A, 1=B, 2=C, 3=D, 4=E). For True/False, use 0=True and 1=False. If a question type cannot be mapped cleanly to this scheme, return `{"status": "skip"}`.

### After writing the signal file

```bash
# Use absolute paths — the Python script is polling for this file:
Write("C:/tmp/elang_signal.json", <json>)
```

The script polls every 1 second and will pick up the file within 2 seconds.

### Answering strategy

- Read the passage carefully, then answer each question based on the passage content
- Return answers for ALL questions in the article
- If the passage or questions are unreadable/broken, use `{"status": "skip"}`
- If you cannot determine an answer with enough confidence because the context is missing or the formatting is unclear, use `{"status": "skip"}`
- Do NOT run the Python script in this mode — the script is already running and waiting

---

## IPC file protocol reference

| File | Writer | Purpose |
|------|--------|---------|
| `C:/tmp/elang_current.json` | Script | Current article: passage, questions, `status: "waiting_for_ai"` |
| `C:/tmp/elang_signal.json` | AI | Answers or commands: `status + answers[]` |
| `C:/tmp/elang_checkpoint.json` | Script | Resume state: completed_categories[], total_submitted |

## Auto-skipped articles (by the script)

- Already completed (Vue `status === 2` or text `已学`)
- No questions or unrecognised question format — submits empty
- Navigation failure (no log_id / resources_id)

## CAPTCHA

Auto-solved via ddddocr OCR. Captcha is 4-digit numeric, shown in a `.Verify-box` popup after ~10 consecutive articles. Falls back to manual solve if OCR fails. Once captcha appears, proactively checks on every subsequent article entry.

## Requirements

- Python 3.8+, Playwright, python-dotenv, ddddocr, Pillow
- Edge browser (auto-detected by Playwright)
- `pip install -r requirements.txt && playwright install chromium`
