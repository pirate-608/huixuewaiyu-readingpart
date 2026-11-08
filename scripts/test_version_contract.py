#!/usr/bin/env python3
"""Enforce the version contract.

The version appears in several places and they must agree, otherwise a release
ships a tag that disagrees with the code inside it. The chain is:

    pyproject.toml  version            the single source of truth
    src/elang/__init__.py  __version__ must equal it (elang --version reads this)
    git tag                            must be "v" + version
    wheel filename                     elang_reading-<version>-*.whl
    bundle VERSION / /latest.json      both derive from the wheel at build time

This test checks everything that can be checked without cutting a release: the
first three, plus that the docs still document pinning and that CI keeps the tag
guard. The wheel-name and bundle parts are covered by build_bundle.py deriving
them from the wheel.

Run: python scripts/test_version_contract.py
"""
import re
import subprocess
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
results = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    results.append((name, bool(cond)))


def read(p):
    return (REPO / p).read_text(encoding="utf-8")


print("=== pyproject is the single source of truth ===")
proj = tomllib.loads(read("pyproject.toml"))
version = proj["project"]["version"]
check("pyproject has a version", bool(version), version)
check("version looks like PEP 440-ish semver",
      re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.\-]+)?", version) is not None,
      version)

print("\n=== the module agrees with pyproject ===")
m = re.search(r'__version__\s*=\s*"([^"]+)"', read("src/elang/__init__.py"))
check("__init__.py declares __version__", m is not None)
check("__init__ matches pyproject", m and m.group(1) == version,
      f"init={m.group(1) if m else '?'} pyproject={version}")

print("\n=== doctor and the CLI report that same version ===")
sys.path.insert(0, str(REPO / "scripts"))
import doctor  # noqa: E402

check("doctor._version() matches pyproject", doctor._version() == version,
      doctor._version())

env_py = str(REPO / "src")
r = subprocess.run([sys.executable, "-m", "elang.cli", "--version"],
                   capture_output=True, encoding="utf-8", errors="replace",
                   env={"PYTHONPATH": env_py, "PATH": ""})
check("elang --version exits 0", r.returncode == 0, str(r.returncode))
check("elang --version prints the version",
      f"elang {version}" in (r.stdout or ""), (r.stdout or "").strip())

print("\n=== the tag guard is still in CI ===")
wf = read(".github/workflows/release-bundle.yml")
check("CI compares the tag with pyproject", '!= "v$ver"' in wf)
check("CI compares __init__ with pyproject", '"$init" != "$ver"' in wf)

print("\n=== docs still describe how to pin ===")
for doc in ("README.md", "SETUP.md"):
    text = read(doc)
    check(f"{doc} shows @vX.Y.Z pinning",
          re.search(r"\.git@v\d+\.\d+\.\d+", text) is not None)
    check(f"{doc} mentions elang --version or upgrade", "elang --version" in text
          or "uv tool upgrade" in text)

print("\n=== the bundle derives its version from the wheel ===")
bb = read("tools/bootstrap/build_bundle.py")
check("build_bundle writes VERSION from the wheel name",
      'wheel.stem.split("-")[1]' in bb)

print("\n" + "=" * 58)
passed = sum(1 for _, ok in results if ok)
print(f"{passed}/{len(results)} checks passed")
for name, ok in results:
    if not ok:
        print(f"  FAILED: {name}")
sys.exit(0 if passed == len(results) else 1)