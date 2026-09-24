"""
Bygger browserudgaven til en midlertidig mappe og tjekker indholdet.
Kræver internet første gang (downloads caches i webapp/.build-cache/).

Kør: python test_build_site.py
"""
import json
import re
import sys
import tempfile
import zipfile
from pathlib import Path

import build_site

PASS, FAIL = [], []


def check(name, condition, detail=""):
    (PASS.append(name) if condition else FAIL.append((name, detail)))
    if not condition:
        print(f"FAIL: {name}  {detail}")


def run():
    out = Path(tempfile.mkdtemp()) / "Gymnastik"
    build_site.build(out)

    check("index.html copied", (out / "index.html").is_file())
    check(".nojekyll present", (out / ".nojekyll").is_file())
    cfg = (out / "config.js").read_text(encoding="utf-8")
    m = re.search(r"window\.PLANNER_CONFIG = (\{.*\});", cfg)
    config = json.loads(m.group(1)) if m else {}
    check("config.js selects browser mode", config.get("mode") == "browser", cfg)
    check("config.js lists the two wheels",
          sorted(config.get("wheels", [])) == ["et_xmlfile-2.0.0-py3-none-any.whl", "openpyxl-3.1.5-py2.py3-none-any.whl"],
          config)
    for whl in config.get("wheels", []):
        check(f"wheel {whl} present", (out / "wheels" / whl).is_file())

    with zipfile.ZipFile(out / "planner.zip") as z:
        names = set(z.namelist())
    check("planner.zip has engine and planner",
          {"engine/__init__.py", "engine/placement.py", "planner/__init__.py", "planner/actions.py", "planner/browser.py"} <= names,
          sorted(names))
    check("planner.zip has no tests or caches", not any("test_" in n or "__pycache__" in n for n in names))

    for f in ["pyodide.js", "pyodide.asm.wasm", "pyodide.asm.mjs", "python_stdlib.zip", "pyodide-lock.json"]:
        check(f"pyodide/{f} present", (out / "pyodide" / f).is_file())
    lock = json.loads((out / "pyodide" / "pyodide-lock.json").read_text(encoding="utf-8"))
    for pkg in ["pandas", "numpy", "python-dateutil", "pytz", "six"]:
        check(f"pyodide wheel for {pkg} present", (out / "pyodide" / lock["packages"][pkg]["file_name"]).is_file())
    check("pyodide lock is for Python 3.14", lock["info"]["python"].startswith("3.14"), lock["info"])

    total = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    biggest = max(f.stat().st_size for f in out.rglob("*") if f.is_file())
    check("site is under GitHub Pages limits (1 GB, 100 MB per file)",
          total < 1_000_000_000 and biggest < 100_000_000, f"total={total} biggest={biggest}")

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return not FAIL


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
