---
name: huixuewaiyu-readingpart
description: Automate English reading exercises on 慧学外语 (elang.zju.edu.cn). Use this skill whenever the user wants to complete reading comprehension questions on elang.zju.edu.cn, mentions "慧学外语", "elang", "英文阅读", or needs help with ZJU English reading homework. Triggers on URLs containing elang.zju.edu.cn, mentions of 慧学外语阅读, or requests to batch-complete reading exercises.
---

# 慧学外语阅读自动答题

Automates English reading exercises on elang.zju.edu.cn via Playwright + Vue component method calls.

## How it works

1. Opens Edge browser — user logs in once via ZJU CAS
2. Navigates category pages, extracts article lists (Vue data + text fallback)
3. For each uncompleted article: clicks in, extracts passage + questions via DOM
4. Writes content to `/tmp/elang_current.json` — AI reads, answers, writes `/tmp/elang_signal.json`
5. Script calls Vue `check_answer(qIdx, optIdx)` + `to_submit()` to submit
6. Returns to learn page, continues; saves checkpoint after each category
7. **Every 50 articles**: pauses for user confirmation

## Commands

```bash
# ALL 11 categories (~291 articles), resumable via checkpoint
python <skill-path>/scripts/elang_reader.py batch-all

# Single category
python <skill-path>/scripts/elang_reader.py batch "https://elang.zju.edu.cn/#/read/learn?subject_id=14"

# Single article
python <skill-path>/scripts/elang_reader.py solve "<praxis-url>"
```

Categories: 道路与交通(3), 历史与文化(22), 文学与艺术(12), 职业与发展(18), 运动与娱乐(6), 学习与教育(59), 商业与经济(26), 科技与创新(38), 社会与政治(36), 自然与农业(22), 家庭与生活(49) — ~291 articles total.

## IPC file protocol (/tmp/)

| File | Writer | Purpose |
|------|--------|---------|
| `elang_current.json` | Script | Current article: passage, questions, `status: "waiting_for_ai"` |
| `elang_signal.json` | AI | Answers or commands: `status + answers[]` |
| `elang_checkpoint.json` | Script | Resume state: completed_categories[], total_submitted |

### AI writes to `/tmp/elang_signal.json`:

```json
// Submit answers (0=A, 1=B, 2=C, 3=D)
{"status": "answers_ready", "answers": [[0, 0], [1, 2], [2, 1], [3, 3], [4, 0]]}

// Skip article (fill-in-blank, broken, etc.)
{"status": "skip"}

// Checkpoint confirmation
{"status": "continue"}

// Stop after current category
{"status": "stop"}
```

## Auto-skipped articles

- Already completed (Vue `status === 2` or text `已学`)
- No questions or no clickable options (fill-in-blank type — submitted empty)
- Navigation failure (no log_id / resources_id)

## CAPTCHA

Script detects CAPTCHA and pauses. User solves manually in the browser. Script resumes automatically after CAPTCHA clears.

## Resume

Delete `/tmp/elang_checkpoint.json` to start fresh. Categories in `completed_categories` are skipped on re-run.

## Requirements

- Python 3.8+, Playwright (`pip install playwright`), Edge browser
- `playwright install chromium` for browser binaries
