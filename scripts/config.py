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
import os
import sys
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


def parse_env_file(path):
    """Minimal .env reader: KEY=VALUE, # comments, optional quotes.

    Deliberately not python-dotenv: this must work even when the dependency is
    unavailable, and the format used here is trivial. A UTF-8 BOM is tolerated
    because PowerShell's Out-File adds one.
    """
    out = {}
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except Exception:
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


def load_credentials():
    """Resolve CAS credentials.

    Returns a dict:
        username, password, env_file, source, username_from, password_from, ok
    `*_from` is "environment" or "file:KEY" so a caller can explain where a value
    came from without re-deriving it.
    """
    path, source = resolve_env_file()
    file_vars = parse_env_file(path)

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
    }


def write_env_template(path=None, force=False):
    """Create a .env template. Returns (path, created)."""
    target = Path(path).expanduser() if path else resolve_env_file()[0]
    if target.exists() and not force:
        return target, False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "# 慧学外语 CAS 凭据\n"
        "# 这个文件属于工作区，请勿提交到版本库。\n"
        "CAS_USERNAME=你的学号\n"
        "CAS_PASSWORD=你的密码\n",
        encoding="utf-8",
    )
    return target, True


# ---------------------------------------------------------------- browser

# The tool's own browser cache, kept next to the profile. Installing here rather
# than into Playwright's SHARED cache avoids two real problems measured on a real
# machine: the shared cache had grown to 1374 MB holding two generations of
# chromium (1217 and 1223, each with full + headless-shell builds), and every
# other Playwright user on the machine reads and writes the same directory.
BROWSERS_DIR = Path.home() / ".elang" / "browsers"


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
    return "\n".join(lines)


def describe():
    """One-line-ish description for doctor output."""
    info = load_credentials()
    lines = [f"env file   : {info['env_file']}  ({info['source']})"]
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
