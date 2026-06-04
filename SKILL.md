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

### Commands

The skill has its own venv at `~/.claude/skills/huixuewaiyu-readingpart/.venv/`. Always use the venv Python — your global/conda environment is irrelevant.

**Before running**, verify the venv exists. If it doesn't, the skill hasn't been installed yet — tell the user to run `install.sh` or `install.ps1` first.

```bash
# Bash (Git Bash / Linux / macOS)
SKILL_DIR="$HOME/.claude/skills/huixuewaiyu-readingpart"
# Auto-detect venv layout (Windows = Scripts/, Unix = bin/)
if [ -f "$SKILL_DIR/.venv/Scripts/python" ]; then
    SKILL_PYTHON="$SKILL_DIR/.venv/Scripts/python"
elif [ -f "$SKILL_DIR/.venv/bin/python" ]; then
    SKILL_PYTHON="$SKILL_DIR/.venv/bin/python"
else
    echo "ERROR: venv not found. Run install.sh first." && exit 1
fi

# ALL 11 categories (~291 articles), resumable via checkpoint
$SKILL_PYTHON $SKILL_DIR/scripts/elang_reader.py batch-all

# Single category
$SKILL_PYTHON $SKILL_DIR/scripts/elang_reader.py batch "https://elang.zju.edu.cn/#/read/learn?subject_id=14"

# Single article
$SKILL_PYTHON $SKILL_DIR/scripts/elang_reader.py solve "<praxis-url>"
```

```powershell
# PowerShell
$SKILL_DIR = "$env:USERPROFILE\.claude\skills\huixuewaiyu-readingpart"
$SKILL_PYTHON = "$SKILL_DIR\.venv\Scripts\python.exe"
if (-not (Test-Path $SKILL_PYTHON)) {
    # MSYS2/Cygwin Python creates bin/ layout instead
    $SKILL_PYTHON = "$SKILL_DIR\.venv\bin\python.exe"
}
if (-not (Test-Path $SKILL_PYTHON)) {
    Write-Error "venv not found. Run install.ps1 first."; exit 1
}

& $SKILL_PYTHON $SKILL_DIR\scripts\elang_reader.py batch-all
& $SKILL_PYTHON $SKILL_DIR\scripts\elang_reader.py batch "https://elang.zju.edu.cn/#/read/learn?subject_id=14"
& $SKILL_PYTHON $SKILL_DIR\scripts\elang_reader.py solve "<praxis-url>"
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

Use the **Read tool** to read `C:/tmp/elang_current.json` — this is an absolute path, the Python script writes it there regardless of your working directory.

The JSON contains:
- `passage` — the reading passage text
- `questions` — array of `{index, title, question, options: [{label, text}]}`
- `article_name`, `article_number` — metadata

### Step 2: Answer and write signal

Use the **Write tool** to write your answer to `C:/tmp/elang_signal.json`:

```json
// Submit answers as [question_index, option_index] tuples
// (0=A, 1=B, 2=C, 3=D, 4=E; True/False: 0=True, 1=False)
{"status": "answers_ready", "answers": [[0, 0], [1, 2], [2, 1], [3, 3], [4, 0]]}

// Skip article (fill-in-blank, broken, unreadable)
{"status": "skip"}

// Checkpoint confirmation (every 50 articles)
{"status": "continue"}

// Stop after current category
{"status": "stop"}
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

- Python 3.8+
- Edge browser (Playwright uses `channel="msedge"`)
- ZJU CAS account with access to elang.zju.edu.cn
- Install via `install.sh` / `install.ps1` (creates an isolated venv with all dependencies)
