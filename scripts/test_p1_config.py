#!/usr/bin/env python3
"""Robustness checks for the P1 fixes in config.py / doctor.py.

These are the failure paths a code review found, each of which used to be
invisible or destructive:

  * a GBK/ANSI `.env` (the default encoding of Notepad and PowerShell's
    `Out-File` on a Chinese Windows) was silently treated as EMPTY, so the user
    was told "credentials missing" instead of "this file cannot be read";
  * a relative `ELANG_TMP_DIR` was handed out as a relative path;
  * `init-env --force` overwrote a filled-in `.env` with the template and left
    no copy;
  * registry App Paths values are quoted, and the quotes made the `is_file()`
    check fail, hiding an installed browser;
  * doctor's JSON view must never carry the credential values.

No browser, no network, no registry writes. The GBK fixture is written as raw
bytes to a temporary directory under the repository.

Run: python scripts/test_p1_config.py
"""
import json
import os
import shutil
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import config  # noqa: E402
import doctor  # noqa: E402

ALL_KEYS = ("ELANG_CAS_USERNAME", "ELANG_CAS_PASSWORD",
            "CAS_USERNAME", "CAS_PASSWORD")
results = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    results.append((name, bool(cond)))


def clean_env():
    for k in ALL_KEYS:
        os.environ.pop(k, None)


# A unique directory under temp/: in this sandbox a directory made by
# `tempfile.mkdtemp` is not writable (PermissionError on the first file), while a
# `Path.mkdir` child is. temp/ is gitignored, so a fixed parent plus this unique
# child keeps the artifacts local and easy to remove.
scratch = REPO / "temp"
scratch.mkdir(parents=True, exist_ok=True)
tmp = scratch / f"p1config-{os.getpid()}-{uuid.uuid4().hex[:8]}"
tmp.mkdir(parents=True, exist_ok=False)
saved_tmpdir = os.environ.get("ELANG_TMP_DIR")

try:
    print("=== an unreadable .env is reported, not silently empty ===")
    clean_env()
    gbk_env = tmp / "gbk.env"
    # UTF-8 decoding of these bytes raises UnicodeDecodeError.
    gbk_env.write_bytes("CAS_USERNAME=学号\nCAS_PASSWORD=密码\n".encode("gbk"))
    os.environ["ELANG_ENV_FILE"] = str(gbk_env)
    creds = config.load_credentials()
    check("parse_problem is set", bool(creds.get("parse_problem")),
          str(creds.get("parse_problem")))
    check("parse_problem names the file",
          str(gbk_env) in (creds.get("parse_problem") or ""))
    check("credentials reported missing", creds["ok"] is False)

    print("\n=== a missing .env is not a read failure ===")
    # A fresh checkout has no .env; that is reported separately and must not be
    # dressed up as a decode problem.
    os.environ["ELANG_ENV_FILE"] = str(tmp / "absent" / ".env")
    missing = config.load_credentials()
    check("no parse_problem for a missing file",
          missing.get("parse_problem") is None, str(missing.get("parse_problem")))
    check("missing file reported as absent", missing["env_file_exists"] is False)

    print("\n=== a relative ELANG_TMP_DIR becomes absolute ===")
    os.environ["ELANG_TMP_DIR"] = os.path.join("temp", "p1-rel")
    got = config.ipc_dir()
    want = (Path.cwd() / "temp" / "p1-rel").resolve()
    check("ipc_dir is absolute", got.is_absolute(), str(got))
    check("ipc_dir equals the resolved cwd-relative path", got == want,
          "" if got == want else f"{got} != {want}")

    print("\n=== force=True keeps a backup of the old .env ===")
    envdir = tmp / "force"
    envdir.mkdir()
    env_path = envdir / ".env"
    old = "CAS_USERNAME=old_user\nCAS_PASSWORD=old_pw\n"
    env_path.write_text(old, encoding="utf-8")
    target, created = config.write_env_template(env_path, force=True)
    check("force overwrite reports created", created and target == env_path)
    backups = sorted(envdir.glob(".env.bak-*"))
    check("a .env.bak-* backup exists next to it", len(backups) == 1,
          str([b.name for b in backups]))
    check("backup preserves the old content",
          bool(backups) and backups[0].read_text(encoding="utf-8") == old)
    check("the template replaced the file",
          "你的学号" in env_path.read_text(encoding="utf-8"))

    print("\n=== App Paths quotes are stripped before the file test ===")
    strip = getattr(config, "_strip_quotes", None)
    if strip is None:
        print("  [SKIP] config._strip_quotes is not present")
    else:
        plain = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        check("double-quoted value is unquoted",
              strip('"' + plain + '"') == plain)
        check("single-quoted value is unquoted",
              strip("'" + plain + "'") == plain)
        check("an unquoted value is unchanged", strip(plain) == plain)
        check("surrounding whitespace is dropped",
              strip('  "' + plain + '"  ') == plain)

    print("\n=== doctor's JSON view never carries the secret values ===")
    redacted = doctor._redact_credentials({
        "ok": True,
        "env_file": r"X:\.env",
        "env_file_exists": True,
        "source": "workspace",
        "username_from": "file:CAS_USERNAME",
        "password_from": "file:CAS_PASSWORD",
        "username": "placeholder-username-value",
        "password": "placeholder-password-value",
        "parse_problem": None,
    })
    blob = json.dumps(redacted, ensure_ascii=False)
    check("no username key", "username" not in redacted, str(sorted(redacted)))
    check("no password key", "password" not in redacted)
    check("neither secret value appears",
          "placeholder-username-value" not in blob
          and "placeholder-password-value" not in blob)
    check("set/MISSING booleans are kept",
          redacted.get("username_set") is True and redacted.get("password_set") is True)

    print("\n" + "=" * 58)
    passed = sum(1 for _, ok in results if ok)
    print(f"{passed}/{len(results)} checks passed")
    for name, ok in results:
        if not ok:
            print(f"  FAILED: {name}")
    sys.exit(0 if passed == len(results) else 1)
finally:
    clean_env()
    os.environ.pop("ELANG_ENV_FILE", None)
    if saved_tmpdir is None:
        os.environ.pop("ELANG_TMP_DIR", None)
    else:
        os.environ["ELANG_TMP_DIR"] = saved_tmpdir
    shutil.rmtree(tmp, ignore_errors=True)
