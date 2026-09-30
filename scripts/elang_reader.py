#!/usr/bin/env python3
"""
HuixueWaiyu Reading Part - Fully Automated Solver (PC layout)
=============================================================
Extracts passage + questions from elang.zju.edu.cn, coordinates with an AI
(via file IPC) to answer, then submits through the app's own Vue methods.

Usage:
  python elang_reader.py batch-all [start]     # every subject on the read index
  python elang_reader.py batch <subject_id|learn-url>
  python elang_reader.py solve <praxis-url>
  python elang_reader.py captcha-solve         # inspect a pending captcha request

Flags:
  --dry-run    do everything except the final confirmSubmit() (nothing posted)

Environment:
  ELANG_TMP_DIR   override the IPC directory (default C:/tmp)
  ELANG_BROWSER   chromium | msedge | chrome (default msedge)

Architecture (当前 PC 版; see MIGRATION_CHECKPOINT.md):
  1. Opens Edge; replays a saved session (cookies + localStorage) so CAS is
     usually skipped entirely. Falls back to CAS login if the session is stale.
  2. Read index -> subject list (`PcReadIndex.$data.listData`)
  3. Learn page -> article list (`PcReadLearn.$data.resourceList`), completion
     from the app's own `normalizeStatus` (status===2, or hisLabel===1)
  4. Per article: `toPraxis(item)` mints the server-side log_id and routes to
     `#/pc/read/praxis?log_id=..&resources_id=..`
  5. Questions come from `PcReadPraxis.$data.jobList` (populated only AFTER the
     captcha is passed, so a captcha gate is detected and solved here)
  6. Writes <ipc>/elang_current.json (status: waiting_for_ai) and polls
     <ipc>/elang_signal.json for answers
  7. Answers via `selectOption(qIdx, optIdx)` / `insertWordAnswers`, then the
     two-step submit: `openSubmitConfirm()` + `confirmSubmit()`
  8. Checkpoint saved per category; pauses every 50 articles for confirmation
"""

import asyncio
import base64
import json
import os
import re
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright

# Credentials come from `config.load_credentials()` (see _ensure_credentials), so
# python-dotenv is no longer imported here: the shared resolver reads .env itself
# and keeps a single, documented lookup rule for every entry point.

# `ddddocr` is imported lazily (see _get_ocr). It is a heavy ONNX dependency that
# is ONLY needed for the captcha OCR fallback, so requiring it at import time made
# the whole module unusable wherever it is absent — including simply importing the
# state machine. A missing ddddocr now degrades to the vision hand-off instead of
# breaking every entry point.
_ocr = None
_ocr_tried = False


def _get_ocr():
    """Return a cached ddddocr instance, or None when it is unavailable."""
    global _ocr, _ocr_tried
    if _ocr is not None:
        return _ocr
    if _ocr_tried:
        return None
    _ocr_tried = True
    try:
        import ddddocr
        _ocr = ddddocr.DdddOcr(show_ad=False)
    except Exception as e:
        print(f"[elang] ddddocr unavailable ({type(e).__name__}: {e}); "
              f"captchas will need the vision/manual hand-off")
        _ocr = None
    return _ocr

# ---- Platform-aware IPC paths ----
# On Windows, Python resolves "/tmp/" to "C:\tmp\". On Linux it stays "/tmp/".
# We make this explicit so paths are clear regardless of platform.
# ELANG_TMP_DIR overrides the location (useful for sandboxed/test runs that
# cannot write to C:\tmp, and for keeping artifacts inside a project dir).
import platform as _platform
_ipc_override = os.getenv("ELANG_TMP_DIR", "").strip()
if _ipc_override:
    _IPC_ROOT = Path(_ipc_override)
elif _platform.system() == "Windows":
    _IPC_ROOT = Path("C:/tmp")
else:
    _IPC_ROOT = Path("/tmp")

SCRATCH_DIR = str(_IPC_ROOT / "elang_screenshots")
CURRENT_FILE = str(_IPC_ROOT / "elang_current.json")
SIGNAL_FILE = str(_IPC_ROOT / "elang_signal.json")
CHECKPOINT_FILE = str(_IPC_ROOT / "elang_checkpoint.json")

# ---- Output buffering ----
# When stdout is not a TTY (e.g. run via Claude Code), Python buffers output.
# Force line-buffered mode so the AI can read progress in real time.
sys.stdout.reconfigure(line_buffering=True)

# ---- Load .env ----
# Look next to the script, in the cwd, and in the installed skill. The third
# location matters when running the repo copy during development: the
# credentials normally live with the installed skill.
_SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENV_LOADED = False

try:
    import config as _config  # noqa: E402  (same directory)
except Exception:
    _config = None


def _ensure_credentials(prompt_ok=True):
    """Resolve CAS credentials, prompting once if needed.

    Delegates to `config.load_credentials()`, which implements the single
    resolution rule shared by every entry point:

        $ELANG_ENV_FILE -> <cwd>/.env -> ~/.elang/.env
        and a real environment variable always beats the file.

    `./.env` is the workspace root because every agent runs commands with the
    workspace as its working directory — that is their shared contract, so no
    agent-specific detection is needed. A function (not import-time code) because
    this module is imported as a library by `elang_session`; exiting or prompting
    at import would break that.
    """
    global _ENV_LOADED, CAS_USERNAME, CAS_PASSWORD
    if _ENV_LOADED and CAS_USERNAME and CAS_PASSWORD:
        return True

    if _config is not None:
        info = _config.load_credentials()
        if info["ok"]:
            CAS_USERNAME, CAS_PASSWORD = info["username"], info["password"]
            _ENV_LOADED = True
            src = info["username_from"] or "?"
            print(f"[elang] credentials from {info['env_file']} ({src})")
            return True
        _env_path = Path(info["env_file"])
    else:
        _env_path = Path.cwd() / ".env"

    # Nothing usable. Never block a non-interactive run on input(): under an agent
    # there may be no stdin, where input() raises EOFError and the run dies.
    if not prompt_ok or not sys.stdin or not sys.stdin.isatty():
        print("ERROR: no CAS credentials found.")
        print(f"  Looked for: {_env_path}")
        print("  Create one with:  python scripts/init_env.py")
        print("  Or set ELANG_CAS_USERNAME / ELANG_CAS_PASSWORD in the environment.")
        return False

    print("=" * 50)
    print("  First-time setup: ZJU CAS credentials")
    print(f"  Stored in {_env_path}")
    print("=" * 50)
    _uid = input("Student ID (学号): ").strip()
    _pwd = input("CAS Password: ").strip()
    try:
        _env_path.parent.mkdir(parents=True, exist_ok=True)
        _env_path.write_text(f"CAS_USERNAME={_uid}\nCAS_PASSWORD={_pwd}\n",
                             encoding="utf-8")
    except Exception as e:
        print(f"ERROR: could not write {_env_path}: {type(e).__name__}: {e}")
        return False
    print(f"Credentials saved to {_env_path}")
    CAS_USERNAME, CAS_PASSWORD = _uid, _pwd
    _ENV_LOADED = True
    return True


CAS_USERNAME = os.getenv("ELANG_CAS_USERNAME", "") or os.getenv("CAS_USERNAME", "")
CAS_PASSWORD = os.getenv("ELANG_CAS_PASSWORD", "") or os.getenv("CAS_PASSWORD", "")

# ---- Answer bank ----
# Pre-built answer database from forums. Article titles are matched against
# answers.json to skip the AI round-trip for known articles.
_ANSWER_BANK = {}


def _answer_bank_sources():
    """Yield candidate readers for answers.json, in priority order.

    Order matters for distribution:

    1. **Package data** (`elang/data/answers.json`) — present when installed as a
       tool. Resolved through `importlib.resources`, so it does not depend on the
       working directory; an installed tool's cwd is whatever the host chose.
    2. **Repo `references/answers.json`** — the development layout.
    3. **cwd-relative** — last resort, kept only so an unusual checkout still works.
    """
    try:
        from importlib.resources import files as _res_files
        import elang as _elang_pkg
        p = _res_files(_elang_pkg) / "data" / "answers.json"
        if p.is_file():
            yield str(p)
    except Exception:
        pass

    for cand in (os.path.join(_SKILL_DIR, "references", "answers.json"),
                 os.path.join(os.getcwd(), "references", "answers.json")):
        if os.path.exists(cand):
            yield cand


def _load_answer_bank():
    """Populate `_ANSWER_BANK` from the shipped answers.json (once).

    A function, not import-time code, so importing this module as a library does
    no filesystem work and prints nothing.
    """
    global _ANSWER_BANK
    if _ANSWER_BANK:
        return len(_ANSWER_BANK)
    for _abp in _answer_bank_sources():
        try:
            with open(_abp, "r", encoding="utf-8") as _f:
                _bank = json.load(_f)
            for _art in _bank.get("articles", []):
                _ans = _art.get("answers")
                if not _ans or _ans.get("format") == "unknown":
                    continue
                _title = _art.get("title", "")
                # Normalize title for matching
                _key = re.sub(r'[^a-zA-Z0-9一-鿿]', '', _title.lower())
                if _key and len(_key) >= 6:
                    _ANSWER_BANK[_key] = _ans
            print(f"[elang] Answer bank loaded: {len(_ANSWER_BANK)} entries "
                  f"from {_abp}")
            break
        except Exception as _e:
            print(f"[elang] WARNING: Failed to load answer bank {_abp}: {_e}")
    return len(_ANSWER_BANK)


def _normalize_title(title):
    """Strip everything but letters/digits/CJK for title matching."""
    return re.sub(r'[^a-zA-Z0-9一-鿿]', '', (title or "").lower())


def _match_answer_bank(article_title):
    """Look up an article title in the answer bank.
    Returns (answers_dict, match_info) or (None, None).
    The answers_dict has .format, .letters, .fill_in_blank fields.
    """
    if not _ANSWER_BANK:
        return None, None
    art_key = _normalize_title(article_title)
    if not art_key or len(art_key) < 6:
        return None, None

    # 1) Exact match
    if art_key in _ANSWER_BANK:
        return _ANSWER_BANK[art_key], "exact"

    # 2) Substring match: article title contains bank key or vice versa
    for bank_key, bank_ans in _ANSWER_BANK.items():
        if len(bank_key) >= 10 and (bank_key in art_key or art_key in bank_key):
            return bank_ans, f"substring ({bank_key[:30]}…)"

    # 3) Word-level overlap
    art_words = set(art_key.split())
    best_score, best_entry = 0, None
    for bank_key, bank_ans in _ANSWER_BANK.items():
        bank_words = set(bank_key.split())
        if not art_words or not bank_words:
            continue
        overlap = len(art_words & bank_words)
        score = overlap / max(len(art_words | bank_words), 1)
        if score > 0.7 and score > best_score:
            best_score, best_entry = score, bank_ans
    if best_entry:
        return best_entry, f"fuzzy ({best_score:.0%})"

    return None, None


# ---- Tuning constants ----
CHECKPOINT_INTERVAL = 50  # Pause every N articles for user confirmation
# The script and the answering side (an agent, or a human) do not run in lockstep:
# the agent usually only notices "waiting_for_ai" on its next turn, which can be
# well over a minute later. 120s proved too short and articles timed out while the
# answer was being composed, so this is deliberately generous.
AI_TIMEOUT = 600  # Max seconds to wait for AI answers per article
CAPTCHA_TIMEOUT = 300  # Max seconds to wait for manual CAPTCHA
NAV_LOAD_WAIT = 1.5  # Seconds to wait after page navigation
BACK_LOAD_WAIT = 0.8  # Seconds between back-navigation retries
BACK_RETRIES = 8  # Max retries for back navigation
CAT_LOAD_RETRIES = 12  # Max retries for category page load

# ---- Captcha: automatic OCR + vision-model fallback ----
# ddddocr is a small offline model and is simply wrong on some of these noisy
# images. When it fails we hand the image to a vision model (or a human) through
# the same file-IPC directory the script already uses.
CAPTCHA_IPC_DIR = _IPC_ROOT
CAPTCHA_REQUEST_FILE = str(_IPC_ROOT / "elang_captcha_request.json")
CAPTCHA_ANSWER_FILE = str(_IPC_ROOT / "elang_captcha.json")
CAPTCHA_IMAGE_FILE = str(_IPC_ROOT / "elang_captcha_image.png")
CAPTCHA_MAX_OCR_ATTEMPTS = 3  # OCR submissions before falling back to vision
CAPTCHA_VISION_TIMEOUT = 600  # Seconds to wait for the vision/model answer
CAPTCHA_PROMPT = ("Read the 4 characters in the CAPTCHA image at {img} and write "
                  'the answer into {ans} as {{"captcha_code": "XXXX"}}. '
                  "Suggested command: python scripts/elang_reader.py captcha-solve")

# ---- Login-state persistence ----
# The SPA keeps its session in localStorage: `user` (profile incl. sid) and
# `authorization` (JWT). That is enough to skip CAS on later runs — which both
# saves time and avoids hammering the CAS endpoint (repeated logins appear to be
# what got us rate-limited before).
SESSION_FILE = str(_IPC_ROOT / "elang_session.json")
SESSION_MAX_AGE = 7 * 24 * 3600  # seconds; a stale token just falls back to CAS

# Persistent browser profile, kept in the user's home (NOT in the IPC dir, which
# may be a temp location). Holds cookies/cache between runs. Override with
# ELANG_PROFILE_DIR when a separate profile is wanted.
BROWSER_PROFILE_DIR = os.getenv("ELANG_PROFILE_DIR", "").strip() or os.path.join(
    os.path.expanduser("~"), ".elang", "browser-profile")


# ============================================================
# Navigation
# ============================================================


async def save_session(page):
    """Persist the browser session so the next run can skip CAS entirely.

    TWO things are needed, and localStorage alone is NOT enough:

      * cookies — `https://elang.zju.edu.cn/` is server-side protected and 302s
        to CAS on the very first request, before any page script runs. Without
        the CAS session cookie we never even reach the SPA.
      * localStorage (`user` + `authorization` JWT) — the SPA reads these during
        startup to decide whether it is logged in.
    """
    try:
        data = await page.evaluate("""() => ({
            user: localStorage.getItem('user'),
            authorization: localStorage.getItem('authorization'),
            saved_at: Date.now(),
            url: location.href,
        })""")
        if not data.get("user"):
            return False
        try:
            cookies = await page.context.cookies()
        except Exception:
            cookies = []
        # keep only what is needed to replay the session
        keep = {"name", "value", "domain", "path", "expires", "httpOnly",
                "secure", "sameSite"}
        data["cookies"] = [{k: v for k, v in c.items() if k in keep}
                           for c in cookies]
        Path(_IPC_ROOT).mkdir(parents=True, exist_ok=True)
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        sid = ""
        try:
            sid = str(json.loads(data["user"]).get("sid", ""))
        except Exception:
            pass
        print(f"[elang] session saved (sid={sid or '?'}, "
              f"{len(data['cookies'])} cookies) -> {SESSION_FILE}")
        return True
    except Exception as e:
        print(f"[elang] could not save session: {type(e).__name__}: {e}")
        return False


def _jwt_exp(token):
    """Return the `exp` claim of a JWT, or None if it cannot be read."""
    try:
        parts = str(token).split(".")
        if len(parts) != 3:
            return None
        body = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(body))
        exp = payload.get("exp")
        return float(exp) if exp else None
    except Exception:
        return None


def load_session():
    """Read a previously saved session, or None when absent/too old/expired.

    Both checks matter. The file age alone is not enough: the app's
    `authorization` token carries its own `exp`, and a session within the age
    limit can still hold a token that expired hours ago. Replaying such a session
    makes the app come up "logged in" while its API calls return 401 — the page
    then sits on 加载中 and looks like a scraper bug rather than a stale token.
    """
    if not os.path.exists(SESSION_FILE):
        return None
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    if not data.get("user") or not data.get("authorization"):
        return None

    age = time.time() - (float(data.get("saved_at", 0)) / 1000.0)
    if age > SESSION_MAX_AGE:
        print(f"[elang] saved session is {age / 86400:.1f} days old — ignoring")
        return None

    # Validate the app token's own expiry, with a small safety margin.
    exp = _jwt_exp(data.get("authorization"))
    if exp is not None:
        left = exp - time.time()
        if left <= 60:
            print(f"[elang] saved session token expired "
                  f"{abs(left) / 60:.0f} min ago — re-login required")
            return None
        print(f"[elang] saved session token valid for {left / 60:.0f} more min")
    return data


async def install_session(context, session):
    """Replay cookies + localStorage so the app comes up already authenticated.

    Order matters:
      * cookies are installed on the CONTEXT before the first navigation — the
        elang root does a server-side CAS redirect, so without the session
        cookie we would be bounced to CAS before any script could run.
      * localStorage is seeded by an init script, which runs before the app's
        own scripts on every navigation.

    Note: Playwright's Python `add_init_script` takes no arguments (the JS API
    does), so the values are embedded into the script source instead.
    """
    if not session:
        return False

    cookies = session.get("cookies") or []
    if cookies:
        try:
            await context.add_cookies(cookies)
            print(f"[elang] restored {len(cookies)} cookies")
        except Exception as e:
            print(f"[elang] cookie restore failed: {type(e).__name__}: {e}")

    payload = json.dumps({
        "user": session.get("user"),
        "authorization": session.get("authorization"),
    }, ensure_ascii=False)
    await context.add_init_script(
        f"""() => {{
            try {{
                const s = {payload};
                localStorage.setItem('user', s.user);
                localStorage.setItem('authorization', s.authorization);
            }} catch (e) {{ /* opaque origins throw; harmless */ }}
        }}"""
    )
    return True


async def navigate_to(page, url):
    """Navigate to a URL (hash route included) and handle CAS login.

    Two-phase on purpose. `page.goto()` with a URL that differs only by its hash
    is a same-document navigation the SPA can swallow, leaving us on /#/pc/home;
    so after the document has loaded we re-assert the hash explicitly and give
    the router a moment to act on it.
    """
    print(f"[elang] Navigate: {url}")
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    except Exception as e:
        print(f"[elang] goto failed ({type(e).__name__}); continuing")

    if "elang.zju.edu.cn" not in page.url:
        if CAS_USERNAME and CAS_PASSWORD:
            print(f"[elang] CAS auto-login as {CAS_USERNAME}...")
            try:
                await page.wait_for_selector("#username", timeout=20000)
                await page.locator("#username").fill(CAS_USERNAME)
                await page.locator("#password").fill(CAS_PASSWORD)
                await page.locator("#password").press("Enter")
                await page.wait_for_url("**elang.zju.edu.cn**", timeout=45000)
                print("[elang] CAS auto-login OK!")
                await page.wait_for_timeout(2500)
            except Exception as e:
                print(f"[elang] CAS auto-login failed: {e}")
        else:
            print("[elang] Waiting for CAS login (up to 120s)...")
            try:
                await page.wait_for_url("**elang.zju.edu.cn**", timeout=120000)
                print("[elang] Logged in!")
            except Exception:
                print("[elang] WARNING: login timeout, proceeding anyway")

    # re-assert the hash route: a hash-only goto can leave the router on the
    # previous route (commonly /#/pc/home)
    if "#" in url:
        target_hash = url.split("#", 1)[1]
        want = "#" + target_hash
        for _ in range(6):
            if page.url.split("#", 1)[-1] == target_hash:
                break
            try:
                await page.evaluate("(h) => { window.location.hash = h; }", want)
            except Exception:
                pass
            await page.wait_for_timeout(1200)

    print(f"[elang] URL: {page.url}")
    return True


async def _wait_until(page, js_condition, timeout_s=20, interval_ms=150, label=""):
    """Poll a cheap JS condition until true.

    Used instead of `wait_for_timeout(N)` before every check: sleeping first means
    every navigation costs the full sleep even when the app is ready immediately,
    which is what made the gap between articles feel sluggish.
    """
    import time as _t
    deadline = _t.time() + timeout_s
    while _t.time() < deadline:
        try:
            if await page.evaluate(js_condition):
                return True
        except Exception:
            pass
        await page.wait_for_timeout(interval_ms)
    if label:
        print(f"[elang] timed out waiting for {label} ({timeout_s}s)")
    return False


# cheap, non-recursive: read the learn instance pinned on the page
JS_LEARN_READY = """() => {
    const vm = window.__elangLearnVm;
    return !!(vm && (vm.$data.resourceList || []).length);
}"""

# either the list is ready, or we are on a praxis page (nothing to wait for)
JS_PRAXIS_OR_LEARN_READY = """() => {
    const h = location.hash || '';
    if (h.indexOf('/pc/read/praxis') >= 0) return true;
    const vm = window.__elangLearnVm;
    return !!(vm && (vm.$data.resourceList || []).length);
}"""

JS_PRAXIS_URL = """() => location.hash.indexOf('/pc/read/praxis') >= 0
                       && location.hash.indexOf('log_id=') >= 0"""

# Pin the learn instance on the page and report its list length, so later checks
# are a single cheap property read instead of a recursive component walk.
JS_PIN_LEARN_VM = """() => {
    function find(vm, d) {
        if (!vm || d > 14) return null;
        const n = (vm.$options && (vm.$options.name || vm.$options.__file)) || null;
        if (n === 'PcReadLearn') return vm;
        if (vm.$data && Array.isArray(vm.$data.resourceList)) return vm;
        for (const c of (vm.$children || [])) { const r = find(c, d + 1); if (r) return r; }
        return null;
    }
    const root = document.querySelector('#app');
    const vm = find(root ? root.__vue__ : null, 0);
    window.__elangLearnVm = vm || null;
    return vm ? (vm.$data.resourceList || []).length : -1;
}"""


async def pin_learn_vm(page):
    """Pin the learn instance on the page; returns the resource count (-1 if none)."""
    try:
        return await page.evaluate(JS_PIN_LEARN_VM)
    except Exception:
        return -1


# Pin the read-index instance (PcReadIndex) and report whether listData has rows.
# Returns true only when the subject list is actually populated.
JS_PIN_INDEX_VM_AND_CHECK = """() => {
    const root = document.querySelector('#app');
    function find(vm, d) {
        if (!vm || d > 14) return null;
        const n = (vm.$options && (vm.$options.name || vm.$options.__file)) || null;
        if (n === 'PcReadIndex') return vm;
        if (vm.$data && Array.isArray(vm.$data.listData)) return vm;
        for (const c of (vm.$children || [])) { const r = find(c, d + 1); if (r) return r; }
        return null;
    }
    const vm = find(root ? root.__vue__ : null, 0);
    window.__elangIndexVm = vm || null;
    if (!vm) return false;
    return (vm.$data.listData || []).length > 0;
}"""


# Read the pinned learn instance and normalise each row, using the app's own
# helpers so completion matches what the UI shows.
JS_READ_RESOURCELIST = """() => {
    const vm = window.__elangLearnVm;
    if (!vm) return null;
    const M = (vm.$options && vm.$options.methods) || {};
    const list = vm.$data.resourceList || [];
    return list.map((x, i) => {
        let status = null, text = '';
        try { status = M.normalizeStatus ? M.normalizeStatus.call(vm, x)
                                         : Number(x.status); } catch (e) {}
        try { text = M.statusText ? String(M.statusText.call(vm, x)) : ''; } catch (e) {}
        return {
            index: i,
            id: x.id,
            name: x.name || '',
            status: status,
            statusText: text,
            hisLabel: x.hisLabel,
            hasJob: Number(x.is_has_job || 0) > 0,
            contentLen: (x.content || '').length,
            isCompleted: Number(status) === 2,
        };
    });
}"""


async def go_back_to_learn(page, learn_hash, subject_id=None):
    """Return to the category's article list and wait until it is usable.

    Uses the hash route the PC app actually serves
    (`#/pc/read/learn?subject_id=...`). The list is re-fetched after the route
    change, so we wait on the DATA — but only on a cheap condition, never a fixed
    sleep before each look.
    """
    if subject_id:
        target = f"/pc/read/learn?subject_id={subject_id}"
    elif learn_hash and learn_hash.startswith("#"):
        target = learn_hash[1:]
    elif learn_hash and learn_hash.startswith("/"):
        target = learn_hash
    else:
        target = f"/pc/read/learn?subject_id={learn_hash}"

    # the list must be re-populated for THIS subject; drop the old pin so we do
    # not read the previous page's instance
    try:
        await page.evaluate("() => { window.__elangLearnVm = null; }")
    except Exception:
        pass
    try:
        await page.evaluate("(h) => { window.location.hash = h; }", "#" + target)
    except Exception:
        pass

    # Poll by PINNING the learn instance each round. Clearing the pin without
    # re-pinning was a bug: JS_PRAXIS_OR_LEARN_READY reads `window.__elangLearnVm`,
    # which stayed null forever, so this always ran the full 20s and reported
    # "learn list did not come back" even though the list had loaded fine.
    import time as _t
    deadline = _t.time() + 20
    while _t.time() < deadline:
        n = await pin_learn_vm(page)
        if n > 0:
            return True
        await page.wait_for_timeout(250)

    print("[elang] learn list did not come back after navigating to it")
    return False


# ============================================================
# Content extraction
# ============================================================


def _html_to_text(html):
    """Flatten the rich-text `content` that the resource API returns.

    The passage arrives as HTML (`<p>`, `<strong>`, `<h2>` ...). We only need
    readable plain text for the AI, so block tags become newlines and the rest is
    stripped. Entity handling is deliberately small but covers what the site emits.
    """
    if not html:
        return ""
    text = re.sub(r"(?i)</(p|div|h[1-6]|li|tr|blockquote)>", "\n", html)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&lt;", "<").replace("&gt;", ">")
                .replace("&quot;", '"').replace("&#39;", "'"))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


async def extract_page_content(page, timeout_s=60, quick=False):
    """Passage + questions for the CURRENT praxis page.

    Questions come from `PcReadPraxis.$data.jobList` (the DOM is only used to pair
    option labels with their text). Each job carries `type_id`, whose meaning is
    unchanged from the old layout:

        1        single choice / True-False
        4        multiple choice
        2,5,7,8  fill-in-the-blank (selection based)
        3,6      other (not auto-answerable)

    The questions load asynchronously AND only after the captcha has been passed,
    so we poll on the DATA rather than sleeping: `jobList` non-empty, or the
    question DOM present.

    `quick=True` takes a single reading and returns at once — used right after
    entering an article so a captcha gate is noticed immediately instead of after
    a full timeout.

    Returns {questions, passage, title, blocked, log_id, resources_id}.
    """
    empty = {"questions": [], "passage": "", "title": "",
             "blocked": False, "log_id": "", "resources_id": ""}
    last_log = None
    rounds = 1 if quick else max(1, int(timeout_s / 1.5))

    # Pin the praxis instance on the page once, then read it everywhere. Also
    # remember the handle in Python so the captcha code reads the same object.
    try:
        await pin_praxis_vm(page)
    except Exception as e:
        print(f"  [elang] could not pin the praxis component: "
              f"{type(e).__name__}: {e}")

    for _ in range(rounds):
        # Read from the instance cached ON THE PAGE (set below), so every reader
        # in this process resolves the very same component. Re-running a finder
        # per call is what let one reader see the captcha image while another saw
        # 0 bytes from what was nominally the same page.
        data = await page.evaluate("""() => {
            const vm = window.__elangPraxisVm;
            if (!vm) return null;
            const d = vm.$data || {};

            // DOM option rows, paired positionally with jobList
            const blocks = [...document.querySelectorAll('.question-block')].map(b => ({
                title: (b.querySelector('.question-title')?.innerText || '').trim(),
                options: [...b.querySelectorAll('.option-row')].map(o => ({
                    label: (o.querySelector('span')?.innerText || '').trim(),
                    text: (o.querySelector('em')?.innerText || '').trim(),
                })),
                selects: [...b.querySelectorAll('select')].map(s => ({
                    value: s.value,
                    options: [...s.options].map(op => ({ value: op.value, text: op.text.trim() })),
                })),
            }));

            const res = (d.resources && d.resources.resources) || {};
            return {
                jobs: JSON.parse(JSON.stringify(d.jobList || [])),
                blocks: blocks,
                imageLen: (d.imageBase64 || '').length,
                logId: d.logId || '',
                resourcesId: d.resourcesId || '',
                resourceName: res.name || '',
                content: res.content || '',
            };
        }""")

        if data is None:
            if quick:
                break
            await page.wait_for_timeout(1500)
            continue

        note = (len(data["jobs"]), len(data["blocks"]), data["imageLen"] > 0)
        if note != last_log:
            print(f"  [elang] praxis: jobs={note[0]} domBlocks={note[1]} "
                  f"captchaImg={'yes' if note[2] else 'no'}")
            last_log = note

        if data["jobs"] or data["blocks"]:
            questions = _build_questions(data["jobs"], data["blocks"])
            return {
                "questions": questions,
                "passage": _html_to_text(data.get("content") or ""),
                "title": data.get("resourceName") or "",
                "blocked": False,
                "log_id": data.get("logId") or "",
                "resources_id": data.get("resourcesId") or "",
            }

        await page.wait_for_timeout(1500)

    # No questions arrived. Decide whether a captcha is holding them back, using
    # the image length measured by the loop above — NOT a second, separately
    # computed probe. Having two sources of truth for the same fact is exactly
    # what made the gate report "no captcha" while the loop right above it
    # printed captchaImg=yes.
    blocked = bool(last_log and last_log[2])   # (jobs, blocks, hasImage)
    state = await _captcha_state(page)
    detail = ""
    if state:
        detail = (f" [jobs={state.get('jobs')} dom={state.get('domQuestions')} "
                  f"img={len(state.get('imageBase64') or '')}B "
                  f"gated={state.get('gated')}]")
    if blocked:
        print(f"  [elang] no questions — captcha image is pending{detail}")
    else:
        print(f"  [elang] no questions and no captcha image (empty jobList){detail}")
    out = dict(empty)
    out["blocked"] = blocked
    if state:
        out["log_id"] = str(state.get("logId") or "")
    return out


def _build_questions(jobs, blocks):
    """Normalise jobList (+ DOM rows) into the shape the rest of the script uses."""
    questions = []
    for i, job in enumerate(jobs):
        tid = job.get("type_id")
        b = blocks[i] if i < len(blocks) else {}
        options = b.get("options") or []
        if not options:
            # fall back to the model's own options when the DOM rows are absent
            for j, o in enumerate(job.get("optionsArray") or []):
                options.append({"label": o.get("label") or chr(65 + j),
                                "text": o.get("title") or o.get("text") or ""})
        kind = ("choice" if tid in (1, 4) else
                "fill" if tid in (2, 5, 7, 8) else
                "text" if tid in (3, 6) else "unknown")
        questions.append({
            "index": i,
            "job_id": job.get("id"),
            "type_id": tid,
            "kind": kind,
            "multi": tid == 4,
            "title": job.get("title") or "",
            "question": b.get("title") or job.get("title") or "",
            "options": options,
            "blanks": len(b.get("selects") or []) or
                      len([c for c in (job.get("titleChunks") or []) if c.get("isInput")]),
            "select_options": [s.get("options") for s in (b.get("selects") or [])],
        })
    return questions


async def get_article_list(page, timeout_s=45):
    """Article list for the CURRENT learn page.

    PC layout: `PcReadLearn.$data.resourceList`, whose items carry the fields we
    need (`id`, `name`, `status`, `hisLabel`). Completion is decided by the app's
    OWN helpers rather than by reimplementing the rule:

        normalizeStatus(t) { const e = Number(t.status), s = Number(t.hisLabel);
                             return s === 1 ? 2 : e }

    so `status === 2` (raw status, or hisLabel === 1) means already done.

    The id is taken from this data, NOT from the DOM: `.resource-item` elements
    expose no Vue instance on any ancestor, so a row's id cannot be read off the
    element. Items are clicked positionally instead, and the id is verified from
    the resulting URL.
    """
    import time as _t
    deadline = _t.time() + timeout_s
    while _t.time() < deadline:
        # pin once, then read the pinned instance — no recursive walk per poll
        n = await pin_learn_vm(page)
        if n > 0:
            items = await page.evaluate(JS_READ_RESOURCELIST)
            if items:
                done = sum(1 for a in items if a.get("isCompleted"))
                print(f"[elang] Vue(resourceList): {len(items)} articles ({done} done)")
                return items
        await page.wait_for_timeout(300)

    print("[elang] resourceList not found on this page (is it a learn page?)")
    return []



async def click_article(page, name, article=None):
    """Open an article. Returns (log_id, resources_id, url).

    On the PC layout the URL cannot be built by hand: `toPraxis` calls an API
    that has the server mint a `log_id`, then routes to
    `#/pc/read/praxis?log_id=...&resources_id=...`. So we must invoke it.

    Selection is positional (article['index']) because `.resource-item` elements
    carry no Vue instance, and the resulting `resources_id` is verified against
    the id we asked for. Falling back to "first row" is deliberately NOT done —
    that silently opens article 1 forever, which is how an earlier version ended
    up submitting the same answers to every article.
    """
    target_index = (article or {}).get("index")
    target_id = (article or {}).get("id")
    if target_index is None or target_id is None:
        print(f"  [ERROR] cannot open {name!r}: no row index/id in the list data")
        return "", "", page.url

    result = await page.evaluate("""(args) => {
        const [idx, wantId] = args;
        function find(vm, d) {
            if (!vm || d > 14) return null;
            const n = (vm.$options && (vm.$options.name || vm.$options.__file)) || null;
            if (n === 'PcReadLearn') return vm;
            if (vm.$data && Array.isArray(vm.$data.resourceList)) return vm;
            for (const c of (vm.$children || [])) { const r = find(c, d + 1); if (r) return r; }
            return null;
        }
        const root = document.querySelector('#app');
        const vm = find(root ? root.__vue__ : null, 0);
        if (!vm) return { error: 'PcReadLearn not found' };
        const M = (vm.$options && vm.$options.methods) || {};
        if (!M.toPraxis) return { error: 'toPraxis missing' };
        const item = (vm.$data.resourceList || [])[idx];
        if (!item) return { error: 'row ' + idx + ' not in resourceList' };
        if (wantId != null && String(item.id) !== String(wantId))
            return { error: 'row ' + idx + ' is id ' + item.id + ', wanted ' + wantId };
        window.__elangTarget = { id: item.id, name: item.name };
        try { M.toPraxis.call(vm, item); }
        catch (e) { return { error: 'toPraxis threw: ' + e.message }; }
        return { ok: true, id: item.id, name: item.name };
    }""", [target_index, target_id])

    if result.get("error"):
        print(f"  [ERROR] {result['error']}")
        return "", "", page.url
    print(f"  [elang] opening row {target_index}: {result.get('name')!r} "
          f"(id={result.get('id')})")

    # toPraxis awaits an API before routing, so wait for the route to appear.
    # Poll a cheap condition instead of sleeping in fixed steps.
    await _wait_until(page, JS_PRAXIS_URL, timeout_s=20, interval_ms=150,
                      label="praxis route")

    u = page.url
    log_id = u.split("log_id=")[1].split("&")[0] if "log_id=" in u else ""
    rid = u.split("resources_id=")[1].split("&")[0] if "resources_id=" in u else ""
    if rid and str(rid) != str(target_id):
        print(f"  [ERROR] opened resources_id={rid} but asked for {target_id} "
              f"— refusing to answer the wrong article")
        return "", "", u
    return log_id, rid, u


# ============================================================
# Answer submission
# ============================================================


async def set_answers(page, answers):
    """Record answers through the app's own methods.

    PC layout (read from the live source):
      * choice (type_id 1): `selectOption(qIdx, optIdx)`
      * choice (type_id 4): same call, but it TOGGLES, so multi-select works
      * fill   (type_id 2/5/7/8): a LIST of per-blank values in
        `$data.insertWordAnswers[jobId]` — one entry per blank, in order

    Each answer entry is:
      * `[question_index, option_index]`                      choice
      * `[question_index, ["A-avocation", "G-scavenger hunt"]]` fill, per blank
      * `[question_index, "A-avocation"]`                     fill, all blanks
                                                              the same value
    """
    result = await page.evaluate("""(answers) => {
        function find(vm, d) {
            if (!vm || d > 14) return null;
            const n = (vm.$options && (vm.$options.name || vm.$options.__file)) || null;
            if (n === 'PcReadPraxis') return vm;
            if (vm.$data && Array.isArray(vm.$data.jobList)) return vm;
            for (const c of (vm.$children || [])) { const r = find(c, d + 1); if (r) return r; }
            return null;
        }
        const root = document.querySelector('#app');
        const vm = find(root ? root.__vue__ : null, 0);
        if (!vm) return { error: 'PcReadPraxis not found' };
        const M = (vm.$options && vm.$options.methods) || {};
        if (!M.selectOption) return { error: 'selectOption missing' };

        const FILL = [2, 5, 7, 8];
        let choice = 0, fill = 0;
        const notes = [];
        for (const [qIdx, val] of answers) {
            const job = (vm.$data.jobList || [])[qIdx];
            if (!job) { notes.push('q' + qIdx + ': no job'); continue; }
            if (FILL.indexOf(job.type_id) >= 0) {
                const cur = vm.$data.insertWordAnswers[job.id] || [];
                const blanks = (job.titleChunks || []).filter(c => c.isInput).length
                    || (job.optionsArray1 || job.optionsArray || []).length || 1;
                const n = Math.max(cur.length, blanks, 1);
                // `val` is normally ONE value per blank. Accept a list so a
                // multi-blank question can be answered properly, and a scalar so
                // a single blank (or "same value everywhere") still works.
                const vals = Array.isArray(val) ? val : [val];
                const out = [];
                for (let k = 0; k < n; k++) {
                    out.push(String(vals[k] !== undefined ? vals[k] : vals[0]));
                }
                vm.$set(vm.$data.insertWordAnswers, job.id, out);
                if (M.markFillAnswer) {
                    try { M.markFillAnswer.call(vm, qIdx, 0); } catch (e) {}
                }
                notes.push('fill q' + qIdx + ': ' + out.length + ' blank(s)');
                fill++;
            } else {
                M.selectOption.call(vm, qIdx, Number(val));
                choice++;
            }
        }
        return { choice: choice, fill: fill, notes: notes,
                 jobs: (vm.$data.jobList || []).length };
    }""", [list(a) for a in answers])
    print(f"  [elang] answers recorded: {result}")
    await page.wait_for_timeout(300)
    return result


async def submit(page, dry_run=False):
    """Submit via the app's own two-step confirm.

    PC contract (read from the live source):

        openSubmitConfirm()  { if (!submitting) submitConfirmVisible = true }
        confirmSubmit()      { POST buildSubmitData(); if (code===100)
                               POST {id: logId}; if (code===100)
                               router.push({name:'PcPracticeDetailRead', ...}) }

    Letting the app build its own payload keeps us correct on question-type
    details we would otherwise have to mirror. `dry_run` opens the confirm dialog
    but does NOT post — used to exercise the whole path safely.
    """
    pre = await page.evaluate("""() => {
        function find(vm, d) {
            if (!vm || d > 14) return null;
            const n = (vm.$options && (vm.$options.name || vm.$options.__file)) || null;
            if (n === 'PcReadPraxis') return vm;
            if (vm.$data && Array.isArray(vm.$data.jobList)) return vm;
            for (const c of (vm.$children || [])) { const r = find(c, d + 1); if (r) return r; }
            return null;
        }
        const root = document.querySelector('#app');
        const vm = find(root ? root.__vue__ : null, 0);
        if (!vm) return { error: 'PcReadPraxis not found' };
        const M = (vm.$options && vm.$options.methods) || {};
        if (!M.openSubmitConfirm) return { error: 'openSubmitConfirm missing' };
        const jobs = vm.$data.jobList || [];
        let answered = 0;
        for (const j of jobs) {
            try { if (M.isAnswered && M.isAnswered.call(vm, j)) answered++; } catch (e) {}
        }
        M.openSubmitConfirm.call(vm);
        return { answered: answered, jobs: jobs.length,
                 confirmVisible: !!vm.$data.submitConfirmVisible };
    }""")
    print(f"  [elang] submit: answered {pre.get('answered')}/{pre.get('jobs')}, "
          f"confirmVisible={pre.get('confirmVisible')}")
    if pre.get("error"):
        return f"error: {pre['error']}"

    if dry_run:
        print("  [elang] dry-run: leaving the confirm dialog open, not posting")
        return "dry-run"

    await page.wait_for_timeout(600)
    post = await page.evaluate("""async () => {
        function find(vm, d) {
            if (!vm || d > 14) return null;
            const n = (vm.$options && (vm.$options.name || vm.$options.__file)) || null;
            if (n === 'PcReadPraxis') return vm;
            if (vm.$data && Array.isArray(vm.$data.jobList)) return vm;
            for (const c of (vm.$children || [])) { const r = find(c, d + 1); if (r) return r; }
            return null;
        }
        const root = document.querySelector('#app');
        const vm = find(root ? root.__vue__ : null, 0);
        if (!vm || !vm.$options.methods.confirmSubmit) return 'confirmSubmit missing';
        try { await vm.$options.methods.confirmSubmit.call(vm); return 'OK'; }
        catch (e) { return 'threw: ' + e.message; }
    }""")
    print(f"  [elang] submit: confirmSubmit -> {post}")
    await page.wait_for_timeout(4000)
    return post



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

CAPTCHA_KEYWORDS = ["captcha", "验证码", "verification", "请完成验证"]


async def detect_captcha(page):
    """Is a CAPTCHA blocking the current page?

    On the PC layout the captcha is NOT a DOM image — it lives in
    `PcReadPraxis.$data.imageBase64`, so the old DOM/title heuristics below can
    never see it. We therefore consult the component first, and only fall back
    to the DOM checks (which still serve the legacy mobile layout).

    The PC signal is `gated`: an image is waiting AND the questions have not
    arrived. Both halves matter — the image is produced as part of the normal
    load, so its mere presence is not a gate; questions appearing is what proves
    the captcha was passed.
    """
    try:
        vm = await _find_praxis_vm(page)
        if vm is None:
            print("[elang] captcha probe: PcReadPraxis not present")
        else:
            state = await _captcha_state(page)
            if state is None:
                print("[elang] captcha probe: could not read component state")
            else:
                # Always surface what we see. Silent detection made the captcha
                # step look like a hang: the terminal showed nothing at all.
                print(f"[elang] captcha probe: image={len(state.get('imageBase64') or '')}B "
                      f"jobs={state.get('jobs')} dom={state.get('domQuestions')} "
                      f"gated={state.get('gated')} cleared={state.get('cleared')}")
                if state.get("gated"):
                    return True
                if state.get("cleared"):
                    return False
    except Exception as e:
        print(f"[elang] captcha probe failed: {type(e).__name__}: {e}")

    # ---- legacy DOM heuristics ----
    try:
        body = await page.evaluate("() => document.body.innerText.substring(0, 500)")
        for kw in CAPTCHA_KEYWORDS:
            if kw.lower() in body.lower():
                print(f"[elang] captcha probe: matched keyword {kw!r}")
                return True
    except Exception:
        pass
    try:
        has_img = await page.evaluate("""() => {
            return !!document.querySelector('img[src*="captcha"],img[src*="code"],img[class*="captcha"],.captcha-img,.verify-img')
        }""")
        if has_img:
            print("[elang] captcha probe: matched a captcha image in the DOM")
            return True
    except Exception:
        pass
    return False


# Track captcha state: once it appears, it persists for the rest of the session
_captcha_seen = False

# Generic component lookup. The PC app names its pages PcReadIndex / PcReadLearn /
# PcReadPraxis, so we match on the name (preferred) or on a data-key fingerprint
# (fallback, in case a name changes).
def _js_find_vm(names, data_keys):
    names_js = json.dumps(list(names))
    keys_js = json.dumps(list(data_keys))
    return """() => {
        const NAMES = %s, KEYS = %s;
        function find(vm, d) {
            if (!vm || d > 14) return null;
            const opts = vm.$options || {};
            const n = opts.name || opts.__file || null;
            if (n && NAMES.indexOf(n) >= 0) return vm;
            const data = vm.$data || {};
            if (KEYS.length && KEYS.every(k => k in data)) return vm;
            for (const c of (vm.$children || [])) { const r = find(c, d + 1); if (r) return r; }
            return null;
        }
        const root = document.querySelector('#app');
        return find(root ? root.__vue__ : null, 0);
    }""" % (names_js, keys_js)


JS_FIND_PRAXIS_VM = _js_find_vm(["PcReadPraxis"], ["jobList", "imageBase64"])
JS_FIND_LEARN_VM = _js_find_vm(["PcReadLearn"], ["resourceList"])
JS_FIND_INDEX_VM = _js_find_vm(["PcReadIndex"], ["listData", "categoryId"])


async def _wait_for_vm(page, js, timeout_s=40, label="component"):
    """Poll until a component is present (the SPA mounts it after the route change)."""
    import time as _t
    deadline = _t.time() + timeout_s
    while _t.time() < deadline:
        try:
            vm = await page.evaluate(js)
        except Exception:
            vm = None
        if vm is not None:
            return vm
        await page.wait_for_timeout(700)
    print(f"[elang] {label} not found within {timeout_s}s")
    return None


JS_PRAXIS_STATE = """() => {
    // Read the instance that pin_praxis_vm() stored ON THE PAGE.
    //
    // Do NOT try to pass a Vue instance in from Python: a Vue component is a big
    // circular object and Playwright cannot serialise it, so the argument arrives
    // as an opaque/empty value and every field reads as 0 — which is precisely
    // how "captcha image is present" and "captcha has no image" were both being
    // reported for the same page.
    const vm = window.__elangPraxisVm;
    if (!vm) return null;
    const d = vm.$data || {};
    const jobs = (d.jobList || []).length;
    const domQuestions = document.querySelectorAll(
        '.question-block, .option-row').length;
    const img = d.imageBase64 || '';
    return {
        imageBase64: img,
        hasImage: !!img,
        verifyCode: d.verifyCode || '',
        dialogShow: !!d.dialogShow,
        jobs: jobs,
        domQuestions: domQuestions,
        submitting: !!d.submitting,
        loading: !!d.loading,
        _name: (vm.$options && (vm.$options.name || vm.$options.__file)) || null,
        _keys: Object.keys(d).length,
        _logId: d.logId || null,
        _resourcesId: d.resourcesId || null,
        // questions are present -> the captcha (if any) has been passed
        cleared: (jobs > 0 || domQuestions > 0),
        // an image is waiting and the questions have not arrived yet
        gated: (!!img && jobs === 0 && domQuestions === 0),
    };
}"""

async def _find_praxis_vm(page):
    """Locate the component that owns the captcha state, or None."""
    try:
        return await page.evaluate(JS_FIND_PRAXIS_VM)
    except Exception:
        return None


# Store the located instance on the page so that every reader — including the
# ones that live in separate `page.evaluate` calls — reads the SAME object.
# `page.evaluate` returning an object hands back a copy, so re-finding the
# component per call is what produced contradictory readings (one reader saw the
# captcha image, another saw 0 bytes, on the same page).
JS_PIN_PRAXIS_VM = """() => {
    const root = document.querySelector('#app');
    const vm = __FIND_PRAXIS_VM__(root ? root.__vue__ : null, 0);
    window.__elangPraxisVm = vm || null;
    if (!vm) return null;
    const d = vm.$data || {};
    return {
        name: (vm.$options && (vm.$options.name || vm.$options.__file)) || null,
        dataKeys: Object.keys(d).length,
        imageLen: (d.imageBase64 || '').length,
        jobs: (d.jobList || []).length,
        logId: d.logId || null,
        resourcesId: d.resourcesId || null,
    };
}"""


async def pin_praxis_vm(page):
    """Find the praxis component and pin the INSTANCE on the page.

    The finder is installed as a page global first, so the pin call and any later
    lookup use literally the same function and therefore the same instance. The
    instance itself stays in the browser (`window.__elangPraxisVm`) because a Vue
    component cannot be serialised out to Python.
    """
    finder = _js_find_vm(["PcReadPraxis"], ["jobList", "imageBase64"])
    try:
        await page.evaluate(
            "() => { window.__FIND_PRAXIS_VM__ = " + finder + "; }")
        info = await page.evaluate(JS_PIN_PRAXIS_VM)
    except Exception as e:
        print(f"  [elang] pin failed: {type(e).__name__}: {e}")
        return None
    if info is None:
        return None
    print(f"  [elang] praxis pinned: {info['name']} "
          f"image={info['imageLen']}B jobs={info['jobs']} "
          f"logId={info['logId']} rid={info['resourcesId']}")
    return info


async def _focus_captcha_vm(page):
    """(Re)pin the captcha-owning component. False when absent.

    Kept as a small wrapper for call sites that only want "is there a praxis
    component right now?".
    """
    info = await pin_praxis_vm(page)
    return info is not None


async def _captcha_state(page, vm=None):
    """Read captcha state from the instance pinned on the page.

    Why the argument is ignored: a Vue component instance is a large circular
    object, and Playwright **cannot serialise it into Python**. Passing one as an
    argument therefore delivers an empty value, every field reads as 0, and the
    captcha image appears absent even when it is right there — which is exactly
    how "image present" and "no image yet" were both being printed for one page.

    `pin_praxis_vm()` stores the live instance on `window.__elangPraxisVm`, so the
    read happens entirely inside the browser where the real object exists.
    """
    try:
        return await page.evaluate(JS_PRAXIS_STATE)
    except Exception as e:
        print(f"[elang] captcha state read failed: {type(e).__name__}: {e}")
        return None


def _decode_data_uri(value):
    """'data:image/png;base64,XXXX' (or bare base64) -> PNG bytes."""
    import base64 as _b64
    s = (value or "").strip()
    if s.startswith("data:"):
        s = s.split(",", 1)[1] if "," in s else ""
    try:
        return _b64.b64decode(s)
    except Exception:
        return b""


def _save_captcha_image(png_bytes, name="captcha_last.png"):
    if not png_bytes:
        return None
    try:
        Path(SCRATCH_DIR).mkdir(parents=True, exist_ok=True)
        p = os.path.join(SCRATCH_DIR, name)
        with open(p, "wb") as f:
            f.write(png_bytes)
        return p
    except Exception as e:
        print(f"[elang] could not save captcha image: {e}")
        return None


def _ocr_captcha(png_bytes):
    """ddddocr -> 4 characters, or '' when it cannot tell.

    These images are 4 characters over heavy colour noise. ddddocr is quick and
    usually right, but it is a small model and does get these wrong — which is
    exactly why the vision fallback exists.
    """
    if not png_bytes:
        return ""
    ocr = _get_ocr()
    if ocr is None:
        return ""
    try:
        text = str(ocr.classification(png_bytes)).strip()
    except Exception as e:
        print(f"[elang] ddddocr error: {type(e).__name__}: {e}")
        return ""
    chars = re.sub(r"[^0-9A-Za-z]", "", text)
    if len(chars) >= 4:
        return chars[:4]
    print(f"[elang] ddddocr returned too few characters: {text!r}")
    return ""


def _write_captcha_request(png_bytes):
    """Hand the image to a vision model / the user via file IPC.

    The image goes INTO the IPC directory so the path recorded in the request is
    a path a reader can actually open.
    """
    try:
        Path(CAPTCHA_IPC_DIR).mkdir(parents=True, exist_ok=True)
        if png_bytes:
            with open(CAPTCHA_IMAGE_FILE, "wb") as f:
                f.write(png_bytes)
        req = {
            "status": "captcha_needs_vision",
            "image_path": CAPTCHA_IMAGE_FILE,
            "image_size": len(png_bytes or b""),
            "answer_file": CAPTCHA_ANSWER_FILE,
            "chars_expected": 4,
            "instruction": ("Read the 4 characters in image_path, then write "
                            '{"captcha_code": "XXXX"} to answer_file.'),
        }
        with open(CAPTCHA_REQUEST_FILE, "w", encoding="utf-8") as f:
            json.dump(req, f, ensure_ascii=False, indent=2)
        print(f"[elang] captcha request -> {CAPTCHA_REQUEST_FILE}")
    except Exception as e:
        print(f"[elang] could not write captcha request: {e}")


def _read_captcha_answer():
    """Read the code a vision model (or the user) supplied, if any."""
    if not os.path.exists(CAPTCHA_ANSWER_FILE):
        return ""
    try:
        with open(CAPTCHA_ANSWER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return ""
    code = re.sub(r"[^0-9A-Za-z]", "", str(data.get("captcha_code", "")))
    return code[:4] if len(code) >= 4 else ""


def _remove_file(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


async def _submit_captcha(page, code, vm=None):
    """Set verifyCode and call the component's own checkCaptchaCode().

    Everything happens inside the browser, against the instance pinned on the
    page — see `_captcha_state` for why a Vue instance cannot be handed across
    the Playwright boundary.

    Returns True once the page is usable (questions present). We deliberately do
    NOT key success off `dialogShow` — its meaning is easy to invert, and the
    questions appearing is the signal that actually matters.
    """
    if not await _focus_captcha_vm(page):
        print("[elang] captcha submit: praxis component not found")
        return False
    try:
        result = await page.evaluate("""async (code) => {
            const vm = window.__elangPraxisVm;
            if (!vm) return { error: 'praxis component not pinned' };
            const M = (vm.$options && vm.$options.methods) || {};
            if (!M.checkCaptchaCode) return { error: 'checkCaptchaCode missing' };
            const before = {
                jobs: (vm.$data.jobList || []).length,
                images: (vm.$data.imageBase64 || '').length,
                dialogShow: !!vm.$data.dialogShow,
            };
            vm.$data.verifyCode = code;
            try { await M.checkCaptchaCode.call(vm); }
            catch (e) { return { error: 'threw: ' + e.message, before: before }; }
            return {
                ok: true, before: before,
                after: {
                    jobs: (vm.$data.jobList || []).length,
                    images: (vm.$data.imageBase64 || '').length,
                    dialogShow: !!vm.$data.dialogShow,
                    sameImage: (vm.$data.imageBase64 || '').length === before.images,
                },
            };
        }""", code)
    except Exception as e:
        print(f"[elang] captcha submit failed: {type(e).__name__}: {e}")
        return False

    if result.get("ok"):
        b, a = result.get("before") or {}, result.get("after") or {}
        print(f"[elang] captcha submit {code!r}: jobs {b.get('jobs')}->{a.get('jobs')}, "
              f"image {b.get('images')}->{a.get('images')}B, "
              f"dialogShow={a.get('dialogShow')}, imageChanged={not a.get('sameImage')}")
    if result.get("error"):
        print(f"[elang] captcha submit: {result['error']}")
        return False

    for _ in range(10):
        await page.wait_for_timeout(600)
        state = await _captcha_state(page)
        if state and state.get("cleared"):
            return True
    _remove_file(CAPTCHA_ANSWER_FILE)
    return False


async def wait_for_captcha(page, timeout=CAPTCHA_TIMEOUT):
    """Solve the captcha: automatic OCR first, vision model (or human) second.

    Two mechanisms, in this order:

      1. ddddocr — instant, offline, free. Right most of the time.
      2. Vision hand-off — the image is written to the IPC directory together
         with an explicit request, and a vision-capable agent (or the user)
         supplies the code. This exists because ddddocr *is* wrong sometimes on
         these noisy 200x100 images, and being wrong would otherwise stall the
         whole run.

    How the answer is submitted on the PC layout
    --------------------------------------------
    NOT by typing into a field. Live reconnaissance of `PcReadPraxis` showed the
    captcha is driven entirely by component state:

        $data.imageBase64   the image (data URI), filled by refreshCaptcha()
        $data.verifyCode    the code to submit
        checkCaptchaCode()  POSTs the code; on success it loads the job list

    and the page renders **no <input>** for it (the dialog is a Vant component),
    so the old `.Verify-box input` + `.btn-Verify` clicking path cannot work on
    the PC layout. We therefore set `verifyCode` and call `checkCaptchaCode()`.

    Retries compare the image bytes: if the server did not hand us a NEW image
    after a wrong code, retrying the same attempt is pointless and we stop —
    that guard is what prevents the infinite OCR loop this file used to have.
    """
    global _captcha_seen
    print("[elang] !! CAPTCHA detected — solving")

    if not await _focus_captcha_vm(page):
        print("[elang] no praxis component with captcha state found")
        return False

    state = await _captcha_state(page)
    if not state:
        print("[elang] captcha state unavailable")
        return False
    image = state.get("imageBase64") or ""
    if not image:
        print("[elang] captcha has no image yet")
        return False

    # ---------- manual mode: hands off, the human solves it ----------
    # Important: the app binds the dialog's input to `$data.verifyCode`, and a
    # wrong submission makes the app refresh the image — which WIPES whatever the
    # user had typed. So when the user wants to solve it by hand we must not
    # touch verifyCode at all; we only watch for the questions to appear.
    if os.getenv("ELANG_CAPTCHA_MANUAL", "").strip() in ("1", "true", "yes"):
        print("[elang] MANUAL captcha mode (ELANG_CAPTCHA_MANUAL=1):")
        print("[elang]   -> type the 4 characters into the page and click 提交")
        print(f"[elang]   (the image is also saved to {CAPTCHA_IMAGE_FILE})")
        _save_captcha_image(_decode_data_uri(image), "captcha_manual.png")
        waited = 0
        while waited < timeout:
            await asyncio.sleep(2)
            waited += 2
            st = await _captcha_state(page)
            if st and st.get("cleared"):
                _captcha_seen = True
                print(f"[elang] [OK] captcha solved by hand after {waited}s")
                return True
            if waited % 20 == 0:
                print(f"[elang]   still waiting for the captcha "
                      f"({waited}s/{timeout}s)")
        print("[elang] manual captcha timed out")
        return False

    tried = set()
    code = ""

    # ---------- mechanism 1: automatic OCR ----------
    for attempt in range(1, CAPTCHA_MAX_OCR_ATTEMPTS + 1):
        state = await _captcha_state(page)
        image = state.get("imageBase64") or ""
        if not image:
            break
        png = _decode_data_uri(image)
        _save_captcha_image(png, "captcha_last.png")
        guess = _ocr_captcha(png)
        if not guess:
            break
        if guess in tried:
            print(f"[elang] OCR keeps returning {guess!r} and the image is not "
                  f"changing — stopping OCR retries")
            break
        tried.add(guess)
        print(f"[elang] OCR attempt {attempt}/{CAPTCHA_MAX_OCR_ATTEMPTS}: {guess!r}")
        if await _submit_captcha(page, guess):
            _captcha_seen = True
            print("[elang] [OK] CAPTCHA solved by OCR")
            return True

    # ---------- mechanism 2: vision model / human ----------
    state = await _captcha_state(page)
    if not state:
        return False
    image = state.get("imageBase64") or ""
    if not image:
        print("[elang] captcha cleared while solving")
        _captcha_seen = True
        return True

    png = _decode_data_uri(image)
    _save_captcha_image(png, "captcha_unsolved.png")
    _write_captcha_request(png)
    print(f"[elang] OCR could not solve it (tried {sorted(tried)}).")
    print(f"[elang] Image: {CAPTCHA_IMAGE_FILE}")
    print(f"[elang] A vision model or you can read it, then write:")
    print(f'[elang]   {CAPTCHA_ANSWER_FILE}  ->  {{"captcha_code": "XXXX"}}')
    print(f"[elang] Waiting up to {CAPTCHA_VISION_TIMEOUT}s...")

    waited = 0
    last_image = image
    while waited < CAPTCHA_VISION_TIMEOUT:
        await asyncio.sleep(2)
        waited += 2

        # the user may have typed it into the page by hand; either way, once the
        # dialog is gone / the job list appears we are done
        state = await _captcha_state(page)
        if state and state.get("cleared"):
            _captcha_seen = True
            print("[elang] [OK] CAPTCHA resolved (page is usable)")
            return True

        # a vision answer handed back through IPC
        answer = _read_captcha_answer()
        if answer and answer not in tried:
            tried.add(answer)
            print(f"[elang] vision/manual answer: {answer!r}")
            if await _submit_captcha(page, answer):
                _captcha_seen = True
                print("[elang] [OK] CAPTCHA solved via vision model")
                return True
            # wrong -> the app refreshes the image; re-issue the request
            state = await _captcha_state(page)
            if not state:
                return False
            new_image = state.get("imageBase64") or ""
            if new_image and new_image != last_image:
                last_image = new_image
                _save_captcha_image(_decode_data_uri(new_image), "captcha_unsolved.png")
                _write_captcha_request(_decode_data_uri(new_image))
                print("[elang] new captcha image — request re-issued")
            else:
                print("[elang] image unchanged; will not retry the same guess")
        elif answer:
            _remove_file(CAPTCHA_ANSWER_FILE)

    print(f"[elang] captcha not solved within {CAPTCHA_VISION_TIMEOUT}s")
    return False


async def check_and_handle_captcha(page):
    """Proactive captcha check — call before entering article if captcha was seen before."""
    global _captcha_seen
    if _captcha_seen:
        print("[elang] Proactive captcha check (seen before)...")
        if await detect_captcha(page):
            return await wait_for_captcha(page)
    return True


# ============================================================
# Article processor (per category)
# ============================================================


async def process_articles(page, article_infos, start_counter, learn_hash,
                           subject_id=None, dry_run=False):
    """Work through a category's articles.

    Articles are opened via `click_article`, which calls the app's `toPraxis`
    (the server mints `log_id`; the URL cannot be built by hand). Once on the
    praxis page the questions are read from `jobList` — and because that only
    populates AFTER the captcha is passed, a captcha gate is handled here rather
    than being waited out.

    `subject_id` (when known) is used to return to the list, since the PC learn
    route is `#/pc/read/learn?subject_id=...`.
    """
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

        print(f"\n{'=' * 50}")
        print(f"[{article_num}] {i+1}/{total}: {name}")
        print(f"{'=' * 50}")

        log_id, resources_id, praxis_url = await click_article(page, name, info)
        if not log_id or not resources_id:
            print("  SKIP: no praxis URL generated")
            results.append({"name": name, "status": "no_url"})
            await go_back_to_learn(page, learn_hash, subject_id)
            continue

        # Read the page. The captcha check must be immediate: waiting for the
        # questions first would burn a whole extract timeout before we even look.
        # `extract_page_content` itself decides whether the captcha image that it
        # observed is holding the questions back, so there is exactly one source
        # of truth and no second probe to disagree with it.
        content = await extract_page_content(page, timeout_s=8, quick=True)

        if content.get("blocked"):
            print("  [captcha] image pending on entry — solving now")
            if await wait_for_captcha(page):
                print("  [captcha] cleared — reading the questions")
                content = await extract_page_content(page)
        elif not content.get("questions"):
            print("  no questions yet and no captcha — waiting for them to load...")
            content = await extract_page_content(page)
            if content.get("blocked"):
                print("  [captcha] image appeared while waiting — solving")
                if await wait_for_captcha(page):
                    content = await extract_page_content(page)

        if not content.get("questions"):
            print(f"  SKIP: no questions (blocked={content.get('blocked')})")
            results.append({"name": name, "status": "no_questions"})
            await go_back_to_learn(page, learn_hash, subject_id)
            continue

        questions = content["questions"]
        kinds = {}
        for q in questions:
            kinds[q["kind"]] = kinds.get(q["kind"], 0) + 1
        print(f"  Qs: {len(questions)} {kinds} | "
              f"Passage: {len(content['passage'])} chars")

        unsupported = [q for q in questions if q["kind"] in ("text", "unknown")]
        if unsupported:
            print(f"  SKIP: {len(unsupported)} non-choice question(s) "
                  f"(type_id {sorted({q['type_id'] for q in unsupported})})")
            results.append({"name": name, "status": "unsupported_types"})
            await go_back_to_learn(page, learn_hash, subject_id)
            continue

        Path(SCRATCH_DIR).mkdir(parents=True, exist_ok=True)
        with open(os.path.join(SCRATCH_DIR, f"article_{article_num}.json"),
                  "w", encoding="utf-8") as f:
            json.dump({"title": content["title"], "passage": content["passage"],
                       "questions": questions}, f, ensure_ascii=False, indent=2)

        # ---- answer bank: only for all-choice articles ----
        data = None
        choice_qs = [q for q in questions if q["kind"] == "choice"]
        all_choice = len(choice_qs) == len(questions)
        bank_ans, match_info = _match_answer_bank(content["title"] or name)
        if not bank_ans:
            bank_ans, match_info = _match_answer_bank(name)
        if bank_ans and bank_ans.get("format") in ("letters", "letter_and_fill"):
            letters = bank_ans.get("letters", [])
            if not all_choice:
                print(f"  [BANK] matched ({match_info}) but this article has "
                      f"fill-in questions — asking AI")
            elif len(letters) != len(choice_qs):
                print(f"  [BANK] matched ({match_info}) but bank has {len(letters)} "
                      f"letters for {len(choice_qs)} questions — asking AI")
            else:
                letter_map = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
                data = {"status": "answers_ready",
                        "answers": [[q["index"], letter_map[L.upper()]]
                                    for q, L in zip(choice_qs, letters)]}
                print(f"  [BANK] matched ({match_info}) — {len(letters)} answers")
        elif bank_ans:
            print(f"  [BANK] found but format={bank_ans.get('format')} — asking AI")

        if data is None:
            article_data = {
                "article_index": i,
                "article_name": name,
                "article_number": article_num,
                "total_remaining": total - i,
                "url": praxis_url,
                "title": content["title"],
                "passage": content["passage"][:8000],
                "questions": [{
                    "index": q["index"], "type_id": q["type_id"], "kind": q["kind"],
                    "multi": q["multi"], "blanks": q["blanks"],
                    "question": q["question"], "options": q["options"],
                    "select_options": q["select_options"],
                } for q in questions],
                "answers": [],
                "status": "waiting_for_ai",
            }
            data = await request_ai_answers(article_data)

        if data and data.get("status") in ("answers_ready", "skip"):
            if data.get("status") == "answers_ready" and data.get("answers"):
                await set_answers(page, data["answers"])
            else:
                print("  [SKIP] submitting as-is")
            await submit(page, dry_run=dry_run)
            results.append({"name": name,
                            "status": "dry_run" if dry_run else "submitted"})
            print(f"  [OK] {'dry-run (not posted)' if dry_run else 'submitted'}")
        else:
            print("  [FAIL] AI timeout")
            results.append({"name": name, "status": "timeout"})

        await go_back_to_learn(page, learn_hash, subject_id)

    return results



def print_summary(results):
    """Count outcomes accurately.

    `dry_run` is a SUCCESS (answers were recorded and the confirm dialog opened);
    only real failures should be reported as failed.
    """
    s = sum(1 for r in results if r["status"] == "submitted")
    d = sum(1 for r in results if r["status"] == "dry_run")
    k = sum(1 for r in results if r["status"] == "skipped_completed")
    f = len(results) - s - d - k
    parts = [f"{s} submitted"]
    if d:
        parts.append(f"{d} dry-run")
    parts.append(f"{k} skipped")
    if f:
        parts.append(f"{f} failed")
    print(f"\n[elang] Done: " + ", ".join(parts))


# ============================================================
# Batch ALL categories
# ============================================================


async def open_browser(playwright):
    """Open a browser with a PERSISTENT profile, pre-loading any saved session.

    Returns `(context, page, restored)`.

    Design notes, all verified on a real machine:

    * **Bundled Chromium, no `channel=`.** Using `channel="msedge"` made the
      browser refuse to start (Edge complained about unsupported command-line
      flags) and it ties the tool to a system-installed browser. The bundled
      Chromium is installed by `playwright install chromium`, which the setup
      scripts already run, so this works on any machine with no user setup.
    * **`launch_persistent_context`, not `launch` + args.** Passing
      `--user-data-dir` to `launch()` is rejected by Playwright; the persistent
      API is the supported way to get a stable profile. The profile lives under
      the user's home so caches and other state survive reboots and temp cleanup.
    * **Cookies + localStorage are still injected explicitly.** Measured: a
      persistent profile alone does NOT retain the CAS session cookies
      (`iPlanetDirectoryPro`, zjuam `JSESSIONID` are session cookies and are
      dropped), so the replay step is required, not optional.

    There is no separate `browser` object to close with this API — the context is
    the top-level handle, so callers close the context.
    """
    # Lazily load credentials and the answer bank on first browser start, so that
    # merely importing this module has no side effects.
    _ensure_credentials(prompt_ok=False)
    _load_answer_bank()

    channel = os.getenv("ELANG_BROWSER", "").strip()
    kwargs = {
        "user_data_dir": str(BROWSER_PROFILE_DIR),
        "headless": False,
        "viewport": {"width": 1440, "height": 900},
    }
    if channel and channel != "chromium":
        # escape hatch for anyone who specifically wants a system browser
        kwargs["channel"] = channel

    # Tell Playwright where to FIND the browser before launching. Without this it
    # always uses the shared cache, so a browser installed into the tool's private
    # directory would sit unused while launch failed.
    #
    # Precedence mirrors config.browser_search_paths(): an explicit
    # PLAYWRIGHT_BROWSERS_PATH wins; otherwise prefer the private cache, but fall
    # back to the shared one when the private copy is absent — that reuses an
    # existing installation instead of forcing a redundant ~683 MB download.
    if _config is not None:
        override = (os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "").strip()
        if not override:
            if _config.BROWSERS_DIR.is_dir():
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(_config.BROWSERS_DIR)

    Path(BROWSER_PROFILE_DIR).mkdir(parents=True, exist_ok=True)
    try:
        context = await playwright.chromium.launch_persistent_context(**kwargs)
    except Exception as e:
        msg = str(e)
        if "Executable doesn't exist" in msg or "playwright install" in msg:
            raise RuntimeError(
                "Chromium is not installed for this tool.\n"
                f"  Install it with:  elang install-browser\n"
                f"  (or directly:  {sys.executable} -m playwright install chromium)\n"
                f"  Original error: {msg.splitlines()[0]}"
            ) from e
        raise

    session = load_session()
    restored = False
    if session:
        await install_session(context, session)
        restored = True
        print(f"[elang] restoring saved session -> {SESSION_FILE}")
    else:
        print("[elang] no saved session; CAS login will be needed")

    page = context.pages[0] if context.pages else await context.new_page()
    return context, page, restored


async def token_seconds_left(page):
    """Seconds until the app's authorization token expires, or None if unknown."""
    try:
        return await page.evaluate("""() => {
            const auth = localStorage.getItem('authorization') || '';
            try {
                const parts = auth.split('.');
                if (parts.length !== 3) return null;
                const b = parts[1].replace(/-/g, '+').replace(/_/g, '/');
                const pad = b + '='.repeat((4 - b.length % 4) % 4);
                const payload = JSON.parse(atob(pad));
                if (!payload || !payload.exp) return null;
                return Math.floor(payload.exp - Date.now() / 1000);
            } catch (e) { return null; }
        }""")
    except Exception:
        return None


async def ensure_fresh_token(page, url, margin_s=300):
    """Re-login if the app token is close to expiring.

    The app token lives only ~2 hours (measured `iat` -> `exp`), which a long
    `batch-all` run will certainly cross. When it lapses the app does not recover
    on its own: API calls start returning 401 and pages sit on 加载中. Refreshing
    *before* that happens keeps a long run working, instead of failing at an
    arbitrary article.

    Returns True when a usable token exists afterwards.
    """
    left = await token_seconds_left(page)
    if left is None:
        return await session_is_live(page)
    if left > margin_s:
        return True
    print(f"[elang] app token expires in {left / 60:.0f} min — refreshing the session")
    return await ensure_logged_in(page, url, restored=False)


async def session_is_live(page):
    """Is the app actually authenticated right now?

    Checks three things, all of which matter:
      * we are not sitting on the CAS callback,
      * the SPA has written `user` + `authorization`,
      * **and that authorization token has not expired.**

    The expiry check is not optional. Presence alone is a trap: the app's token is
    short-lived (observed ~2 hours), and an expired token left in localStorage
    still satisfies "user and auth exist". The app then renders as logged in while
    its API calls return 401 — the subject list never appears, and it looks like a
    scraping bug. Verified on the live site: a token whose `exp` was 12 hours in
    the past passed a presence-only check while `/en/subject/gets` answered 401.
    """
    try:
        st = await page.evaluate("""() => {
            const auth = localStorage.getItem('authorization') || '';
            let exp = null;
            try {
                const parts = auth.split('.');
                if (parts.length === 3) {
                    const b = parts[1].replace(/-/g, '+').replace(/_/g, '/');
                    const pad = b + '='.repeat((4 - b.length % 4) % 4);
                    const payload = JSON.parse(atob(pad));
                    if (payload && payload.exp) exp = Number(payload.exp);
                }
            } catch (e) {}
            return {
                hash: location.hash,
                user: !!localStorage.getItem('user'),
                auth: !!auth,
                exp: exp,
                now: Math.floor(Date.now() / 1000),
            };
        }""")
    except Exception:
        return False
    if "#/authLogin" in (st.get("hash") or ""):
        return False
    if "zjuam.zju.edu.cn" in page.url:
        return False
    if not (st.get("user") and st.get("auth")):
        return False
    exp = st.get("exp")
    if exp is not None:
        left = exp - (st.get("now") or 0)
        if left <= 60:
            print(f"[elang] app token expired {abs(left) / 60:.0f} min ago "
                  f"— treating the session as stale")
            return False
    return True


def drop_session():
    """Discard the saved session so the next attempt does a clean CAS login."""
    _remove_file(SESSION_FILE)


async def finish_login(page):
    """Persist the session once the app is genuinely authenticated.

    Timing matters: straight after the CAS redirect the app is still on
    /#/authLogin exchanging the code for a JWT, so `authorization` is not written
    yet and saving then would store a useless session. Wait until that hop has
    completed and the token is actually present.
    """
    for _ in range(30):
        if await session_is_live(page):
            return await save_session(page)
        await page.wait_for_timeout(1000)
    print("[elang] login did not complete (no user/authorization in localStorage)")
    return False


async def ensure_logged_in(page, url, restored):
    """Navigate to `url`, retrying once with a clean login if a replayed session
    turned out to be stale.

    Why the recovery clears storage, not just cookies
    -------------------------------------------------
    Observed failure (console from the real site):

        authLogin.vue:79  ST-746842-...          <- reusing an ALREADY-CONSUMED ticket
        authLogin.vue:43  CAS login failed

    The app keeps the original `#/authLogin?code=ST-...` in the URL hash and
    re-submits that same ticket. A CAS service ticket is single-use, so the
    exchange always returns `code:400 登录失败` and the page stays blank on
    /#/authLogin — it never goes back to CAS for a fresh ticket. Because the code
    lives in the URL hash, stale app storage keeps resurrecting it. So recovery
    must clear the app's storage as well as its cookies, then start over.
    """
    await navigate_to(page, url)

    if await session_is_live(page):
        if restored:
            print("[elang] saved session is live — CAS skipped")
        else:
            await finish_login(page)
        return True

    # Not authenticated. Whether we replayed a session or not, the app's storage
    # may hold an EXPIRED token, and that must be wiped before trying to log in.
    #
    # Why this is not only a "restored" concern: with a persistent browser profile
    # the previous run's localStorage survives on disk. The app then boots looking
    # logged in, `session_is_live` (correctly) rejects the expired token, and any
    # plain re-navigation just re-reads the same dead token — the CAS exchange
    # never runs and the caller waits forever for a token that cannot appear.
    # Observed exactly that: 31 consecutive "token expired" checks followed by
    # "login did not complete".
    print("[elang] session is not usable — clearing app storage and cookies, "
          "then logging in again")
    drop_session()
    try:
        await page.context.clear_cookies()
    except Exception:
        pass
    # A stale hash ticket otherwise gets replayed on the next load, and CAS
    # rejects an already-consumed ticket with code:400.
    try:
        await page.evaluate(
            "() => { try { localStorage.clear(); sessionStorage.clear(); } "
            "catch (e) {} }")
    except Exception:
        pass
    # Also drop any init script that could re-seed the old values on load.
    try:
        await page.context.add_init_script(
            """() => { try { localStorage.clear(); sessionStorage.clear(); }
                       catch (e) {} }""")
    except Exception:
        pass
    try:
        await page.goto("about:blank", wait_until="domcontentloaded", timeout=15000)
    except Exception:
        pass
    await navigate_to(page, url)
    await finish_login(page)
    return await session_is_live(page)


async def mode_batch_all(start_cat=0, dry_run=False, limit=None,
                         subjects_only=False, only_subject_ids=None):
    """Process every subject on the reading index. Resumable via checkpoint.

    `limit` caps how many articles may be SUBMITTED in this run, which makes the
    mode safe to exercise without opening the floodgates over ~291 articles.
    `subjects_only` lists what would be processed and exits without touching any
    article — the cheapest way to verify the index-reading path.
    `only_subject_ids` restricts the run to specific subject ids.
    """
    Path(SCRATCH_DIR).mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        context, page, restored = await open_browser(p)

        # Navigate to reading index (re-logs in if a saved session is stale)
        await ensure_logged_in(page, "https://elang.zju.edu.cn/#/pc/read/index", restored)

        # The route change only MOUNTS PcReadIndex; its subject list is fetched
        # afterwards. Reading immediately gets an empty list and looked like
        # "no subjects found", so wait on the component's own data first.
        print("[elang] Loading the subject list...")
        ready = await _wait_until(page, JS_PIN_INDEX_VM_AND_CHECK, timeout_s=30,
                                  interval_ms=400, label="PcReadIndex listData")
        if not ready:
            # say what we actually see instead of a bare failure
            try:
                diag = await page.evaluate("""() => ({
                    url: location.href,
                    hasApp: !!document.querySelector('#app'),
                    appVue: !!(document.querySelector('#app') || {}).__vue__,
                    text: (document.body.innerText || '').slice(0, 200),
                })""")
                print(f"[elang] index page state: {diag}")
            except Exception as e:
                print(f"[elang] index diag failed: {type(e).__name__}: {e}")

        # Extract the SUBJECT list from the PC read index.
        # `PcReadIndex.$data.listData` holds subjects (not the top-level "reading"
        # category): each item is {id, name, resource_num, category_id, ...} and
        # `id` is the subject_id used by /#/pc/read/learn?subject_id=<id>.
        # Only subjects with resources are worth visiting.
        categories = []
        for _ in range(CAT_LOAD_RETRIES):
            categories = await page.evaluate("""() => {
                function find(vm, d) {
                    if (!vm || d > 14) return null;
                    const n = (vm.$options && (vm.$options.name || vm.$options.__file)) || null;
                    if (n === 'PcReadIndex') return vm;
                    if (vm.$data && Array.isArray(vm.$data.listData)) return vm;
                    for (const c of (vm.$children || [])) { const r = find(c, d + 1); if (r) return r; }
                    return null;
                }
                const root = document.querySelector('#app');
                const vm = find(root ? root.__vue__ : null, 0);
                if (!vm) return [];
                return (vm.$data.listData || []).map(x => ({
                    id: x.id,
                    name: x.name || '',
                    resource_num: Number(x.resource_num || 0),
                })).filter(x => x.id != null && x.resource_num > 0);
            }""")
            if categories:
                break
            await page.wait_for_timeout(1200)

        if not categories:
            print("[elang] ERROR: no subjects found on the read index")
            await context.close()
            return

        # Deduplicate
        seen = set()
        unique = []
        for c in categories:
            if c["name"] not in seen:
                seen.add(c["name"])
                unique.append(c)
        categories = unique

        if only_subject_ids:
            wanted = {str(s) for s in only_subject_ids}
            categories = [c for c in categories if str(c["id"]) in wanted]
            print(f"[elang] restricted to {len(categories)} subject(s) via --subject-ids")

        print(f"\n{'='*60}")
        print(f"BATCH-ALL: {len(categories)} subjects")
        print(f"{'='*60}")
        total_items = 0
        for c in categories:
            print(f"  [subject_id={c['id']}] {c['name']} ({c['resource_num']} items)")
            total_items += c["resource_num"]
        print(f"{'='*60}")
        print(f"  total items across subjects: {total_items}")

        if subjects_only:
            print("\n[elang] --subjects-only: stopping before any article work")
            await context.close()
            return

        # Restore checkpoint
        checkpoint = {}
        if os.path.exists(CHECKPOINT_FILE):
            with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                checkpoint = json.load(f)
            print(
                f"\n[elang] Resuming: {checkpoint.get('total_submitted', 0)} done, "
                f"{len(checkpoint.get('completed_categories', []))} categories complete"
            )

        total_submitted = checkpoint.get("total_submitted", 0)
        article_counter = total_submitted
        submitted_this_run = 0
        stop_requested = False

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

            if limit is not None and submitted_this_run >= limit:
                print(f"\n[elang] --limit {limit} reached; stopping before {cat_name}")
                break

            print(f"\n{'='*60}")
            print(f"CATEGORY [{cat_idx+1}/{len(categories)}]: {cat_name} (id={cat_id})")
            print(f"{'='*60}")

            # The app token only lasts ~2 hours, so refresh it before it lapses
            # mid-subject rather than failing partway through a long run.
            await ensure_fresh_token(
                page, "https://elang.zju.edu.cn/#/pc/read/index")

            # Navigate: clear page → goto learn URL (twice if CAS redirects to /#/home)
            learn_url = f"https://elang.zju.edu.cn/#/pc/read/learn?subject_id={cat_id}"
            await page.goto("about:blank")
            await page.wait_for_timeout(500)
            await page.goto(learn_url, wait_until="domcontentloaded", timeout=30000)
            # Wait for SPA to render article list (retry with increasing wait)
            for _ in range(CAT_LOAD_RETRIES):
                await page.wait_for_timeout(1000)
                body = await page.evaluate("() => document.body.innerText")
                if "..." not in body and len(body.split("\n")) > 5:
                    break
            # If CAS redirected us to /#/home, retry (2nd goto lands correctly)
            if "/#/home" in page.url or "learn" not in page.url:
                print(f"[elang]   landed on home, retrying...")
                await page.goto(learn_url, wait_until="domcontentloaded", timeout=30000)
                for _ in range(CAT_LOAD_RETRIES):
                    await page.wait_for_timeout(1000)
                    body = await page.evaluate("() => document.body.innerText")
                    if "..." not in body and len(body.split("\n")) > 5:
                        break
            print(f"[elang]   nav URL: {page.url}")

            article_infos = await get_article_list(page)
            print(f"[elang] {len(article_infos)} articles found")

            # Apply the per-run cap: hand over only as many unfinished articles as
            # we are still allowed to submit, keeping finished rows so the
            # positional indices stay valid.
            # `trimmed` records whether we actually left unfinished work behind —
            # that, and not "did we hit the limit", is what decides whether the
            # subject may be marked complete below.
            trimmed = False
            if limit is not None:
                remaining = limit - submitted_this_run
                pending = [a for a in article_infos if not a.get("isCompleted")]
                if len(pending) > remaining:
                    keep = [a for a in article_infos if a.get("isCompleted")]
                    keep += pending[:remaining]
                    keep.sort(key=lambda a: a.get("index", 0))
                    article_infos = keep
                    trimmed = True
                    print(f"[elang] --limit: taking {remaining} unfinished "
                          f"article(s) in this subject, leaving "
                          f"{len(pending) - remaining} for a later run")

            if not article_infos:
                print("[elang] No articles - marking category complete")
                completed_cats.append(cat_id)
                checkpoint["completed_categories"] = completed_cats
                with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
                    json.dump(checkpoint, f, ensure_ascii=False, indent=2)
                continue

            learn_hash = f"/pc/read/learn?subject_id={cat_id}"
            results = await process_articles(
                page, article_infos, article_counter, learn_hash,
                subject_id=cat_id, dry_run=dry_run,
            )

            for r in results:
                if r["status"] == "submitted":
                    article_counter += 1
                    total_submitted += 1
                    submitted_this_run += 1
                elif r["status"] == "dry_run":
                    # A dry run still consumes a whole article's worth of work, so
                    # it must count against --limit. Without this the cap never
                    # triggers in dry-run mode and the run walks every subject.
                    article_counter += 1
                    submitted_this_run += 1

            # Mark the subject complete only when nothing was left behind.
            # `trimmed` records that --limit cut the work short; marking it
            # complete then would make a later full run skip the remainder.
            if trimmed:
                print("[elang] --limit: NOT marking this subject complete "
                      "(unfinished articles remain)")
            else:
                completed_cats.append(cat_id)
            checkpoint["completed_categories"] = completed_cats
            checkpoint["total_submitted"] = total_submitted
            with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
                json.dump(checkpoint, f, ensure_ascii=False, indent=2)

            print_summary(results)

            if limit is not None and submitted_this_run >= limit:
                print(f"\n[elang] --limit {limit} reached; stopping")
                break

            # 50-article user confirmation checkpoint
            if article_counter > 0 and article_counter % CHECKPOINT_INTERVAL == 0:
                print(f"\n{'='*60}")
                print(f"CHECKPOINT: {total_submitted} articles submitted.")
                print(f"Continue? Write to {SIGNAL_FILE}:")
                print(f'  {{"status": "continue"}}  or  {{"status": "stop"}}')
                print(f"{'='*60}")

                cp_data = {"status": "checkpoint", "total_submitted": total_submitted}
                with open(CURRENT_FILE, "w", encoding="utf-8") as f:
                    json.dump(cp_data, f, ensure_ascii=False)
                if os.path.exists(SIGNAL_FILE):
                    os.remove(SIGNAL_FILE)

                data = await wait_for_ai(timeout=3600)
                if data and data.get("status") == "stop":
                    print("[elang] Stopped. Progress saved.")
                    stop_requested = True
                    break
                print("[elang] Continuing...")

        if stop_requested:
            await context.close()
            return

        done_cats = len(checkpoint.get("completed_categories", []))
        print(
            f"\n[elang] Run finished. This run: {submitted_this_run} article(s) "
            f"(submitted {total_submitted} total) across {done_cats}/"
            f"{len(categories)} subjects marked complete."
        )
        await asyncio.sleep(3)
        await context.close()


# ============================================================
# Single-article solve mode
# ============================================================


async def mode_solve(url, dry_run=False):
    """Process a single article: extract, wait for AI, submit."""
    Path(SCRATCH_DIR).mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        context, page, restored = await open_browser(p)
        await ensure_logged_in(page, url, restored)

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
            "status": "waiting_for_ai",
        }

        data = await request_ai_answers(article_data)
        if not data or data.get("status") not in ("answers_ready", "skip"):
            print("[elang] Timeout.")
            await context.close()
            return

        if data.get("status") == "answers_ready" and data.get("answers") is not None:
            await set_answers(page, data["answers"])
        await page.wait_for_timeout(500)
        await submit(page, dry_run=dry_run)
        await page.wait_for_timeout(3000)

        print(f"\n[elang] Done!")
        await asyncio.sleep(10)
        await context.close()


# ============================================================
# Single-category batch mode
# ============================================================


async def mode_batch(learn_url, dry_run=False):
    """Process all articles in a single category."""
    Path(SCRATCH_DIR).mkdir(parents=True, exist_ok=True)

    # accept a full learn URL or a bare subject_id, and remember the id so we can
    # navigate back to the list between articles
    if "subject_id=" in learn_url:
        subject_id = learn_url.split("subject_id=")[1].split("&")[0]
    else:
        subject_id = str(learn_url).strip()
        learn_url = f"https://elang.zju.edu.cn/#/pc/read/learn?subject_id={subject_id}"

    async with async_playwright() as p:
        context, page, restored = await open_browser(p)
        await ensure_logged_in(page, learn_url, restored)
        learn_hash = learn_url.split("#", 1)[1] if "#" in learn_url else ""

        for _ in range(CAT_LOAD_RETRIES):
            await page.wait_for_timeout(800)
            text = await page.evaluate("() => document.body.innerText")
            if "..." not in text and len(text.split("\n")) > 10:
                break

        article_infos = await get_article_list(page)
        print(f"\n[elang] {len(article_infos)} articles")

        results = await process_articles(page, article_infos, 0, learn_hash,
                                         subject_id=subject_id, dry_run=dry_run)
        print_summary(results)
        await asyncio.sleep(10)
        await context.close()


# ============================================================
# CLI entry point
# ============================================================


def _flag_value(name):
    """Read `--name value` out of argv, or None."""
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None


def main():
    if len(sys.argv) < 2:
        print("HuixueWaiyu Reading Part - Auto Solver")
        print("  solve <praxis-url>            Single article")
        print("  batch <learn-url|subject_id>  One subject (all its articles)")
        print("  batch-all [start-subject]     Every subject on the read index")
        print("\nFlags:")
        print("  --dry-run             open the confirm dialog but do NOT post")
        print("  --limit N             batch-all: submit at most N articles")
        print("  --subjects-only       batch-all: list subjects, then exit")
        print("  --subject-ids 26,1879 batch-all: only these subject ids")
        print("  captcha-solve         Inspect a pending captcha request")
        sys.exit(1)

    mode = sys.argv[1]
    dry_run = "--dry-run" in sys.argv
    subjects_only = "--subjects-only" in sys.argv
    limit = _flag_value("--limit")
    limit = int(limit) if limit and limit.isdigit() else None
    ids_raw = _flag_value("--subject-ids")
    only_ids = [s.strip() for s in ids_raw.split(",")] if ids_raw else None

    if mode == "solve":
        url = sys.argv[2] if len(sys.argv) > 2 else input("Praxis URL: ")
        asyncio.run(mode_solve(url, dry_run=dry_run))
    elif mode == "batch":
        url = sys.argv[2] if len(sys.argv) > 2 else input("Learn URL: ")
        asyncio.run(mode_batch(url, dry_run=dry_run))
    elif mode == "batch-all":
        # Only treat argv[2] as a start index when it is a bare number, so flags
        # like --limit are not mistaken for it.
        arg2 = sys.argv[2] if len(sys.argv) > 2 else None
        start_cat = int(arg2) - 1 if arg2 and arg2.isdigit() else 0
        asyncio.run(mode_batch_all(start_cat, dry_run=dry_run, limit=limit,
                                   subjects_only=subjects_only,
                                   only_subject_ids=only_ids))
    elif mode == "captcha-solve":
        # Vision hand-off helper. The script writes a request while it waits;
        # a vision model (or the user) reads the image and writes the answer.
        if not os.path.exists(CAPTCHA_REQUEST_FILE):
            print(f"No pending captcha request at {CAPTCHA_REQUEST_FILE}")
            print("(it is created only when ddddocr cannot solve a captcha)")
            sys.exit(0)
        with open(CAPTCHA_REQUEST_FILE, "r", encoding="utf-8") as f:
            req = json.load(f)
        print("Pending captcha request:")
        print(json.dumps(req, ensure_ascii=False, indent=2))
        img = req.get("image_path", CAPTCHA_IMAGE_FILE)
        print(f"\nImage to read : {img}")
        print(f"Answer goes to: {CAPTCHA_ANSWER_FILE}")
        print(f'\n  e.g.  echo {{\"captcha_code\": \"1234\"}} > "{CAPTCHA_ANSWER_FILE}"')
        print("\nThe running script polls that file and submits it automatically.")
    else:
        print(f"Unknown mode: {mode}")
        sys.exit(1)


if __name__ == "__main__":
    main()
