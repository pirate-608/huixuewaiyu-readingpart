#!/usr/bin/env python3
"""Lock the credential variable naming rules.

The tool accepts TWO spellings for both credentials, from BOTH sources:

    ELANG_CAS_USERNAME  /  CAS_USERNAME
    ELANG_CAS_PASSWORD  /  CAS_PASSWORD

That is deliberate, not an accident or a leftover:

  * `.env` files use the bare names — short, and compatible with configurations
    created before the ELANG_ prefix existed
  * environment variables use the prefixed names — a process environment is shared
    with other tools, and a bare `CAS_USERNAME` could collide

Both sources accept both spellings, the prefixed one wins when both are present,
and a real environment variable always beats the file. This test pins all of that,
plus the requirement that the docs and the generated template describe it the same
way — the original confusion was that the template wrote `CAS_*` while the docs
only mentioned `ELANG_CAS_*`.

Run: python scripts/test_env_names.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import config  # noqa: E402

ALL_KEYS = ("ELANG_CAS_USERNAME", "ELANG_CAS_PASSWORD",
            "CAS_USERNAME", "CAS_PASSWORD")
results = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    results.append((name, bool(cond)))


def clean_env():
    for k in ALL_KEYS:
        os.environ.pop(k, None)


def resolve(env_text):
    """Write an .env with `env_text` and resolve credentials with a clean environment."""
    clean_env()
    path.write_text(env_text, encoding="utf-8")
    return config.load_credentials()


tmp = Path(tempfile.mkdtemp(prefix="elangenv-", dir=str(REPO / "temp")))
path = tmp / ".env"
os.environ["ELANG_ENV_FILE"] = str(path)
try:
    print("=== both spellings work from the FILE ===")
    c = resolve("CAS_USERNAME=bare\nCAS_PASSWORD=bpw\n")
    check("bare names in file", (c["username"], c["password"]) == ("bare", "bpw"),
          f"{c['username']}/{c['username_from']}")

    c = resolve("ELANG_CAS_USERNAME=pref\nELANG_CAS_PASSWORD=ppw\n")
    check("prefixed names in file", (c["username"], c["password"]) == ("pref", "ppw"),
          f"{c['username']}/{c['username_from']}")

    c = resolve("CAS_USERNAME=bare\nELANG_CAS_USERNAME=pref\n")
    check("prefixed wins in file", c["username"] == "pref", c["username_from"])

    print("\n=== both spellings work from the ENVIRONMENT ===")
    clean_env()
    path.write_text("", encoding="utf-8")
    os.environ["CAS_USERNAME"] = "env_bare"
    os.environ["CAS_PASSWORD"] = "env_bpw"
    c = config.load_credentials()
    check("bare names in environment", c["username"] == "env_bare")
    check("source reported as environment", c["username_from"] == "environment")

    clean_env()
    os.environ["ELANG_CAS_USERNAME"] = "env_pref"
    os.environ["ELANG_CAS_PASSWORD"] = "env_ppw"
    c = config.load_credentials()
    check("prefixed names in environment", c["username"] == "env_pref")

    clean_env()
    os.environ["CAS_USERNAME"] = "env_bare"
    os.environ["ELANG_CAS_USERNAME"] = "env_pref"
    c = config.load_credentials()
    check("prefixed wins in environment", c["username"] == "env_pref")

    print("\n=== environment beats the file, either spelling ===")
    clean_env()
    path.write_text("CAS_USERNAME=file_user\nCAS_PASSWORD=file_pw\n", encoding="utf-8")
    os.environ["CAS_USERNAME"] = "env_bare"
    c = config.load_credentials()
    check("bare env beats file", c["username"] == "env_bare")

    clean_env()
    os.environ["ELANG_CAS_USERNAME"] = "env_pref"
    c = config.load_credentials()
    check("prefixed env beats file", c["username"] == "env_pref")

    print("\n=== partial configuration is reported honestly ===")
    clean_env()
    path.write_text("CAS_USERNAME=only_user\n", encoding="utf-8")
    c = config.load_credentials()
    check("username found, password missing",
          c["username"] == "only_user" and not c["password"] and not c["ok"])

    print("\n=== the generated template documents both spellings ===")
    clean_env()
    tpl_dir = tmp / "gen"
    tpl_path, created = config.write_env_template(tpl_dir / ".env")
    tpl = tpl_path.read_text(encoding="utf-8")
    check("template created", created)
    check("template writes the bare key", "CAS_USERNAME=你的学号" in tpl)
    check("template mentions the prefixed key", "ELANG_CAS_USERNAME" in tpl)
    check("template states the precedence", "优先" in tpl or "wins" in tpl)

    print("\n=== docs describe it the same way ===")
    for name in ("SKILL.md", "SETUP.md", "README.md", "CLAUDE.md", ".env.example"):
        text = (REPO / name).read_text(encoding="utf-8")
        # Whole document: the resolution block sits at different depths per file.
        has_bare = "CAS_USERNAME" in text
        has_pref = "ELANG_CAS_USERNAME" in text
        # A doc that names only one spelling is what made this look like a mix-up.
        check(f"{name} mentions both spellings", has_bare and has_pref,
              f"bare={has_bare} prefixed={has_pref}")

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
    shutil.rmtree(tmp, ignore_errors=True)
