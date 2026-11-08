#!/usr/bin/env python3
"""Build the offline Windows bundle for elang.

Produces a directory (and a zip) that installs elang with NO network access:

    elang-bundle-win64.zip
    ├─ cpython-<ver>+<tag>-x86_64-pc-windows-msvc-install_only_stripped.tar.gz
    ├─ wheels/            every dependency as a wheel (win_amd64, cp3xx)
    ├─ install.cmd        wrapper
    ├─ install.ps1        the installer
    ├─ SHA256SUMS         hashes for the runtime and every wheel
    └─ VERSION            bundle/package version, shown by install.ps1

Design notes
------------
* The runtime is python-build-standalone's ``install_only_stripped`` build: ~21 MB
  compressed, no installer, no admin rights, ships its own pip.
* The runtime archive is kept COMPRESSED in the bundle and extracted by
  ``install.ps1`` via the ``tar.exe`` that ships with Windows 10 1803+.
* Wheels are resolved for win_amd64 + one CPython minor version, so the same
  bundle works on any Windows 10/11 x64 machine with that runtime.
* The browser is NOT bundled: elang already prefers an installed Chrome/Edge
  (``config.browser_choice()``), so a user with Chrome needs no extra download.
  OCR (ddddocr + onnxruntime + opencv, ~275 MB) is deliberately excluded; see
  ``--with-ocr`` for a private build.

Usage
-----
    python tools/bootstrap/build_bundle.py --wheel dist/elang_reading-*.whl
    python tools/bootstrap/build_bundle.py --wheel ... --out build/bundle
    python tools/bootstrap/build_bundle.py --wheel ... --with-ocr      # heavy
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
HERE = Path(__file__).resolve().parent
PBA_LATEST = ("https://raw.githubusercontent.com/astral-sh/"
              "python-build-standalone/latest-release/latest-release.json")
PBA_ASSET_URL = ("https://github.com/astral-sh/python-build-standalone/"
                 "releases/download/{tag}/{name}")


def log(msg):
    print(f"  {msg}", flush=True)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "elang-build"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def http_download(url, dest):
    log(f"downloading {Path(dest).name}")
    req = urllib.request.Request(url, headers={"User-Agent": "elang-build"})
    with urllib.request.urlopen(req, timeout=900) as r, open(dest, "wb") as f:
        for chunk in iter(lambda: r.read(1 << 20), b""):
            f.write(chunk)


def resolve_runtime(py_minor, tag):
    """Return (tag, asset_name, url) for python-build-standalone on Windows x64."""
    if not tag:
        tag = http_json(PBA_LATEST)["tag"]
    base = f"https://github.com/astral-sh/python-build-standalone/releases/expanded_assets/{tag}"
    req = urllib.request.Request(base, headers={"User-Agent": "Mozilla/5.0"})
    html = urllib.request.urlopen(req, timeout=90).read().decode("utf-8", "replace")

    import re as _re
    names = _re.findall(r'href="[^"]*?/(cpython-[^"]+?)"', html)
    want_prefix = f"cpython-{py_minor}."
    cands = [n for n in names
             if n.startswith(want_prefix)
             and "x86_64-pc-windows-msvc" in n
             and n.endswith("-install_only_stripped.tar.gz")]
    if not cands:
        cands = [n for n in names
                 if n.startswith(want_prefix)
                 and "x86_64-pc-windows-msvc" in n
                 and n.endswith("-install_only.tar.gz")]
    if not cands:
        raise SystemExit(f"no Windows runtime asset for Python {py_minor} in tag {tag}")
    name = sorted(cands)[-1]          # latest patch level wins
    return tag, name, PBA_ASSET_URL.format(tag=tag, name=name)


def build_wheelhouse(wheel, out_dir, py_minor, with_ocr):
    """Download every dependency as a wheel for win_amd64 + this CPython minor."""
    venv = out_dir / "wheels"
    venv.mkdir(parents=True, exist_ok=True)
    abi = "cp" + py_minor.replace(".", "")
    cmd = [sys.executable, "-m", "pip", "download",
           "--dest", str(venv),
           "--only-binary=:all:",
           "--platform", "win_amd64",
           "--python-version", py_minor,
           "--implementation", "cp",
           "--abi", abi,
           str(wheel)]
    if with_ocr:
        cmd += ["ddddocr", "Pillow"]
    log(" ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise SystemExit("pip download failed:\n" + (r.stdout or "") + (r.stderr or ""))
    return venv


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wheel", required=True, help="built elang wheel (.whl)")
    ap.add_argument("--out", default=str(REPO / "build" / "bundle"),
                    help="output directory for the bundle")
    ap.add_argument("--python", default="3.13", help="runtime CPython minor, e.g. 3.13")
    ap.add_argument("--pba-tag", default="", help="pin python-build-standalone tag")
    ap.add_argument("--with-ocr", action="store_true",
                    help="also bundle ddddocr + Pillow (~275 MB); off by default")
    ap.add_argument("--no-zip", action="store_true", help="skip creating the zip")
    args = ap.parse_args()

    wheel = Path(args.wheel).resolve()
    if not wheel.is_file():
        raise SystemExit(f"wheel not found: {wheel}")
    out = Path(args.out).resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    print("=" * 64)
    print("  elang offline bundle")
    print("=" * 64)
    log(f"wheel : {wheel.name}")
    log(f"out   : {out}")

    # ---- runtime ----
    print("\n[1/5] runtime")
    tag, name, url = resolve_runtime(args.python, args.pba_tag)
    log(f"tag   : {tag}")
    log(f"asset : {name}")
    runtime = out / name
    http_download(url, runtime)
    log(f"size  : {runtime.stat().st_size / 1048576:.1f} MB")

    # ---- wheels ----
    print("\n[2/5] dependencies")
    wheels = build_wheelhouse(wheel, out, args.python, args.with_ocr)
    whl_files = sorted(wheels.glob("*.whl"))
    total = sum(p.stat().st_size for p in whl_files)
    log(f"{len(whl_files)} wheel(s), {total / 1048576:.1f} MB")
    if not any(p.name.startswith("playwright-") for p in whl_files):
        raise SystemExit("playwright wheel missing from the wheelhouse")

    # ---- scripts ----
    print("\n[3/5] installer")
    for name_ in ("install.cmd", "install.ps1"):
        shutil.copy2(HERE / name_, out / name_)
        log(f"copied {name_}")

    # ---- checksums + version ----
    print("\n[4/5] manifest")
    lines, count = [], 0
    for p in sorted(out.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(out).as_posix()
        if rel in ("SHA256SUMS", "VERSION"):
            continue
        lines.append(f"{sha256(p)}  {rel}")
        count += 1
    (out / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="ascii")
    version = wheel.stem.split("-")[1] if "-" in wheel.stem else "0.0.0"
    (out / "VERSION").write_text(f"{version}\n", encoding="ascii")
    log(f"version   : {version}")
    log(f"checksums : {count} file(s)")

    # ---- zip ----
    bundle_size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    print("\n[5/5] package")
    log(f"bundle dir: {bundle_size / 1048576:.1f} MB")
    if not args.no_zip:
        zip_path = out.parent / "elang-bundle-win64.zip"
        if zip_path.exists():
            zip_path.unlink()
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED,
                             compresslevel=6) as z:
            for p in sorted(out.rglob("*")):
                if p.is_file():
                    z.write(p, p.relative_to(out).as_posix())
        log(f"zip       : {zip_path} "
            f"({zip_path.stat().st_size / 1048576:.1f} MB)")
        log(f"zip sha256: {sha256(zip_path)}")
    print("\n  done.")


if __name__ == "__main__":
    main()