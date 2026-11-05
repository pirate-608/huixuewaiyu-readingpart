#!/usr/bin/env python3
"""Where credentials come from.

Deliberately tiny. Every agent (DSH, Claude Code, Codex, ...) runs commands with
the workspace root as the working directory — that is their shared contract, not
a guess — so `./.env` is the natural place and needs no discovery machinery.

Resolution order:

    1. $ELANG_ENV_FILE     explicit override
    2. <cwd>/.env          the workspace root
    3. ~/.elang/.env       fallback, so a wrong cwd does not fail mysteriously

and then, for each value, a real environment variable beats the file:

    ELANG_CAS_USERNAME  /  ELANG_CAS_PASSWORD

That last rule matters because an MCP host can inject credentials when it spawns
the server (measured: child processes do receive them), and a stale file must
never override what the host supplied.

No upward directory walking, no agent detection, no pointer files.
"""
import functools
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# The Windows console is GBK here; any Chinese in the output would crash or
# mojibake without this.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

FALLBACK_DIR = Path.home() / ".elang"
FALLBACK_ENV = FALLBACK_DIR / ".env"

# Accepted spellings in the file / environment. The ELANG_-prefixed names avoid
# colliding with other tools that also use CAS_*.
USER_KEYS = ("ELANG_CAS_USERNAME", "CAS_USERNAME")
PASS_KEYS = ("ELANG_CAS_PASSWORD", "CAS_PASSWORD")


def parse_env_file(path, problems=None):
    """Minimal .env reader: KEY=VALUE, # comments, optional quotes.

    Deliberately not python-dotenv: this must work even when the dependency is
    unavailable, and the format used here is trivial. A UTF-8 BOM is tolerated
    because PowerShell's Out-File adds one.

    `problems`, when given, collects one human-readable line per read failure.
    Without it an unreadable file (GBK/ANSI bytes are the common case on a
    Chinese Windows) is indistinguishable from a file with no credentials, and
    the caller reports "credentials missing" instead of the real cause.

    A missing file is NOT a problem: `resolve_env_file()` deliberately returns a
    not-yet-created workspace path on a fresh checkout, and that is reported by
    the caller itself (`env_file_exists`). Only an existing file that cannot be
    read or decoded lands in `problems`.
    """
    out = {}
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return out
    except Exception as e:
        if problems is not None:
            problems.append(f"cannot read {path}: {type(e).__name__}: {e}")
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
            v = v[1:-1]
        if k:
            out[k] = v
    return out


def resolve_env_file():
    """Return (path, source_label). The file need not exist."""
    override = os.environ.get("ELANG_ENV_FILE", "").strip()
    if override:
        return Path(override).expanduser(), "ELANG_ENV_FILE"

    cwd_env = Path.cwd() / ".env"
    if cwd_env.is_file():
        return cwd_env, "workspace"

    if FALLBACK_ENV.is_file():
        return FALLBACK_ENV, "fallback"

    # Nothing exists yet: report the workspace path as the place to create.
    return cwd_env, "workspace (missing)"


def _pick(env, keys):
    for k in keys:
        v = (env.get(k) or "").strip()
        if v:
            return v, k
    return "", None


# ---------------------------------------------------------------- IPC paths

def ipc_dir():
    """Directory holding the file-IPC artifacts.

    Lives here (not in elang_reader) so the answering commands can read and write
    those files WITHOUT importing the automation module, which pulls in Playwright.
    `ELANG_TMP_DIR` overrides; otherwise the platform temp convention is used.

    A relative override is expanded and resolved ONCE, here, so every caller in
    this process works with one absolute directory instead of a path that is
    reinterpreted against whatever cwd happens to be current later.
    """
    override = (os.environ.get("ELANG_TMP_DIR") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path("C:/tmp") if os.name == "nt" else Path("/tmp")


def ipc_file(name):
    return ipc_dir() / name


def load_credentials():
    """Resolve CAS credentials.

    Returns a dict:
        username, password, env_file, source, username_from, password_from, ok,
        parse_problem
    `*_from` is "environment" or "file:KEY" so a caller can explain where a value
    came from without re-deriving it. `parse_problem` is None when the file was
    read (or did not exist), or the reason the file could not be decoded.
    """
    path, source = resolve_env_file()
    problems = []
    file_vars = parse_env_file(path, problems)

    user, u_key = _pick(os.environ, USER_KEYS)
    u_from = "environment" if u_key else None
    if not user:
        user, u_key = _pick(file_vars, USER_KEYS)
        u_from = f"file:{u_key}" if u_key else None

    pwd, p_key = _pick(os.environ, PASS_KEYS)
    p_from = "environment" if p_key else None
    if not pwd:
        pwd, p_key = _pick(file_vars, PASS_KEYS)
        p_from = f"file:{p_key}" if p_key else None

    return {
        "username": user,
        "password": pwd,
        "env_file": str(path),
        "env_file_exists": path.is_file(),
        "source": source,
        "username_from": u_from,
        "password_from": p_from,
        "ok": bool(user and pwd),
        "parse_problem": problems[0] if problems else None,
    }


def write_env_template(path=None, force=False):
    """Create a .env template. Returns (path, created).

    `force=True` replaces an existing file, which may already hold the user's real
    credentials, so keep a timestamped copy next to it first. An unreadable or
    undeletable backup is better surfaced as an error than silently losing the
    only copy of the password.
    """
    target = Path(path).expanduser() if path else resolve_env_file()[0]
    if target.exists() and not force:
        return target, False
    target.parent.mkdir(parents=True, exist_ok=True)
    if force and target.is_file():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(target, target.with_name(f"{target.name}.bak-{stamp}"))
    target.write_text(
        "# 慧学外语 CAS 凭据\n"
        "# 这个文件属于工作区，请勿提交到版本库。\n"
        "#\n"
        "# 键名两套都认（带 ELANG_ 前缀的优先）：\n"
        "#     ELANG_CAS_USERNAME / CAS_USERNAME\n"
        "#     ELANG_CAS_PASSWORD / CAS_PASSWORD\n"
        "# 真实环境变量优先于本文件 —— 两套键名都适用。\n"
        "CAS_USERNAME=你的学号\n"
        "CAS_PASSWORD=你的密码\n",
        encoding="utf-8",
    )
    # The file holds the CAS password in plaintext; keep it owner-only where the
    # platform allows it (POSIX). Windows has no chmod equivalent.
    restrict_to_owner(target)
    return target, True


# ---------------------------------------------------------------- browser

# The tool's own browser cache, kept next to the profile. Installing here rather
# than into Playwright's SHARED cache avoids two real problems measured on a real
# machine: the shared cache had grown to 1374 MB holding two generations of
# chromium (1217 and 1223, each with full + headless-shell builds), and every
# other Playwright user on the machine reads and writes the same directory.
BROWSERS_DIR = Path.home() / ".elang" / "browsers"

# The saved browser session holds cookies (including the CAS session cookie) and the
# app's `authorization` JWT in plaintext. That is login state, not the CAS password,
# but it still lets anyone holding the file act as the user until it expires — so it
# must NOT sit in a world-readable temp directory. Keep it next to the browser
# profile, in the user's own home, and tighten permissions on write.
SESSION_FILE = Path.home() / ".elang" / "session.json"
# Where it used to live (IPC temp dir); still read so an existing login is not lost.
LEGACY_SESSION_NAME = "elang_session.json"


def restrict_to_owner(path):
    """Best-effort: make a file readable only by its owner.

    POSIX honours 0o600. Windows has no chmod equivalent (it only toggles the
    read-only bit), so this is a no-op there — the protection there comes from the
    file living inside the user's own profile directory.
    """
    try:
        if os.name != "nt":
            os.chmod(path, 0o600)
    except Exception:
        pass


def shared_browsers_dir():
    """Playwright's default shared cache for this platform."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "ms-playwright"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    return Path.home() / ".cache" / "ms-playwright"


def browser_search_paths():
    """Where to look for browser builds, most-preferred first.

    An explicit PLAYWRIGHT_BROWSERS_PATH wins outright (Playwright's own
    convention). Otherwise the tool's private cache is preferred, with the shared
    cache as a fallback so an existing working installation is REUSED instead of
    triggering a redundant ~683 MB download.
    """
    override = (os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "").strip()
    if override and override != "0":
        return [Path(override).expanduser()]
    return [BROWSERS_DIR, shared_browsers_dir()]


def has_browser(paths=None):
    """True when some candidate directory holds at least one chromium build."""
    for p in (paths or browser_search_paths()):
        try:
            if p.is_dir() and any(p.glob("chromium-*")):
                return True
        except Exception:
            continue
    return False


# ------------------------------------------------------- installed browsers
# A machine that already has Chrome installed should not download ~683 MB of
# chromium. Measured here (Playwright 1.60, bundled chromium 148 = Chrome 148):
# system Chrome 157 and Edge 156 both launch through `launch_persistent_context`,
# headless and headed, execute the site's Vue code, and can share ONE profile
# directory with the bundled build in either direction. So reusing them is a
# supported option, not an escape hatch.
#
# Detection is by PATH, deliberately not by asking Playwright: `channel="chrome"`
# relies on Playwright's own registry lookup, which misses non-standard installs
# (scoop, portable copies, tarballs). Finding the executable ourselves and
# passing `executable_path` covers all of them; `channel` is only used when the
# user names a channel we could NOT locate, so the old behaviour still applies.

SYSTEM_CHANNELS = ("chrome", "msedge")
SYSTEM_LABELS = {"chrome": "Google Chrome", "msedge": "Microsoft Edge"}


def _windows_file_version(path):
    """Product version of a Windows executable, or "" when it cannot be read."""
    try:
        import ctypes
        from ctypes import wintypes

        ver = ctypes.WinDLL("version")
        size = ver.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return ""
        buf = ctypes.create_string_buffer(size)
        if not ver.GetFileVersionInfoW(str(path), 0, size, buf):
            return ""
        ptr = ctypes.c_void_p()
        length = wintypes.UINT()
        if not ver.VerQueryValueW(buf, "\\", ctypes.byref(ptr),
                                 ctypes.byref(length)):
            return ""

        class _Fixed(ctypes.Structure):
            _fields_ = [
                ("signature", ctypes.c_uint32), ("struc", ctypes.c_uint32),
                ("file_ms", ctypes.c_uint32), ("file_ls", ctypes.c_uint32),
                ("prod_ms", ctypes.c_uint32), ("prod_ls", ctypes.c_uint32),
                ("flags_mask", ctypes.c_uint32), ("flags", ctypes.c_uint32),
                ("os", ctypes.c_uint32), ("type", ctypes.c_uint32),
                ("subtype", ctypes.c_uint32), ("date_ms", ctypes.c_uint32),
                ("date_ls", ctypes.c_uint32),
            ]

        info = ctypes.cast(ptr, ctypes.POINTER(_Fixed)).contents
        return (f"{info.prod_ms >> 16}.{info.prod_ms & 0xFFFF}."
                f"{info.prod_ls >> 16}.{info.prod_ls & 0xFFFF}")
    except Exception:
        return ""


def exe_version(path):
    """Best-effort version string for a browser executable.

    Windows: read the PE version resource (the exe detaches from the console, so
    `--version` prints nothing there). macOS/Linux: ask the binary. A failure
    here is cosmetic — detection never depends on it.

    Cached per path: one `doctor`/`install-browser` run probes both browsers
    several times and each probe reopens the PE resource or spawns the binary.
    """
    return _exe_version_cached(str(path))


@functools.lru_cache(maxsize=64)
def _exe_version_cached(path_str):
    path = Path(path_str)
    if os.name == "nt":
        return _windows_file_version(path)
    try:
        out = subprocess.run([str(path), "--version"], capture_output=True,
                             text=True, timeout=10).stdout
        m = re.search(r"(\d+(?:\.\d+){2,})", out or "")
        return m.group(1) if m else ""
    except Exception:
        return ""


def _browser_candidates():
    """Plausible install locations per channel, most authoritative first."""
    out = {"chrome": [], "msedge": []}
    if os.name == "nt":
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        local = os.environ.get("LOCALAPPDATA", "")
        out["chrome"] = [rf"{pf}\Google\Chrome\Application\chrome.exe",
                         rf"{pf86}\Google\Chrome\Application\chrome.exe",
                         rf"{local}\Google\Chrome\Application\chrome.exe"]
        out["msedge"] = [rf"{pf86}\Microsoft\Edge\Application\msedge.exe",
                         rf"{pf}\Microsoft\Edge\Application\msedge.exe",
                         rf"{local}\Microsoft\Edge\Application\msedge.exe"]
    elif sys.platform == "darwin":
        out["chrome"] = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            str(Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        ]
        out["msedge"] = [
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            str(Path.home() / "Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        ]
    else:
        out["chrome"] = ["/usr/bin/google-chrome", "/usr/bin/google-chrome-stable",
                         "/opt/google/chrome/chrome", "/usr/bin/chromium",
                         "/usr/bin/chromium-browser", "/snap/bin/chromium"]
        out["msedge"] = ["/usr/bin/microsoft-edge", "/usr/bin/microsoft-edge-stable",
                         "/opt/microsoft/msedge/msedge"]
    return out


def _strip_quotes(value):
    """Drop a matching pair of surrounding quotes from a registry value.

    App Paths values are usually stored as `"C:\\Program Files\\...\\chrome.exe"`.
    `Path('"C:\\...exe"').is_file()` is then False, which used to hide an
    installed browser from detection.
    """
    if not isinstance(value, str):
        return value
    v = value.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
        return v[1:-1]
    return v


@functools.lru_cache(maxsize=1)
def _windows_app_paths():
    """Executables advertised by the registry's App Paths keys.

    Cached for the process: one run calls detection several times (choice,
    describe, doctor), and each call used to reopen four registry keys.
    """
    try:
        import winreg
    except Exception:
        return {}
    found = {}
    base = r"Software\Microsoft\Windows\CurrentVersion\App Paths"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for exe, channel in (("chrome.exe", "chrome"), ("msedge.exe", "msedge")):
            if channel in found:
                continue
            try:
                with winreg.OpenKey(hive, base + "\\" + exe) as k:
                    value = _strip_quotes(winreg.QueryValueEx(k, None)[0])
                if value and Path(value).is_file():
                    found[channel] = value
            except Exception:
                continue
    return found


def find_system_browser(channel):
    """Locate an installed browser. Returns a dict, or None when absent."""
    channel = (channel or "").strip().lower()
    if channel in ("edge", "microsoft edge", "microsoft-edge"):
        channel = "msedge"
    if channel not in SYSTEM_CHANNELS:
        return None

    declared = _windows_app_paths() if os.name == "nt" else {}
    ordered = list(_browser_candidates().get(channel, []))
    if channel in declared:
        ordered.insert(0, declared[channel])

    names = (["chrome.exe", "chrome", "google-chrome", "chromium"]
             if channel == "chrome"
             else ["msedge.exe", "msedge", "microsoft-edge"])
    ordered += [w for w in (shutil.which(n) for n in names) if w]

    seen = set()
    for cand in ordered:
        key = str(cand)
        if not key or key in seen:
            continue
        seen.add(key)
        try:
            if Path(cand).is_file():
                return {"channel": channel, "label": SYSTEM_LABELS[channel],
                        "path": key, "version": exe_version(cand)}
        except Exception:
            continue
    return None


def system_browsers():
    """Installed system browsers, Chrome first."""
    found = []
    for ch in SYSTEM_CHANNELS:
        b = find_system_browser(ch)
        if b:
            found.append(b)
    return found


def _bundled_choice(reason):
    for p in browser_search_paths():
        try:
            if p.is_dir() and any(p.glob("chromium-*")):
                return {"mode": "bundled", "channel": None, "path": None,
                        "label": "bundled chromium", "version": "",
                        "cache": str(p), "reason": reason}
        except Exception:
            continue
    return {"mode": "bundled", "channel": None, "path": None,
            "label": "bundled chromium", "version": "", "cache": "",
            "reason": reason}


def _system_choice(browser, reason):
    return {"mode": "system", "channel": browser["channel"],
            "path": browser["path"], "label": browser["label"],
            "version": browser.get("version", ""), "cache": "",
            "reason": reason}


def browser_choice():
    """Which browser `elang run` will launch, and why.

    Precedence:

      1. ``$ELANG_BROWSER`` — explicit, always wins:

         ======================  ==========================================
         ``chromium``/``bundled`` the tool's own build
         ``chrome``/``msedge``    that installed browser
         an executable path       exactly that executable
         anything else            passed to Playwright as a channel unchanged
         ======================  ==========================================

      2. a bundled chromium build, when one is installed (self-contained default)
      3. an installed Chrome/Edge when there is no bundled build — this is what
         saves the ~683 MB download on a machine that already has a browser
      4. nothing: report it, and `elang install-browser` fixes it
    """
    raw = (os.environ.get("ELANG_BROWSER") or "").strip()
    if raw:
        low = raw.lower()
        if low in ("chromium", "bundled", "chromium-bundled"):
            return _bundled_choice("ELANG_BROWSER=" + raw)
        if os.sep in raw or "/" in raw or low.endswith((".exe", ".app")):
            p = Path(raw).expanduser()
            if not p.is_file():
                return {"mode": "none", "channel": None, "path": None,
                        "label": p.name, "version": "", "cache": "",
                        "reason": f"ELANG_BROWSER points at a missing file: {p}"}
            return {"mode": "system", "channel": None, "path": str(p),
                    "label": p.name, "version": exe_version(p), "cache": "",
                    "reason": "ELANG_BROWSER=" + raw}
        found = find_system_browser(low)
        if found:
            return _system_choice(found, "ELANG_BROWSER=" + raw)
        # Unlisted channel name: hand it to Playwright verbatim, which is exactly
        # what the old escape hatch did.
        return {"mode": "system", "channel": raw, "path": None,
                "label": raw, "version": "", "cache": "",
                "reason": "ELANG_BROWSER=" + raw}

    if has_browser():
        return _bundled_choice("a bundled chromium build is installed")
    found = system_browsers()
    if found:
        return _system_choice(
            found[0], "no bundled chromium; using the installed browser")
    return {"mode": "none", "channel": None, "path": None, "label": "none",
            "version": "", "cache": "",
            "reason": "no bundled chromium and no system Chrome/Edge"}


def browser_launch_kwargs(choice=None):
    """Playwright launch kwargs that select the chosen browser."""
    choice = choice or browser_choice()
    if choice.get("mode") == "system":
        if choice.get("path"):
            return {"executable_path": choice["path"]}
        if choice.get("channel"):
            return {"channel": choice["channel"]}
    return {}


def describe_browser():
    """Report the browser situation without launching anything."""
    override = (os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "").strip()
    lines = []
    if override:
        lines.append(f"browsers path: {override}  (from PLAYWRIGHT_BROWSERS_PATH)")
    lines.append(f"private cache: {BROWSERS_DIR}  "
                 f"({'present' if BROWSERS_DIR.is_dir() else 'absent'})")
    lines.append(f"shared cache : {shared_browsers_dir()}  "
                 f"({'present' if shared_browsers_dir().is_dir() else 'absent'})")
    lines.append(f"usable       : {has_browser()}")
    browsers = system_browsers()          # one scan, not one scan per line
    for b in browsers:
        lines.append(f"system {b['channel']:<10}: {b['path']}"
                     f"  v{b['version'] or '?'}")
    if not browsers:
        lines.append("system       : no installed Chrome/Edge found")
    ch = browser_choice()
    detail = ch["label"] + (f" v{ch['version']}" if ch["version"] else "")
    lines.append(f"choice       : {ch['mode']} — {detail} ({ch['reason']})")
    return "\n".join(lines)


def describe():
    """One-line-ish description for doctor output."""
    info = load_credentials()
    lines = [f"env file   : {info['env_file']}  ({info['source']})"]
    if info.get("parse_problem"):
        lines.append(f"             -> 读取失败: {info['parse_problem']}")
    if not info["env_file_exists"]:
        lines.append("             -> 文件不存在，可用 `init-env` 生成模板")
    else:
        lines.append(f"username   : {'set' if info['username'] else 'MISSING'}"
                     f"{'  from ' + info['username_from'] if info['username_from'] else ''}")
        lines.append(f"password   : {'set' if info['password'] else 'MISSING'}"
                     f"{'  from ' + info['password_from'] if info['password_from'] else ''}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(describe())
