#!/usr/bin/env python3
"""
HuixueWaiyu Reading Part - Fully Automated Solver
==================================================
Extracts passage + questions from elang.zju.edu.cn, coordinates with AI
(via file IPC) to answer, then submits via Vue component method calls.

Usage:
  python elang_reader.py batch-all                 # All 11 categories
  python elang_reader.py batch <learn-url>         # Single category
  python elang_reader.py solve <praxis-url>        # Single article

Architecture:
  1. Opens Edge (user logs in once via CAS)
  2. Navigates category learn pages, extracts article list
  3. For each uncompleted article:
     a. Clicks article -> waits for praxis page
     b. Extracts passage + questions via DOM
     c. Writes to /tmp/elang_current.json (status: waiting_for_ai)
     d. Polls /tmp/elang_signal.json for AI answers
     e. Calls Vue.check_answer() + Vue.to_submit()
     f. Returns to learn page
  4. Saves checkpoint to /tmp/elang_checkpoint.json each category
  5. Pauses every 50 articles for user confirmation
"""

import asyncio
import json
import sys
import os
import re
import time
from pathlib import Path
from playwright.async_api import async_playwright

# ---- File paths ----
SCRATCH_DIR = "/tmp/elang_screenshots"
CURRENT_FILE = "/tmp/elang_current.json"
SIGNAL_FILE = "/tmp/elang_signal.json"
CHECKPOINT_FILE = "/tmp/elang_checkpoint.json"

# ---- Tuning constants ----
CHECKPOINT_INTERVAL = 50   # Pause every N articles for user confirmation
AI_TIMEOUT = 120           # Max seconds to wait for AI answers per article
CAPTCHA_TIMEOUT = 300      # Max seconds to wait for manual CAPTCHA
NAV_LOAD_WAIT = 1.5        # Seconds to wait after page navigation
BACK_LOAD_WAIT = 0.8       # Seconds between back-navigation retries
BACK_RETRIES = 8           # Max retries for back navigation
CAT_LOAD_RETRIES = 12      # Max retries for category page load


# ============================================================
# Navigation
# ============================================================

async def navigate_to(page, url):
    """Navigate to URL, handle CAS login, wait for SPA to render."""
    print(f"[elang] Navigate: {url}")
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)

    if "elang.zju.edu.cn" not in page.url:
        print("[elang] Waiting for CAS login (up to 120s)...")
        try:
            await page.wait_for_url("**elang.zju.edu.cn**", timeout=120000)
            print("[elang] Logged in!")
        except:
            print("[elang] WARNING: Login timeout, proceeding anyway")

    await page.wait_for_timeout(int(NAV_LOAD_WAIT * 1000))

    if "#" in url:
        await page.evaluate(f"window.location.hash = '{url.split('#', 1)[1]}'")
    else:
        await page.goto(url, wait_until="networkidle", timeout=30000)

    try:
        await page.wait_for_selector(
            ".praxis-item, .listen-item, .van-nav-bar", timeout=15000
        )
    except:
        await page.wait_for_timeout(2000)

    print(f"[elang] URL: {page.url}")
    return True


async def go_back_to_learn(page, learn_hash):
    """Navigate back to a category learn page via hash routing."""
    await page.evaluate(f"window.location.hash = '{learn_hash}'")
    for _ in range(BACK_RETRIES):
        await page.wait_for_timeout(int(BACK_LOAD_WAIT * 1000))
        text = await page.evaluate("() => document.body.innerText")
        if "..." not in text and len(text.split("\n")) > 10:
            break


# ============================================================
# Content extraction
# ============================================================

async def extract_page_content(page):
    """Extract passage text and question/options from the praxis page."""
    return await page.evaluate("""() => {
        const items = document.querySelectorAll('.praxis-item');
        const questions = [];
        items.forEach((item, idx) => {
            const title = item.querySelector('.praxis-title')?.innerText?.trim() || '';
            const desc = item.querySelector('.praxis-desc')?.innerText?.trim() || '';
            const answerDivs = item.querySelectorAll('.answer');
            const options = [];
            answerDivs.forEach(ans => {
                const label = ans.querySelector('.answer-title')?.innerText?.trim() || '';
                const text = ans.querySelector('.answer-desc')?.innerText?.trim() || '';
                if (label && label.length === 1) {
                    options.push({label: label, text: text});
                }
            });
            if (desc || options.length > 0) {
                questions.push({index: idx, title, question: desc, options});
            }
        });

        let passage = '';
        const bodyText = document.body.innerText || '';
        const parts = bodyText.split(/\\u67e5\\u770b\\u539f\\u6587|\\u539f\\u6587/);
        if (parts.length > 1) passage = parts[parts.length - 1].trim();
        if (!passage || passage.length < 50) {
            const wrapTexts = document.querySelectorAll('.wrap-text');
            wrapTexts.forEach(wt => {
                const text = wt.innerText || '';
                if (text.length > 200 && !text.startsWith('Directions')) passage = text;
            });
        }

        return {
            questions, passage,
            title: document.querySelector('.van-nav-bar__title')?.innerText?.trim() || ''
        };
    }""")


async def get_article_list(page):
    """
    Extract article names from the current learn page.
    Returns list of {name, isCompleted}.
    Tries Vue data first (has completion status), falls back to text parsing.
    """
    # Strategy 1: Vue component data (has completion status)
    articles = await page.evaluate("""() => {
        function findListData(vm, depth) {
            if (!vm || depth > 12) return null;
            const data = vm.$data || {};
            if (data.listData && Array.isArray(data.listData)
                && data.listData.length > 0 && data.listData[0].name) {
                return data.listData;
            }
            // Also try common Vue data property names
            for (const key of ['articles', 'items', 'resources', 'records']) {
                if (data[key] && Array.isArray(data[key])
                    && data[key].length > 0 && data[key][0].name) {
                    return data[key];
                }
            }
            if (vm.$children) {
                for (const child of vm.$children) {
                    const r = findListData(child, depth + 1);
                    if (r) return r;
                }
            }
            return null;
        }
        const raw = findListData(document.querySelector('#app').__vue__, 0);
        if (!raw) return [];
        return raw.map(item => ({
            name: item.name || item.title || '',
            isCompleted: (item.status === 2 || item.learnStatus === '\\u5df2\\u5b66'
                          || item.isFinished === true || item.statusDesc === '\\u5df2\\u5b66')
        }));
    }""")

    if articles and len(articles) > 0:
        completed = sum(1 for a in articles if a.get("isCompleted"))
        print(f"[elang] Vue: {len(articles)} articles ({completed} done)")
        return articles

    # Strategy 2: Text-based extraction with completion detection
    print("[elang] Vue data empty, falling back to text extraction...")
    text = await page.evaluate("() => document.body.innerText")
    lines = text.split("\n")
    articles = []
    date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    skip_words = {"已学", "未学", "学习中", "返回", "慧学外语", "我的阅读",
                  "问题反馈", "...", "[阅读]", "筛选"}

    for i, line in enumerate(lines):
        line = line.strip()
        if not line or len(line) < 5 or len(line) > 150:
            continue
        if date_pattern.match(line):
            continue
        if line in skip_words or any(k in line for k in skip_words):
            continue
        if not (line[0].isascii() and line[0].isalpha()):
            continue
        # Check if previous non-empty line indicates completion
        prev = lines[i - 1].strip() if i > 0 else ""
        is_done = prev == "..."
        articles.append({"name": line, "isCompleted": is_done})

    completed = sum(1 for a in articles if a.get("isCompleted"))
    print(f"[elang] Text: {len(articles)} articles ({completed} done)")
    return articles


async def click_article(page, name):
    """Click an article by title text. Returns (log_id, resources_id, url)."""
    await page.evaluate("""(targetName) => {
        const all = document.querySelectorAll('div');
        for (const d of all) {
            if (d.innerText?.trim() === targetName && d.children.length === 0) {
                d.parentElement.click();
                return;
            }
        }
    }""", name)
    await page.wait_for_timeout(1500)
    u = page.url
    log_id = u.split("log_id=")[1].split("&")[0] if "log_id=" in u else ""
    rid = u.split("resources_id=")[1].split("&")[0] if "resources_id=" in u else ""
    return log_id, rid, u


# ============================================================
# Answer submission
# ============================================================

async def set_answers(page, answers):
    """Select answers via Vue check_answer(qIdx, optIdx)."""
    for q_idx, opt_idx in answers:
        result = await page.evaluate("""([qIdx, oIdx]) => {
            function findVm(vm, d, method) {
                if (!vm || d > 10) return null;
                if (vm.$options && vm.$options.methods
                    && vm.$options.methods[method]) return vm;
                if (vm.$children) {
                    for (const c of vm.$children) {
                        const r = findVm(c, d + 1, method);
                        if (r) return r;
                    }
                }
                return null;
            }
            const vm = findVm(document.querySelector('#app').__vue__, 0, 'check_answer');
            if (vm) { vm.check_answer(qIdx, oIdx); return 'OK'; }
            return 'no vm';
        }""", [q_idx, opt_idx])
        print(f"  Q{q_idx+1}: opt {opt_idx} -> {result}")
        await page.wait_for_timeout(80)


async def submit(page):
    """Submit all answers via Vue to_submit()."""
    result = await page.evaluate("""() => {
        function findVm(vm, d, method) {
            if (!vm || d > 10) return null;
            if (vm.$options && vm.$options.methods
                && vm.$options.methods[method]) return vm;
            if (vm.$children) {
                for (const c of vm.$children) {
                    const r = findVm(c, d + 1, method);
                    if (r) return r;
                }
            }
            return null;
        }
        const vm = findVm(document.querySelector('#app').__vue__, 0, 'to_submit');
        if (vm) { vm.to_submit(); return 'OK'; }
        return 'no vm';
    }""")
    print(f"[elang] Submit: {result}")
    return result


# ============================================================
# AI answer coordination (file IPC)
# ============================================================

async def wait_for_ai(timeout=AI_TIMEOUT):
    """Wait for AI to write SIGNAL_FILE. Returns data dict or None."""
    if os.path.exists(SIGNAL_FILE):
        os.remove(SIGNAL_FILE)

    waited = 0
    while waited < timeout:
        await asyncio.sleep(1)
        waited += 1
        if os.path.exists(SIGNAL_FILE):
            try:
                with open(SIGNAL_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                status = data.get("status", "")
                # Accept: answers_ready (with any answers, even empty), skip, continue, stop
                if status in ("answers_ready", "skip", "continue", "stop"):
                    return data
            except (json.JSONDecodeError, IOError):
                pass
    return None


async def request_ai_answers(article_data):
    """Write current article to CURRENT_FILE for AI to read."""
    with open(CURRENT_FILE, "w", encoding="utf-8") as f:
        json.dump(article_data, f, ensure_ascii=False, indent=2)
    if os.path.exists(SIGNAL_FILE):
        os.remove(SIGNAL_FILE)
    print(f"[elang] Waiting for AI answers... (timeout={AI_TIMEOUT}s)")
    return await wait_for_ai()


# ============================================================
# CAPTCHA handling
# ============================================================

CAPTCHA_KEYWORDS = ["...", "captcha", "...", "...", "verification", "..."]

async def detect_captcha(page):
    """Check whether the page is showing a CAPTCHA."""
    try:
        body = await page.evaluate("() => document.body.innerText.substring(0, 500)")
        for kw in CAPTCHA_KEYWORDS:
            if kw.lower() in body.lower():
                return True
    except:
        pass
    return False


async def wait_for_captcha(page, timeout=CAPTCHA_TIMEOUT):
    """Block until the user solves the CAPTCHA manually."""
    print("[elang] !! CAPTCHA detected! Please solve it in the browser...")
    print(f"[elang] Waiting up to {timeout}s...")
    waited = 0
    while waited < timeout:
        await asyncio.sleep(3)
        waited += 3
        if not await detect_captcha(page):
            print("[elang] [OK] CAPTCHA resolved!")
            return True
        if waited % 30 == 0:
            print(f"[elang] Still waiting... ({waited}s)")
    print("[elang] CAPTCHA wait timeout.")
    return False


# ============================================================
# Article processor (per category)
# ============================================================

async def process_articles(page, article_infos, start_counter, learn_hash):
    """Process all uncompleted articles in a category. Returns result list."""
    results = []
    total = len(article_infos)
    done_already = sum(1 for a in article_infos if a.get("isCompleted"))
    print(f"[elang] {done_already}/{total} already completed - will skip")

    for i, info in enumerate(article_infos):
        name = info["name"]
        article_num = start_counter + i + 1

        if info.get("isCompleted"):
            print(f"[{article_num}] {i+1}/{total}: {name} - SKIP (done)")
            results.append({"name": name, "status": "skipped_completed"})
            continue

        print(f"\n{'='*50}")
        print(f"[{article_num}] {i+1}/{total}: {name}")
        print(f"{'='*50}")

        # Navigate to article
        log_id, resources_id, praxis_url = await click_article(page, name)
        if not log_id or not resources_id:
            print(f"  SKIP: no URL generated")
            results.append({"name": name, "status": "no_url"})
            continue

        # Wait for praxis page to render
        try:
            await page.wait_for_selector(".praxis-item", timeout=10000)
        except:
            await page.wait_for_timeout(2000)
        await page.wait_for_timeout(800)

        # CAPTCHA check
        if await detect_captcha(page):
            await wait_for_captcha(page)
            await page.wait_for_timeout(500)

        # Extract content
        content = await extract_page_content(page)

        if not content["questions"]:
            print(f"  SKIP: no questions found")
            await go_back_to_learn(page, learn_hash)
            results.append({"name": name, "status": "no_questions"})
            continue

        # Auto-skip articles whose questions have no clickable options
        has_options = any(len(q.get("options", [])) > 0 for q in content["questions"])
        if not has_options:
            print(f"  SKIP: fill-in-blank type (no options) - submitting empty")
            await submit(page)
            await page.wait_for_timeout(1000)
            await go_back_to_learn(page, learn_hash)
            results.append({"name": name, "status": "skipped_no_options"})
            continue

        print(f"  Qs: {len(content['questions'])} | Passage: {len(content['passage'])} chars")

        # Save raw content for reference
        Path(SCRATCH_DIR).mkdir(parents=True, exist_ok=True)
        with open(os.path.join(SCRATCH_DIR, f"article_{article_num}.json"),
                  "w", encoding="utf-8") as f:
            json.dump(content, f, ensure_ascii=False, indent=2)

        # Request AI answers
        article_data = {
            "article_index": i,
            "article_name": name,
            "article_number": article_num,
            "total_remaining": total - i,
            "url": praxis_url,
            "title": content["title"],
            "passage": content["passage"][:5000],
            "questions": content["questions"],
            "answers": [],
            "status": "waiting_for_ai"
        }

        data = await request_ai_answers(article_data)

        if data and data.get("status") == "skip":
            print(f"  [SKIP] AI requested skip")
            await submit(page)
            await page.wait_for_timeout(1000)
            results.append({"name": name, "status": "submitted"})
            print(f"  [OK] Skipped!")

        elif data and data.get("status") == "answers_ready" and data.get("answers") is not None:
            await set_answers(page, data["answers"])
            await page.wait_for_timeout(200)

            if await detect_captcha(page):
                await wait_for_captcha(page)

            await submit(page)
            await page.wait_for_timeout(1000)
            results.append({"name": name, "status": "submitted"})
            print(f"  [OK] Submitted!")

        else:
            results.append({"name": name, "status": "timeout"})
            print(f"  [FAIL] AI timeout, skipping...")

        await go_back_to_learn(page, learn_hash)

    return results


def print_summary(results):
    s = sum(1 for r in results if r["status"] == "submitted")
    k = sum(1 for r in results if r["status"] == "skipped_completed")
    f = len(results) - s - k
    print(f"\n[elang] Done: {s} submitted, {k} skipped, {f} failed")


# ============================================================
# Batch ALL categories
# ============================================================

async def mode_batch_all(start_cat=0):
    """Process all 11 reading categories. Resumable via checkpoint."""
    Path(SCRATCH_DIR).mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="msedge", headless=False)
        page = await browser.new_page()

        # Navigate to reading index
        await navigate_to(page, "https://elang.zju.edu.cn/#/read/index")

        # Wait for category list to load
        print("[elang] Loading categories...")
        for _ in range(CAT_LOAD_RETRIES):
            await page.wait_for_timeout(800)
            text = await page.evaluate("() => document.body.innerText")
            if "..." not in text and len(text.split("\n")) > 5:
                break

        # Extract categories from Vue data
        categories = await page.evaluate("""() => {
            function findArray(vm, depth) {
                if (!vm || depth > 10) return [];
                if (vm.$data && vm.$data.listData && Array.isArray(vm.$data.listData)
                    && vm.$data.listData.length >= 3 && vm.$data.listData[0].name) {
                    return vm.$data.listData.map(item => ({
                        id: item.id, name: item.name
                    }));
                }
                if (vm.$children) {
                    for (const child of vm.$children) {
                        const r = findArray(child, depth + 1);
                        if (r.length > 0) return r;
                    }
                }
                return [];
            }
            return findArray(document.querySelector('#app').__vue__, 0);
        }""")

        if not categories:
            print("[elang] ERROR: No categories found!")
            await browser.close()
            return

        # Deduplicate
        seen = set()
        unique = []
        for c in categories:
            if c["name"] not in seen:
                seen.add(c["name"])
                unique.append(c)
        categories = unique

        print(f"\n{'='*60}")
        print(f"BATCH-ALL: {len(categories)} categories")
        print(f"{'='*60}")
        for c in categories:
            print(f"  [id={c['id']}] {c['name']}")
        print(f"{'='*60}")

        # Restore checkpoint
        checkpoint = {}
        if os.path.exists(CHECKPOINT_FILE):
            with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                checkpoint = json.load(f)
            print(f"\n[elang] Resuming: {checkpoint.get('total_submitted', 0)} done, "
                  f"{len(checkpoint.get('completed_categories', []))} categories complete")

        total_submitted = checkpoint.get("total_submitted", 0)
        article_counter = total_submitted

        for cat_idx, cat in enumerate(categories):
            cat_id = cat["id"]
            cat_name = cat["name"]

            if cat_idx < start_cat:
                print(f"\n[elang] Skip [{cat_idx+1}]: {cat_name}")
                continue

            completed_cats = checkpoint.get("completed_categories", [])
            if cat_id in completed_cats:
                print(f"\n[elang] Skip completed category: {cat_name}")
                continue

            print(f"\n{'='*60}")
            print(f"CATEGORY [{cat_idx+1}/{len(categories)}]: {cat_name} (id={cat_id})")
            print(f"{'='*60}")

            # Navigate to category learn page
            await page.evaluate(
                f"window.location.hash = '/read/learn?subject_id={cat_id}'"
            )
            for _ in range(CAT_LOAD_RETRIES):
                await page.wait_for_timeout(800)
                text = await page.evaluate("() => document.body.innerText")
                if "..." not in text and len(text.split("\n")) > 10:
                    break

            article_infos = await get_article_list(page)
            print(f"[elang] {len(article_infos)} articles found")

            if not article_infos:
                print("[elang] No articles - marking category complete")
                completed_cats.append(cat_id)
                checkpoint["completed_categories"] = completed_cats
                with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
                    json.dump(checkpoint, f, ensure_ascii=False, indent=2)
                continue

            learn_hash = f"/read/learn?subject_id={cat_id}"
            results = await process_articles(
                page, article_infos, article_counter, learn_hash
            )

            for r in results:
                if r["status"] == "submitted":
                    article_counter += 1
                    total_submitted += 1

            # Mark category complete
            completed_cats.append(cat_id)
            checkpoint["completed_categories"] = completed_cats
            checkpoint["total_submitted"] = total_submitted
            with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
                json.dump(checkpoint, f, ensure_ascii=False, indent=2)

            print_summary(results)

            # 50-article user confirmation checkpoint
            if article_counter > 0 and article_counter % CHECKPOINT_INTERVAL == 0:
                print(f"\n{'='*60}")
                print(f"CHECKPOINT: {total_submitted} articles submitted.")
                print(f"Continue? Write to {SIGNAL_FILE}:")
                print(f'  {{"status": "continue"}}  or  {{"status": "stop"}}')
                print(f"{'='*60}")

                cp_data = {
                    "status": "checkpoint",
                    "total_submitted": total_submitted
                }
                with open(CURRENT_FILE, "w", encoding="utf-8") as f:
                    json.dump(cp_data, f, ensure_ascii=False)
                if os.path.exists(SIGNAL_FILE):
                    os.remove(SIGNAL_FILE)

                data = await wait_for_ai(timeout=3600)
                if data and data.get("status") == "stop":
                    print("[elang] Stopped. Progress saved.")
                    await browser.close()
                    return
                print("[elang] Continuing...")

        print(f"\n[elang] ALL DONE! {total_submitted} submitted across "
              f"{len(categories)} categories.")
        await asyncio.sleep(10)
        await browser.close()


# ============================================================
# Single-article solve mode
# ============================================================

async def mode_solve(url):
    """Process a single article: extract, wait for AI, submit."""
    Path(SCRATCH_DIR).mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="msedge", headless=False)
        page = await browser.new_page()
        await navigate_to(page, url)

        content = await extract_page_content(page)

        print(f"\n{'='*60}")
        print(f"TITLE: {content['title']}")
        print(f"{'='*60}")
        print(f"\n--- PASSAGE ---\n{content['passage'][:3000]}")
        print(f"\n--- QUESTIONS ({len(content['questions'])}) ---")
        for q in content["questions"]:
            print(f"\n{q['title']}: {q['question']}")
            for opt in q["options"]:
                print(f"  {opt['label']}. {opt['text']}")
        print("=" * 60)

        article_data = {
            "article_index": 0,
            "article_name": content["title"],
            "article_number": 1,
            "url": url,
            "title": content["title"],
            "passage": content["passage"][:5000],
            "questions": content["questions"],
            "answers": [],
            "status": "waiting_for_ai"
        }

        data = await request_ai_answers(article_data)
        if not data or data.get("status") not in ("answers_ready", "skip"):
            print("[elang] Timeout.")
            await browser.close()
            return

        if data.get("status") == "answers_ready" and data.get("answers") is not None:
            await set_answers(page, data["answers"])
        await page.wait_for_timeout(500)
        await submit(page)
        await page.wait_for_timeout(3000)

        print(f"\n[elang] Done!")
        await asyncio.sleep(10)
        await browser.close()


# ============================================================
# Single-category batch mode
# ============================================================

async def mode_batch(learn_url):
    """Process all articles in a single category."""
    Path(SCRATCH_DIR).mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="msedge", headless=False)
        page = await browser.new_page()
        await navigate_to(page, learn_url)
        learn_hash = learn_url.split("#", 1)[1] if "#" in learn_url else ""

        for _ in range(CAT_LOAD_RETRIES):
            await page.wait_for_timeout(800)
            text = await page.evaluate("() => document.body.innerText")
            if "..." not in text and len(text.split("\n")) > 10:
                break

        article_infos = await get_article_list(page)
        print(f"\n[elang] {len(article_infos)} articles")

        results = await process_articles(page, article_infos, 0, learn_hash)
        print_summary(results)
        await asyncio.sleep(10)
        await browser.close()


# ============================================================
# CLI entry point
# ============================================================

def main():
    if len(sys.argv) < 2:
        print("HuixueWaiyu Reading Part - Auto Solver")
        print("  solve <praxis-url>            Single article")
        print("  batch <learn-url>             One category (all articles)")
        print("  batch-all [start-category]    ALL 11 categories")
        sys.exit(1)

    mode = sys.argv[1]

    if mode == "solve":
        url = sys.argv[2] if len(sys.argv) > 2 else input("Praxis URL: ")
        asyncio.run(mode_solve(url))
    elif mode == "batch":
        url = sys.argv[2] if len(sys.argv) > 2 else input("Learn URL: ")
        asyncio.run(mode_batch(url))
    elif mode == "batch-all":
        start_cat = int(sys.argv[2]) - 1 if len(sys.argv) > 2 else 0
        asyncio.run(mode_batch_all(start_cat))
    else:
        print(f"Unknown mode: {mode}")
        sys.exit(1)


if __name__ == "__main__":
    main()
