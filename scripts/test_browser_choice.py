#!/usr/bin/env python3
"""Lock the browser-selection rules.

Two ways to get a browser, and the precedence between them, are the whole point:

    ELANG_BROWSER        explicit: chromium | chrome | msedge | a path | a channel
    bundled chromium     the self-contained default when it is installed
    installed Chrome/Edge  used only when no bundled build exists, because that
                         saves a ~683 MB download on a machine that has a browser

Getting the precedence wrong is expensive in both directions: preferring a
missing bundled build breaks the first run, and downloading ~683 MB on a machine
that already has Chrome is pure waste. None of this launches a browser, so the
test runs anywhere.

Run: python scripts/test_browser_choice.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import config  # noqa: E402

results = []
FAKE_SYSTEM = {"channel": "chrome", "label": "Google Chrome",
               "path": r"C:\fake\chrome.exe", "version": "157.0.0.0"}


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    results.append((name, bool(cond)))


def clean_env():
    for k in ("ELANG_BROWSER", "PLAYWRIGHT_BROWSERS_PATH"):
        os.environ.pop(k, None)


def with_system(browsers):
    """Patch system_browsers() so the test does not depend on this machine."""
    orig = config.system_browsers
    config.system_browsers = lambda: list(browsers)
    return orig


def with_find(found):
    """Patch find_system_browser() so a channel can be made 'not installed'."""
    orig = config.find_system_browser
    config.find_system_browser = lambda channel: found
    return orig


scratch = REPO / "temp"
scratch.mkdir(parents=True, exist_ok=True)     # absent in a fresh clone
tmp = Path(tempfile.mkdtemp(prefix="elangbrowser-", dir=str(scratch)))
empty = tmp / "empty-browsers"
empty.mkdir()
fake_cache = tmp / "fake-browsers"
(fake_cache / "chromium-9999").mkdir(parents=True)

real = config.system_browsers()
chrome = next((b for b in real if b["channel"] == "chrome"), None)
edge = next((b for b in real if b["channel"] == "msedge"), None)

try:
    print("=== ELANG_BROWSER is explicit and wins ===")
    clean_env()
    os.environ["ELANG_BROWSER"] = "chromium"
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(empty)
    orig = with_system([FAKE_SYSTEM])
    c = config.browser_choice()
    check("ELANG_BROWSER=chromium -> bundled", c["mode"] == "bundled", c["mode"])
    check("bundled wins over an installed browser", c["mode"] != "system")
    config.system_browsers = orig

    clean_env()
    os.environ["ELANG_BROWSER"] = "chrome"
    orig = with_system([FAKE_SYSTEM])
    c = config.browser_choice()
    check("ELANG_BROWSER=chrome -> system", c["mode"] == "system", c["mode"])
    check("...pins the chrome channel", c["channel"] == "chrome", str(c.get("channel")))
    check("...reason names the variable", "ELANG_BROWSER" in c["reason"], c["reason"])
    config.system_browsers = orig

    clean_env()
    os.environ["ELANG_BROWSER"] = str(Path(sys.executable))
    c = config.browser_choice()
    check("ELANG_BROWSER=<path> -> that executable",
          c["mode"] == "system" and c["path"] == sys.executable,
          f"{c['mode']}/{c.get('path')}")
    check("...no channel when a path is given", not c.get("channel"))

    clean_env()
    os.environ["ELANG_BROWSER"] = str(tmp / "does-not-exist.exe")
    c = config.browser_choice()
    check("ELANG_BROWSER=<missing file> -> none", c["mode"] == "none", c["mode"])
    check("...says the file is missing", "missing" in c["reason"].lower(), c["reason"])

    clean_env()
    os.environ["ELANG_BROWSER"] = "firefox"
    orig = with_system([])
    c = config.browser_choice()
    check("an unlisted channel is passed through unchanged",
          c["mode"] == "system" and c["channel"] == "firefox", str(c))
    config.system_browsers = orig

    print("\n=== automatic: bundled first, installed browser second ===")
    clean_env()
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(fake_cache)
    orig = with_system([FAKE_SYSTEM])
    c = config.browser_choice()
    check("bundled build present -> bundled", c["mode"] == "bundled", c["mode"])
    check("...names the cache it came from",
          c["cache"].lower() == str(fake_cache).lower(), c["cache"])
    config.system_browsers = orig

    clean_env()
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(empty)
    orig = with_system([FAKE_SYSTEM])
    c = config.browser_choice()
    check("no bundled build -> installed browser", c["mode"] == "system", c["mode"])
    check("...explains why", "no bundled" in c["reason"].lower(), c["reason"])
    config.system_browsers = orig

    clean_env()
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(empty)
    orig = with_system([])
    c = config.browser_choice()
    check("nothing available -> none", c["mode"] == "none", c["mode"])
    config.system_browsers = orig

    print("\n=== launch kwargs ===")
    clean_env()
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(empty)
    orig = with_system([FAKE_SYSTEM])
    c = config.browser_choice()
    kw = config.browser_launch_kwargs(c)
    check("system browser launches by executable_path",
          kw.get("executable_path") == FAKE_SYSTEM["path"], str(kw))
    config.system_browsers = orig

    clean_env()
    os.environ["ELANG_BROWSER"] = "chrome"
    orig = with_find(None)          # channel cannot be located -> pass channel through
    kw = config.browser_launch_kwargs(config.browser_choice())
    check("unlocated channel still passes channel=", kw.get("channel") == "chrome",
          str(kw))
    config.find_system_browser = orig

    clean_env()
    os.environ["ELANG_BROWSER"] = "chromium"
    kw = config.browser_launch_kwargs(config.browser_choice())
    check("bundled adds no launch kwarg", kw == {}, str(kw))

    print("\n=== detection on this machine ===")
    clean_env()
    desc = config.describe_browser()
    check("describe reports the choice", "choice" in desc, desc.splitlines()[-1])
    if chrome:
        found = config.find_system_browser("chrome")
        check("finds the installed Chrome", bool(found), found["path"])
        check("reads a plausible version",
              bool(found["version"]) and found["version"].count(".") >= 2,
              found["version"])
    else:
        print("  [SKIP] no Chrome installed here")
    if edge:
        alias = config.find_system_browser("edge")
        check("accepts the 'edge' alias", bool(alias) and alias["channel"] == "msedge",
              alias and alias["path"])
    else:
        print("  [SKIP] no Edge installed here")
    check("unknown channel -> None", config.find_system_browser("safari") is None)
finally:
    clean_env()
    shutil.rmtree(tmp, ignore_errors=True)

bad = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(bad)}/{len(results)} passed")
if bad:
    print("FAILED:")
    for n in bad:
        print(f"  - {n}")
    sys.exit(1)
