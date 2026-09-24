"""
Bygger browserudgaven af opvarmningsplanlæggeren som en statisk side.

    python build_site.py [--out ../site]

Siden kører Python-motoren i browseren med Pyodide. Alt hentes fra siden
selv (ingen CDN ved kørsel): Pyodide-kernen, de nødvendige pakker og
openpyxl/et_xmlfile som wheels. Downloads sker kun her ved build og caches
i webapp/.build-cache/. Hver fil tjekkes mod sin sha256.
"""

import argparse
import hashlib
import json
import shutil
import tarfile
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).parent
CACHE = HERE / ".build-cache"

PYODIDE_VERSION = "314.0.7"
PYODIDE_CORE_URL = (f"https://github.com/pyodide/pyodide/releases/download/"
                    f"{PYODIDE_VERSION}/pyodide-core-{PYODIDE_VERSION}.tar.bz2")
PYODIDE_CDN = f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE_VERSION}/full/"
PYODIDE_PACKAGES = ["pandas"]          # afhængigheder følger af lock-filen
PYPI_WHEELS = {"openpyxl": "3.1.5", "et_xmlfile": "2.0.0"}


def _download(url: str, sha256: str = None) -> Path:
    CACHE.mkdir(exist_ok=True)
    # URL-hash i navnet, så en ny version aldrig genbruger en gammel fil
    target = CACHE / f"{hashlib.sha1(url.encode()).hexdigest()[:8]}_{url.rsplit('/', 1)[1]}"
    if not target.exists():
        print(f"  henter {url}")
        with urllib.request.urlopen(url) as resp, open(target.with_suffix(".part"), "wb") as f:
            shutil.copyfileobj(resp, f)
        target.with_suffix(".part").replace(target)
    if sha256:
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if digest != sha256:
            target.unlink()
            raise RuntimeError(f"Forkert sha256 for {target.name}: {digest} != {sha256}")
    return target


def _pyodide(out: Path) -> None:
    dest = out / "pyodide"
    dest.mkdir(parents=True)
    with tarfile.open(_download(PYODIDE_CORE_URL)) as tar:
        for member in tar.getmembers():
            if member.isfile():
                name = Path(member.name).name   # arkivet har en "pyodide/"-rodmappe
                with tar.extractfile(member) as src, open(dest / name, "wb") as dst:
                    shutil.copyfileobj(src, dst)

    lock_path = _download(PYODIDE_CDN + "pyodide-lock.json")
    shutil.copy(lock_path, dest / "pyodide-lock.json")
    packages = json.loads(lock_path.read_text(encoding="utf-8"))["packages"]

    needed, todo = set(), list(PYODIDE_PACKAGES)
    while todo:
        name = todo.pop()
        if name not in needed:
            needed.add(name)
            todo.extend(packages[name].get("depends", []))
    for name in sorted(needed):
        pkg = packages[name]
        shutil.copy(_download(PYODIDE_CDN + pkg["file_name"], pkg["sha256"]), dest / pkg["file_name"])


def _pypi_wheels(out: Path) -> list:
    dest = out / "wheels"
    dest.mkdir(parents=True)
    names = []
    for project, version in PYPI_WHEELS.items():
        with urllib.request.urlopen(f"https://pypi.org/pypi/{project}/{version}/json") as resp:
            info = json.load(resp)
        wheel = next(u for u in info["urls"] if u["filename"].endswith("-none-any.whl"))
        shutil.copy(_download(wheel["url"], wheel["digests"]["sha256"]), dest / wheel["filename"])
        names.append(wheel["filename"])
    return names


def _planner_zip(out: Path) -> None:
    with zipfile.ZipFile(out / "planner.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for package in ("engine", "planner"):
            for py in sorted((HERE / package).rglob("*.py")):
                z.write(py, py.relative_to(HERE).as_posix())


def build(out: Path) -> None:
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(HERE / "static", out)
    _pyodide(out)
    wheels = _pypi_wheels(out)
    _planner_zip(out)
    (out / "config.js").write_text(
        "// Genereret af build_site.py — browserudgaven.\n"
        f"window.PLANNER_CONFIG = {json.dumps({'mode': 'browser', 'wheels': wheels})};\n",
        encoding="utf-8",
    )
    (out / ".nojekyll").write_text("", encoding="utf-8")   # GitHub Pages: ingen Jekyll
    print(f"Bygget til {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(HERE.parent / "site"))
    build(Path(parser.parse_args().out))
