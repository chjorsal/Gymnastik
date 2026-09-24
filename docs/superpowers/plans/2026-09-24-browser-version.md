# Browserudgave på GitHub Pages — implementeringsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Opvarmningsplanlæggeren kører i browseren på GitHub Pages med den eksisterende Python-motor (via Pyodide), hver brugers plan i egen `localStorage`, mens den lokale FastAPI-server fortsat virker.

**Architecture:** Al logik fra `app.py`'s endpoints flyttes til rene funktioner i `webapp/planner/actions.py`. `app.py` bliver en tynd HTTP-skal om dem, og `webapp/planner/browser.py` er broen, som Pyodide kalder med JSON. Frontenden kalder alt gennem `static/api.js`, som enten bruger HTTP (server) eller Pyodide + `localStorage` (browser). `webapp/build_site.py` samler en statisk side med Pyodide hostet lokalt, og en GitHub Actions-workflow udgiver den.

**Tech Stack:** Python 3.13 (lokalt) / 3.14 (Pyodide), pandas 2.3 (lokalt) / 3.0.2 (Pyodide), openpyxl 3.1.5, FastAPI, Pyodide 314.0.7, vanilla JS, Bootstrap 5 (vendored), Playwright med Edge til browsertest, GitHub Actions + GitHub Pages.

**Spec:** `docs/superpowers/specs/2026-09-24-browser-version-design.md`

## Global Constraints

- Pyodide-version: `314.0.7`. Pakker fra dens lock: `pandas 3.0.2`, `numpy 2.4.6`, `python-dateutil 2.9.0.post0`, `pytz 2026.1.post1`, `six 1.17.0`.
- Fra PyPI som wheels: `openpyxl==3.1.5`, `et_xmlfile==2.0.0`.
- Ingen CDN ved kørsel: alt, siden henter i browseren, ligger på siden selv. Build må hente fra GitHub-release, jsDelivr og PyPI.
- `localStorage`-nøgle for planen: `opvarmning_plan_v1`. Ulæselig plan flyttes til `opvarmning_plan_broken_<unix-ms>`.
- Plan-fil: `opvarmningsplan.json`. Excel-fil: `opvisning_med_opvarmning.xlsx`.
- Ingen cookies, analyse eller sporing.
- Om data-tekst (ordret): "Dine data gemmes kun i denne browser. De sendes ikke til nogen server. Skriv ikke personnavne i Excel-filen."
- Alle brugerrettede tekster er på dansk. Fejlbeskeder fra handlinger er de samme som i dagens `app.py`.
- `engine/` ændres ikke (motoren er verificeret uændret under pandas 3.0.2: 77/77 tests, identiske rækker og tider).
- Serverudgaven (`python app.py`, port 8877, `STATE_FILE`-miljøvariabel) skal virke som i dag.
- Sidens adresse: `https://chjorsal.github.io/Gymnastik/` — alle stier i browserudgaven skal være relative.
- Testfiler må ikke bruge de rigtige Excel-filer i repo-roden (de er gitignored). Testdata laves i koden.

## Review Focus

1. **Gammel eller ufuldstændig plan i `localStorage` eller en `.json`-fil** (manglende nøgler, `show_halls` som strenge) → planen migreres og virker; kun en plan med forkert form afvises med "Filen er ikke en gyldig plan." — test i Task 1 (`migrate`) og Task 4 (`load`/`import_plan`).
2. **`localStorage` kan ikke skrives** (privat vindue, fuld kvote) → appen virker i sessionen, og brugeren får én gang besked om at bruge "Gem plan" — test i Task 6.
3. **Siden er åben i to faner** → ændringer i den ene fane vises i den anden i stedet for at blive overskrevet — test i Task 6.
4. **Ugyldig Excel-fil i browserudgaven** → dansk fejlbesked, planen er uændret — test i Task 1 (actions) og Task 6 (browser).
5. **Pyodide kan ikke hentes** (offline, blokeret) → dansk fejlbesked på indlæsningsskærmen, ingen tom side — test i Task 6.

---

## File Structure

| Fil | Ansvar | Task |
|---|---|---|
| `webapp/planner/__init__.py` | pakke-markør | 1 |
| `webapp/planner/actions.py` | alle handlinger på en plan (rene funktioner) + migrering | 1 |
| `webapp/test_actions.py` | tests af `actions` og `browser` uden server | 1, 4 |
| `webapp/app.py` | tynd FastAPI-skal om `actions` | 2 |
| `webapp/test_api.py` | røgtest af serveren; starter sin egen server | 2 |
| `webapp/static/config.js` | `window.PLANNER_CONFIG` (server-standard) | 3 |
| `webapp/static/api.js` | transport: HTTP eller Pyodide + `localStorage` | 3, 6, 7 |
| `webapp/static/app.js` | brugerflade; kalder `Api` | 3, 6, 7 |
| `webapp/static/index.html` | markup: eksport-knap, indlæsningsskærm, data-sektion | 3, 6, 7 |
| `webapp/static/style.css` | stil for indlæsningsskærm og data-sektion | 6, 7 |
| `webapp/test_e2e.py` | browsertest (Playwright/Edge) mod `server` eller `browser` | 3, 6, 7 |
| `webapp/planner/browser.py` | JSON-bro mellem Pyodide og `actions` | 4 |
| `webapp/build_site.py` | bygger `site/` med Pyodide og wheels | 5 |
| `webapp/test_build_site.py` | tjekker at build indeholder det rigtige | 5 |
| `.github/workflows/pages.yml` | test, build og udgivelse på GitHub Pages | 8 |
| `.gitignore`, `webapp/README.md` | ignorér build-output; dokumentér | 5, 8 |

Kør altid kommandoer fra `webapp/`, medmindre andet står.

---

### Task 1: `planner/actions.py` — handlingerne som rene funktioner

**Files:**
- Create: `webapp/planner/__init__.py`
- Create: `webapp/planner/actions.py`
- Create: `webapp/test_actions.py`

**Interfaces:**
- Consumes: `engine` (uændret): `build_dataframe`, `compute_plan`, `to_row_dicts`, `to_schedule`, `load_excel_bytes`, `clean_hal_name`, `new_special_row`, `classify_type`, `build_workbook`.
- Produces (alle i `planner.actions`; `plan` er en dict med nøglerne `warmup_halls`, `priority_hall`, `show_halls`, `raw_rows`; muterende funktioner ændrer `plan` på stedet og returnerer `None`; fejl kastes som `ActionError` **før** noget ændres):
  - `class ActionError(Exception)` med `.message: str`, `.status: int` (400 eller 404)
  - `new_plan() -> dict`
  - `migrate(data) -> dict` (kaster `ActionError("Filen er ikke en gyldig plan.")`)
  - `import_plan(text: str) -> dict`
  - `payload(plan) -> dict` (nøgler: `warmupHalls`, `priorityHall`, `showHalls`, `rows`, `schedule`)
  - `normalize_hhmm(value) -> Optional[str]`
  - `show_hal_names(plan) -> List[str]`
  - `upload(plan, files: List[Tuple[str, bytes]], show_hal: Optional[str] = None)`
  - `patch_row(plan, row_id, field, value=None)`
  - `delete_row(plan, row_id)`
  - `add_special_row(plan, hal, row_type)`
  - `reorder_rows(plan, hal, ordered_ids)`
  - `swap_warmup_time(plan, dragged_id, target_id)`
  - `reset_rows(plan)`
  - `create_warmup_hall(plan, name)`, `rename_warmup_hall(plan, old_name, new_name)`, `delete_warmup_hall(plan, name)`, `set_priority_hall(plan, name)`
  - `create_show_hall(plan, name)`, `rename_show_hall(plan, old_name, new_name)`, `set_show_hall_start_time(plan, name, start_time)`, `delete_show_hall(plan, name)`
  - `export_xlsx(plan) -> bytes`

- [ ] **Step 1: Write the failing test**

Create `webapp/test_actions.py`:

```python
"""
Tests af planner.actions (og planner.browser) — uden server.

Kør: python test_actions.py
"""
import copy
import json
import sys
from io import BytesIO

import pandas as pd

from planner import actions
from planner.actions import ActionError

PASS = []
FAIL = []


def check(name, condition, detail=""):
    if condition:
        PASS.append(name)
    else:
        FAIL.append((name, detail))
        print(f"FAIL: {name}  {detail}")


def raises(fn, status=None):
    """Kører fn og returnerer ActionError, hvis den kastes (ellers None)."""
    try:
        fn()
    except ActionError as e:
        if status is None or e.status == status:
            return e
        return None
    return None


def excel_bytes(teams):
    """Lav en lille Excel-fil i hukommelsen. teams: [(holdnavn, varighed)]."""
    df = pd.DataFrame({
        "Tid": ["09:00"] + [""] * (len(teams) - 1),
        "Varighed": [v for _, v in teams],
        "Holdnavn": [n for n, _ in teams],
        "Antal deltagere": [20] * len(teams),
        "Alder": ["voksen"] * len(teams),
    })
    buf = BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


def plan_with_halls():
    plan = actions.new_plan()
    actions.create_warmup_hall(plan, "Varm 1")
    actions.create_warmup_hall(plan, "Varm 2")
    actions.create_show_hall(plan, "Sal A")
    actions.create_show_hall(plan, "Sal B")
    return plan


def run():
    # ---------- ny plan og haller ----------
    plan = actions.new_plan()
    check("new_plan is empty", plan == {"warmup_halls": [], "priority_hall": None, "show_halls": [], "raw_rows": []})
    check("new_plan returns a fresh copy", actions.new_plan() is not actions.new_plan())

    actions.create_warmup_hall(plan, "  Varm 1 ")
    actions.create_warmup_hall(plan, "Varm 2")
    actions.create_warmup_hall(plan, "Varm 2")
    actions.create_warmup_hall(plan, "   ")
    check("warm-up halls trimmed, no duplicates or blanks", plan["warmup_halls"] == ["Varm 1", "Varm 2"], plan["warmup_halls"])
    check("first warm-up hall becomes priority", plan["priority_hall"] == "Varm 1")

    actions.set_priority_hall(plan, "Varm 2")
    check("set_priority_hall", plan["priority_hall"] == "Varm 2")
    actions.rename_warmup_hall(plan, "Varm 2", "Varm B")
    check("rename warm-up hall renames priority", plan["priority_hall"] == "Varm B")
    actions.delete_warmup_hall(plan, "Varm B")
    check("delete priority hall moves priority to first remaining", plan["priority_hall"] == "Varm 1")

    actions.create_show_hall(plan, "Sal A")
    actions.create_show_hall(plan, "Sal A")
    check("show hall created once with 09:00", plan["show_halls"] == [{"name": "Sal A", "startTime": "09:00"}])
    actions.set_show_hall_start_time(plan, "Sal A", "9.30")
    check("start time '9.30' -> 09:30", plan["show_halls"][0]["startTime"] == "09:30")
    before = copy.deepcopy(plan)
    err = raises(lambda: actions.set_show_hall_start_time(plan, "Sal A", "abc"), 400)
    check("invalid start time -> ActionError 400 with Danish message",
          err is not None and "gyldigt klokkeslæt" in err.message, err and err.message)
    check("invalid start time leaves plan unchanged", plan == before)

    check("normalize_hhmm variants",
          [actions.normalize_hhmm(v) for v in ["9:30", "09:30", "9.30", "930", "0930", "9", "24:00", "x", ""]]
          == ["09:30", "09:30", "09:30", "09:30", "09:30", "09:00", None, None, None])

    # ---------- upload ----------
    plan = plan_with_halls()
    actions.upload(plan, [("dag.xlsx", excel_bytes([("Hold 1", 10), ("Hold 2", 15)]))], show_hal="Sal A")
    rows = plan["raw_rows"]
    check("upload adds all teams to the chosen hall",
          [(r["Hold"], r["OpvisningHal"], r["Order"]) for r in rows] == [("Hold 1", "Sal A", 0), ("Hold 2", "Sal A", 1)],
          [(r["Hold"], r["OpvisningHal"], r["Order"]) for r in rows])
    check("upload into user-chosen hall keeps its start time", plan["show_halls"][0]["startTime"] == "09:00")

    before = copy.deepcopy(plan)
    err = raises(lambda: actions.upload(plan, [("ok.xlsx", excel_bytes([("X", 5)])), ("skrald.xlsx", b"ikke excel")]), 400)
    check("invalid file -> ActionError naming the file", err is not None and "skrald.xlsx" in err.message, err and err.message)
    check("invalid file in a batch leaves plan unchanged", plan == before)

    plan2 = actions.new_plan()
    actions.upload(plan2, [("202609554902_Lørdag_Arena_færdig.xlsx", excel_bytes([("A", 10)]))])
    check("upload without halls creates hall from cleaned file name",
          plan2["show_halls"] == [{"name": "Arena", "startTime": "09:00"}], plan2["show_halls"])

    # ---------- rækker ----------
    plan = plan_with_halls()
    actions.upload(plan, [("dag.xlsx", excel_bytes([("Hold 1", 10), ("Hold 2", 15)]))], show_hal="Sal A")
    r1, r2 = plan["raw_rows"]

    check("patch unknown field -> 400", raises(lambda: actions.patch_row(plan, r1["id"], "nope", 1), 400) is not None)
    check("patch missing row -> 404", raises(lambda: actions.patch_row(plan, "findes-ikke", "varighed", 1), 404) is not None)
    check("renaming an Excel team is blocked (400)",
          raises(lambda: actions.patch_row(plan, r1["id"], "hold", "Nyt navn"), 400) is not None)
    actions.patch_row(plan, r1["id"], "varighed", -5)
    check("negative duration clamped to 0", r1["Varighed"] == 0)
    actions.patch_row(plan, r1["id"], "opvarmningMin", "abc")
    check("garbage warm-up minutes -> None", r1["OpvarmningMinOverride"] is None)
    actions.patch_row(plan, r1["id"], "opvarmningHal", "Findes ikke")
    check("unknown warm-up hall override -> None", r1["OpvarmningHalOverride"] is None)
    actions.patch_row(plan, r1["id"], "opvisningHal", "Sal B")
    check("moving a team to another show hall puts it last there",
          r1["OpvisningHal"] == "Sal B" and r1["Order"] == 0)

    check("special row with unknown type -> 400",
          raises(lambda: actions.add_special_row(plan, "Sal A", "fest"), 400) is not None)
    check("special row in unknown hall -> 404",
          raises(lambda: actions.add_special_row(plan, "Ingen", "pause"), 404) is not None)
    actions.add_special_row(plan, "Sal A", "pause")
    pause = plan["raw_rows"][-1]
    check("pause added last in hall", pause["Hold"] == "Pause" and pause["Order"] == r2["Order"] + 1)
    actions.patch_row(plan, pause["id"], "hold", "Frokost")
    check("renaming a special row marks it HoldEdited", pause["Hold"] == "Frokost" and pause.get("HoldEdited") is True)

    actions.reorder_rows(plan, "Sal A", [pause["id"], r2["id"]])
    check("reorder sets Order by position", (pause["Order"], r2["Order"]) == (0, 1))

    actions.delete_row(plan, pause["id"])
    check("delete_row removes the row", pause["id"] not in [r["id"] for r in plan["raw_rows"]])

    # ---------- bytte opvarmningstid ----------
    check("swap with unknown team -> 404",
          raises(lambda: actions.swap_warmup_time(plan, "x", r2["id"]), 404) is not None)
    plan_s = actions.new_plan()
    actions.create_warmup_hall(plan_s, "Varm 1")
    actions.create_show_hall(plan_s, "Sal A")
    actions.upload(plan_s, [("d.xlsx", excel_bytes([("Tidlig", 60), ("Sen", 10)]))], show_hal="Sal A")
    early, late = plan_s["raw_rows"]
    before = copy.deepcopy(plan_s)
    err = raises(lambda: actions.swap_warmup_time(plan_s, late["id"], early["id"]), 400)
    check("swap that makes a team miss its show is refused", err is not None and "ikke tid nok" in err.message,
          err and err.message)
    check("refused swap leaves plan unchanged", plan_s == before)

    # ---------- haller og rækker hænger sammen ----------
    actions.rename_show_hall(plan, "Sal A", "Sal Z")
    check("renaming a show hall moves its rows", all(r["OpvisningHal"] != "Sal A" for r in plan["raw_rows"]))
    actions.create_warmup_hall(plan, "Varm 3")
    actions.patch_row(plan, r2["id"], "opvarmningHal", "Varm 3")
    actions.rename_warmup_hall(plan, "Varm 3", "Varm 3B")
    check("renaming a warm-up hall keeps team locks", r2["OpvarmningHalOverride"] == "Varm 3B")

    halls_before = (list(plan["warmup_halls"]), copy.deepcopy(plan["show_halls"]))
    actions.reset_rows(plan)
    check("reset removes rows, keeps halls",
          plan["raw_rows"] == [] and (plan["warmup_halls"], plan["show_halls"]) == halls_before)

    actions.upload(plan, [("d.xlsx", excel_bytes([("Q", 10)]))], show_hal="Sal Z")
    actions.delete_show_hall(plan, "Sal Z")
    check("deleting a show hall deletes its rows", plan["raw_rows"] == [])

    # ---------- visning og eksport ----------
    plan = plan_with_halls()
    actions.upload(plan, [("d.xlsx", excel_bytes([("Hold 1", 10)]))], show_hal="Sal A")
    p = actions.payload(plan)
    check("payload has the frontend keys", set(p) == {"warmupHalls", "priorityHall", "showHalls", "rows", "schedule"})
    check("payload row is placed", p["rows"][0]["status"] == "OK", p["rows"][0])
    data = actions.export_xlsx(plan)
    sheets = pd.read_excel(BytesIO(data), sheet_name=None)
    check("export is an xlsx with one sheet per show hall first",
          data[:2] == b"PK" and list(sheets)[:2] == ["Opvisning Sal A", "Opvisning Sal B"], list(sheets))

    # ---------- migrering ----------
    old = {"warmup_halls": ["V"], "show_halls": ["Gammel"], "raw_rows": [
        {"id": "a", "Hold": "Andet", "Type": "hold", "OpvisningHal": "Gammel", "NeedsWarmup": True},
    ]}
    m = actions.migrate(old)
    check("migrate fills missing keys", m["priority_hall"] is None and "raw_rows" in m)
    check("migrate turns string show halls into dicts", m["show_halls"] == [{"name": "Gammel", "startTime": "09:00"}])
    check("migrate fixes the old 'Andet' bug and drops NeedsWarmup",
          m["raw_rows"][0]["Type"] == "andet" and m["raw_rows"][0]["Hold"] == "" and "NeedsWarmup" not in m["raw_rows"][0])
    for bad in [[], "tekst", {"raw_rows": "x"}, {"raw_rows": [1]}, {"raw_rows": [{"Hold": "uden id"}]},
                {"show_halls": [{"uden": "navn"}]}]:
        check(f"migrate rejects {bad!r}", raises(lambda: actions.migrate(bad), 400) is not None)
    check("import_plan rejects invalid JSON", raises(lambda: actions.import_plan("{ikke json"), 400) is not None)
    check("import_plan round-trips a plan", actions.import_plan(json.dumps(plan)) == plan)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return not FAIL


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python test_actions.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'planner'`

- [ ] **Step 3: Write minimal implementation**

Create `webapp/planner/__init__.py`:

```python
"""Handlinger på en opvarmningsplan — deles af serveren (app.py) og browserudgaven."""
```

Create `webapp/planner/actions.py`:

```python
"""
Alle handlinger på en opvarmningsplan som rene funktioner.

En plan er en dict: {"warmup_halls", "priority_hall", "show_halls", "raw_rows"}
(samme form som state.json). Muterende funktioner ændrer planen på stedet.
Fejl kastes som ActionError FØR noget ændres, så en afvist handling aldrig
efterlader en halvt ændret plan.

Bruges af app.py (server) og planner/browser.py (Pyodide i browseren).
"""

import copy
import json
from pathlib import Path
from typing import List, Optional, Tuple

import engine

DEFAULT_PLAN = {
    "warmup_halls": [],   # brugeren opretter selv sine haller
    "priority_hall": None,
    "show_halls": [],     # [{"name": str, "startTime": "HH:MM"}]
    "raw_rows": [],
}

SPECIAL_TYPES = ("pause", "faneindmarch", "faneudmarch", "dorene_aabner")

EDITABLE_FIELD_MAP = {
    "hold": "Hold",
    "varighed": "Varighed",
    "opvarmningMin": "OpvarmningMinOverride",
    "opvisningHal": "OpvisningHal",
    "opvarmningHal": "OpvarmningHalOverride",
    "opvarmningStart": "OpvarmningStartOverride",
}

INVALID_PLAN = "Filen er ikke en gyldig plan."


class ActionError(Exception):
    """En handling blev afvist. message er dansk og vises til brugeren."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


# ======================================================
# PLAN: oprettelse, migrering, visning
# ======================================================

def new_plan() -> dict:
    return copy.deepcopy(DEFAULT_PLAN)


def migrate(data) -> dict:
    """Validerer formen og opdaterer ældre plan-data til den nuværende form."""
    if not isinstance(data, dict):
        raise ActionError(INVALID_PLAN)
    for key, default in DEFAULT_PLAN.items():
        data.setdefault(key, copy.deepcopy(default))
    if not isinstance(data["warmup_halls"], list) or not isinstance(data["show_halls"], list) \
            or not isinstance(data["raw_rows"], list):
        raise ActionError(INVALID_PLAN)

    # migrering: ældre state havde show_halls som en liste af strenge
    data["show_halls"] = [
        {"name": h, "startTime": "09:00"} if isinstance(h, str) else h
        for h in data["show_halls"]
    ]
    if not all(isinstance(h, dict) and isinstance(h.get("name"), str) for h in data["show_halls"]):
        raise ActionError(INVALID_PLAN)
    for h in data["show_halls"]:
        h.setdefault("startTime", "09:00")
    if not all(isinstance(r, dict) and "id" in r and "OpvisningHal" in r for r in data["raw_rows"]):
        raise ActionError(INVALID_PLAN)

    # engangsrettelse: en tidligere bug gav tomme "andet"-rækker den synlige
    # label "Andet", så de fejlagtigt blev genklassificeret som "hold".
    for row in data["raw_rows"]:
        if row.get("Type") == "hold" and row.get("Hold") == "Andet":
            row["Type"] = "andet"
            row["Hold"] = ""

    # migrering: "hold"/"andet"-rækker genklassificeres ud fra nøgleordslisten.
    # Manuelt oprettede pause/fane-punkter og punkter brugeren selv har
    # omdøbt (HoldEdited) røres ikke.
    for row in data["raw_rows"]:
        if row.get("Type") in ("hold", "andet") and not row.get("HoldEdited"):
            reclassified = engine.classify_type(row.get("Hold", ""))
            if reclassified != row.get("Type"):
                row["Type"] = reclassified
        row.pop("NeedsWarmup", None)
    return data


def import_plan(text: str) -> dict:
    """Læser en plan fra JSON-tekst (fx en gemt .json-fil) og migrerer den."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        raise ActionError(INVALID_PLAN)
    return migrate(data)


def _compute(plan: dict):
    df = engine.build_dataframe(plan["raw_rows"], plan["show_halls"])
    return engine.compute_plan(df, plan["warmup_halls"], plan["priority_hall"])


def payload(plan: dict) -> dict:
    """Det frontenden viser: haller + beregnede rækker og tidsplan."""
    df = _compute(plan)
    return {
        "warmupHalls": plan["warmup_halls"],
        "priorityHall": plan["priority_hall"],
        "showHalls": plan["show_halls"],
        "rows": engine.to_row_dicts(df, plan["warmup_halls"]),
        "schedule": engine.to_schedule(df),
    }


def export_xlsx(plan: dict) -> bytes:
    return engine.build_workbook(_compute(plan), show_hal_names(plan)).getvalue()


# ======================================================
# HJÆLPERE
# ======================================================

def normalize_hhmm(value) -> Optional[str]:
    """Accepterer '9:30', '09:30', '9.30', '930' og '0930' og returnerer
    'HH:MM' — eller None hvis det ikke er et gyldigt klokkeslæt."""
    text = str(value or "").strip().replace(".", ":")
    if ":" in text:
        parts = text.split(":")
        if len(parts) != 2:
            return None
        hh, mm = parts
    elif text.isdigit() and len(text) in (3, 4):
        hh, mm = text[:-2], text[-2:]
    elif text.isdigit() and len(text) in (1, 2):
        hh, mm = text, "00"
    else:
        return None
    try:
        h, m = int(hh), int(mm)
    except ValueError:
        return None
    if 0 <= h <= 23 and 0 <= m <= 59:
        return f"{h:02d}:{m:02d}"
    return None


def _find_show_hal(plan: dict, name: str) -> Optional[dict]:
    return next((h for h in plan["show_halls"] if h["name"] == name), None)


def show_hal_names(plan: dict) -> List[str]:
    return [h["name"] for h in plan["show_halls"]]


def _next_order(plan: dict, hal_name: str) -> int:
    orders = [r["Order"] for r in plan["raw_rows"] if r["OpvisningHal"] == hal_name]
    return (max(orders) + 1) if orders else 0


def _find_row(plan: dict, row_id: str) -> Optional[dict]:
    return next((r for r in plan["raw_rows"] if r["id"] == row_id), None)


# ======================================================
# RÆKKER
# ======================================================

def upload(plan: dict, files: List[Tuple[str, bytes]], show_hal: Optional[str] = None) -> None:
    """Indlæser Excel-filer. Med show_hal lægges alle hold i den hal; ellers
    navngives hallen ud fra filnavnet. Alle filer valideres, før planen ændres."""
    # En eksisterende hal UDEN hold (fx efter "Ryd alle hold") tæller ikke som
    # optaget — den genbruges i stedet for at oprette "Arena (2)".
    halls_with_rows = {r["OpvisningHal"] for r in plan["raw_rows"]}
    existing_names = {h["name"] for h in plan["show_halls"] if h["name"] in halls_with_rows}
    explicit_name = (show_hal or "").strip()
    pending_new_names = set()
    planned = []  # (hal_name, is_new_hal, suggested_start, rows)

    for filename, content in files:
        if explicit_name:
            hal_name = explicit_name
        else:
            # Automatisk navngivning må aldrig stille flette ind i en hal med
            # hold — gør navnet unikt, også inden for samme upload.
            base_name = engine.clean_hal_name(Path(filename).stem)
            hal_name = base_name
            suffix = 2
            while hal_name in existing_names or hal_name in pending_new_names:
                hal_name = f"{base_name} ({suffix})"
                suffix += 1

        is_new_hal = hal_name not in existing_names and hal_name not in pending_new_names
        if is_new_hal:
            pending_new_names.add(hal_name)

        try:
            rows, suggested_start = engine.load_excel_bytes(filename, content, hal_name, 0)
        except Exception as e:
            raise ActionError(f"Kunne ikke læse '{filename}' — er det en gyldig Excel-fil (.xlsx)? ({e})")
        planned.append((hal_name, is_new_hal, suggested_start, rows))

    for hal_name, is_new_hal, suggested_start, rows in planned:
        if is_new_hal:
            existing = _find_show_hal(plan, hal_name)
            if existing is None:
                plan["show_halls"].append({"name": hal_name, "startTime": suggested_start or "09:00"})
            elif suggested_start and not explicit_name:
                # genbrugt tom hal fundet via filnavnet: filens starttid gælder.
                # Har brugeren selv valgt hallen, beholdes brugerens starttid.
                existing["startTime"] = suggested_start
        start_order = _next_order(plan, hal_name)
        for i, row in enumerate(rows):
            row["Order"] = start_order + i
        plan["raw_rows"].extend(rows)


def patch_row(plan: dict, row_id: str, field: str, value=None) -> None:
    if field not in EDITABLE_FIELD_MAP:
        raise ActionError(f"Ukendt felt: {field}")
    key = EDITABLE_FIELD_MAP[field]
    row = _find_row(plan, row_id)
    if row is None:
        raise ActionError("Punkt ikke fundet", 404)

    if key == "Varighed":
        try:
            value = max(0, int(value))
        except (TypeError, ValueError):
            value = row["Varighed"]
    if key == "OpvarmningMinOverride":
        if value in (None, ""):
            value = None
        else:
            try:
                value = int(value)
            except (TypeError, ValueError):
                value = None
    if key == "Hold":
        if row.get("Type") == "hold":
            raise ActionError("Holdnavn fra Excel-importen kan ikke ændres")
        value = str(value or "").strip()
        row["HoldEdited"] = True
    if key == "OpvisningHal":
        name = str(value or "").strip()
        if name and _find_show_hal(plan, name) is None:
            plan["show_halls"].append({"name": name, "startTime": "09:00"})
        if name and name != row["OpvisningHal"]:
            row["Order"] = _next_order(plan, name)
        value = name
    if key == "OpvarmningHalOverride":
        name = str(value or "").strip()
        value = name if name in plan["warmup_halls"] else None
    if key == "OpvarmningStartOverride":
        value = normalize_hhmm(value)

    row[key] = value


def delete_row(plan: dict, row_id: str) -> None:
    plan["raw_rows"] = [r for r in plan["raw_rows"] if r["id"] != row_id]


def add_special_row(plan: dict, hal: str, row_type: str) -> None:
    if row_type not in SPECIAL_TYPES:
        raise ActionError("Ukendt type")
    if _find_show_hal(plan, hal) is None:
        raise ActionError("Opvisningshal ikke fundet", 404)
    plan["raw_rows"].append(engine.new_special_row(hal, row_type, _next_order(plan, hal)))


def reorder_rows(plan: dict, hal: str, ordered_ids: List[str]) -> None:
    by_id = {r["id"]: r for r in plan["raw_rows"] if r["OpvisningHal"] == hal}
    for i, rid in enumerate(ordered_ids):
        if rid in by_id:
            by_id[rid]["Order"] = i


def swap_warmup_time(plan: dict, dragged_id: str, target_id: str) -> None:
    """Det trukne hold overtager målholdets (tidligere) opvarmningstid, og
    målholdet får det trukne holds (senere) tid. Afvises, hvis et af holdene
    så ikke kan nå sin opvisning."""
    dragged = _find_row(plan, dragged_id)
    target = _find_row(plan, target_id)
    if dragged is None or target is None:
        raise ActionError("Hold ikke fundet", 404)

    rows_now = {r["id"]: r for r in engine.to_row_dicts(_compute(plan), plan["warmup_halls"])}
    dragged_now = rows_now.get(dragged_id)
    target_now = rows_now.get(target_id)
    if not dragged_now or not target_now or not dragged_now["opvarmningStart"] or not target_now["opvarmningStart"]:
        raise ActionError("Begge hold skal have en beregnet opvarmningstid lige nu")
    if target_now["opvarmningStart"] >= dragged_now["opvarmningStart"]:
        raise ActionError("Kan kun trække et hold til et tidligere tidspunkt")

    before = [(r, r["OpvarmningStartOverride"], r["OpvarmningHalOverride"]) for r in (dragged, target)]
    dragged["OpvarmningStartOverride"] = target_now["opvarmningStart"]
    target["OpvarmningStartOverride"] = dragged_now["opvarmningStart"]
    # Lås også hallen, så holdene bytter plads i DENNE hal.
    dragged["OpvarmningHalOverride"] = target_now["opvarmningHalBeregnet"]
    target["OpvarmningHalOverride"] = dragged_now["opvarmningHalBeregnet"]

    after = {r["id"]: r for r in engine.to_row_dicts(_compute(plan), plan["warmup_halls"])}
    if after[dragged_id]["status"] != "OK" or after[target_id]["status"] != "OK":
        for r, start, hal in before:
            r["OpvarmningStartOverride"], r["OpvarmningHalOverride"] = start, hal
        raise ActionError(
            f"Byttet giver ikke tid nok: '{target['Hold']}' kan ikke nå sin opvisning med det senere tidspunkt"
        )


def reset_rows(plan: dict) -> None:
    plan["raw_rows"] = []


# ======================================================
# HALLER
# ======================================================

def create_warmup_hall(plan: dict, name: str) -> None:
    name = (name or "").strip()
    if name and name not in plan["warmup_halls"]:
        plan["warmup_halls"].append(name)
        if plan["priority_hall"] is None:
            plan["priority_hall"] = name


def rename_warmup_hall(plan: dict, old_name: str, new_name: str) -> None:
    old, new = (old_name or "").strip(), (new_name or "").strip()
    if old in plan["warmup_halls"] and new:
        plan["warmup_halls"] = [new if h == old else h for h in plan["warmup_halls"]]
        if plan["priority_hall"] == old:
            plan["priority_hall"] = new
        for r in plan["raw_rows"]:
            if r.get("OpvarmningHalOverride") == old:
                r["OpvarmningHalOverride"] = new


def delete_warmup_hall(plan: dict, name: str) -> None:
    name = (name or "").strip()
    plan["warmup_halls"] = [h for h in plan["warmup_halls"] if h != name]
    if plan["priority_hall"] == name:
        plan["priority_hall"] = plan["warmup_halls"][0] if plan["warmup_halls"] else None


def set_priority_hall(plan: dict, name: str) -> None:
    name = (name or "").strip()
    if name in plan["warmup_halls"]:
        plan["priority_hall"] = name


def create_show_hall(plan: dict, name: str) -> None:
    name = (name or "").strip()
    if name and _find_show_hal(plan, name) is None:
        plan["show_halls"].append({"name": name, "startTime": "09:00"})


def rename_show_hall(plan: dict, old_name: str, new_name: str) -> None:
    old, new = (old_name or "").strip(), (new_name or "").strip()
    hal = _find_show_hal(plan, old)
    if hal and new:
        hal["name"] = new
        for r in plan["raw_rows"]:
            if r["OpvisningHal"] == old:
                r["OpvisningHal"] = new


def set_show_hall_start_time(plan: dict, name: str, start_time: str) -> None:
    start = normalize_hhmm(start_time)
    if start is None:
        raise ActionError(f"'{start_time}' er ikke et gyldigt klokkeslæt — skriv fx 09:30")
    hal = _find_show_hal(plan, (name or "").strip())
    if hal:
        hal["startTime"] = start


def delete_show_hall(plan: dict, name: str) -> None:
    name = (name or "").strip()
    plan["show_halls"] = [h for h in plan["show_halls"] if h["name"] != name]
    plan["raw_rows"] = [r for r in plan["raw_rows"] if r["OpvisningHal"] != name]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python test_actions.py && python test_engine.py`
Expected: `... passed, 0 failed` for both, exit code 0.

- [ ] **Step 5: Commit**

```bash
git add webapp/planner/__init__.py webapp/planner/actions.py webapp/test_actions.py
git commit -m "Move plan actions into planner/actions.py as pure functions"
```

---

### Task 2: `app.py` som tynd skal + selvstændig røgtest

**Files:**
- Modify: `webapp/app.py` (hele filen erstattes)
- Modify: `webapp/test_api.py` (hele filen erstattes)

**Interfaces:**
- Consumes: alt fra `planner.actions` (Task 1).
- Produces: uændrede HTTP-endpoints og svar (samme URL'er, metoder, body-felter og statuskoder som i dag), plus `app.py`-modulets `STATE` og `STATE_FILE`.

- [ ] **Step 1: Write the failing test**

Replace `webapp/test_api.py`:

```python
"""
Røgtest af serverudgaven (app.py). Starter sin egen server på en ledig port
med en midlertidig STATE_FILE — rører aldrig den rigtige state.json.

Kør: python test_api.py
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
PASS, FAIL = [], []


def check(name, condition, detail=""):
    (PASS.append(name) if condition else FAIL.append((name, detail)))
    if not condition:
        print(f"FAIL: {name}  {detail}")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def excel_bytes():
    df = pd.DataFrame({"Tid": ["09:00", ""], "Varighed": [10, 10], "Holdnavn": ["Hold 1", "Hold 2"],
                       "Antal deltagere": [20, 20], "Alder": ["voksen", "voksen"]})
    buf = BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


def run():
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    tmp = tempfile.mkdtemp()
    env = dict(os.environ, STATE_FILE=str(Path(tmp) / "state.json"), PORT=str(port))
    server = subprocess.Popen([sys.executable, "app.py"], cwd=HERE, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def req(method, path, body=None, raw=None, headers=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        h = headers or ({"Content-Type": "application/json"} if body is not None else {})
        r = urllib.request.Request(base + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    try:
        for _ in range(60):
            try:
                if req("GET", "/api/state")[0] == 200:
                    break
            except OSError:
                time.sleep(0.25)

        status, body = req("GET", "/api/state")
        state = json.loads(body)
        check("GET /api/state -> 200 with frontend keys", status == 200 and
              set(state) == {"warmupHalls", "priorityHall", "showHalls", "rows", "schedule"})
        check("fresh server has no warm-up halls", state["warmupHalls"] == [])

        status, body = req("POST", "/api/halls/warmup", {"name": "Varm 1"})
        check("create warm-up hall", status == 200 and json.loads(body)["warmupHalls"] == ["Varm 1"])
        req("POST", "/api/halls/show", {"name": "Sal A"})

        status, body = req("POST", "/api/halls/show/starttime", {"name": "Sal A", "startTime": "abc"})
        check("invalid start time -> 400 with error", status == 400 and "gyldigt klokkeslæt" in json.loads(body)["error"])

        boundary = "----t"
        parts = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"show_hal\"\r\n\r\nSal A\r\n"
                 f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"dag.xlsx\"\r\n"
                 f"Content-Type: application/octet-stream\r\n\r\n").encode() + excel_bytes() + f"\r\n--{boundary}--\r\n".encode()
        status, body = req("POST", "/api/upload", raw=parts,
                           headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        rows = json.loads(body)["rows"] if status == 200 else []
        check("upload puts teams in the chosen hall", status == 200 and [r["opvisningHal"] for r in rows] == ["Sal A", "Sal A"],
              body[:200])

        bad = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"x.xlsx\"\r\n\r\n"
               f"ikke excel\r\n--{boundary}--\r\n").encode()
        status, body = req("POST", "/api/upload", raw=bad,
                           headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        check("garbage upload -> 400 with error", status == 400 and "x.xlsx" in json.loads(body)["error"])

        status, _ = req("PATCH", "/api/rows/findes-ikke", {"field": "varighed", "value": 1})
        check("patch missing row -> 404", status == 404)

        status, body = req("GET", "/api/export.xlsx")
        check("export -> 200 xlsx", status == 200 and body[:2] == b"PK")

        saved = json.loads((Path(tmp) / "state.json").read_text(encoding="utf-8"))
        check("state is saved to STATE_FILE", len(saved["raw_rows"]) == 2)
    finally:
        server.terminate()
        server.wait(timeout=10)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return not FAIL


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
```

- [ ] **Step 2: Run test to verify the baseline**

Run: `python test_api.py`
Expected: PASS against the *current* `app.py` (this test pins today's HTTP behaviour before the rewrite). If anything fails here, stop and fix the test, not `app.py`.

- [ ] **Step 3: Rewrite `app.py` as a thin shell**

Replace `webapp/app.py`:

```python
"""
Opvarmningsplanlægger — lokal webserver.

Tynd HTTP-skal om planner.actions: læser request, kalder handlingen, gemmer
state.json og returnerer den nye visning. Browserudgaven (GitHub Pages)
bruger de samme handlinger via planner/browser.py.

Kør med:  python app.py
Åbn så:   http://localhost:8877
"""

import asyncio
import json
import os
import time
from pathlib import Path
from typing import List, Optional

import uvicorn
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from planner import actions

BASE_DIR = Path(__file__).parent
# STATE_FILE kan peges et andet sted hen (fx i test), så testene aldrig
# rører den rigtige state.json.
STATE_FILE = Path(os.environ.get("STATE_FILE", BASE_DIR / "state.json"))


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return actions.migrate(json.load(f))
        except Exception as e:
            # Overskriv ALDRIG en fil vi ikke kunne læse — flyt den til side.
            broken = STATE_FILE.with_name(f"{STATE_FILE.stem}.broken-{time.strftime('%Y%m%d-%H%M%S')}.json")
            os.replace(STATE_FILE, broken)
            print(f"ADVARSEL: kunne ikke læse {STATE_FILE.name} ({e}). Flyttet til {broken.name}.")
    return actions.new_plan()


STATE = load_state()


def save_state():
    # Skriv til en midlertidig fil og byt den ind atomisk.
    tmp = STATE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(STATE, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)


def run_action(fn, *args, **kwargs):
    """Kører en handling på STATE. Ved succes gemmes og den nye visning
    returneres; ved ActionError returneres fejlen uden at gemme."""
    try:
        fn(STATE, *args, **kwargs)
    except actions.ActionError as e:
        return JSONResponse({"error": e.message}, status_code=e.status)
    save_state()
    return actions.payload(STATE)


app = FastAPI(title="Opvarmningsplanlægger")

# Synkrone endpoints kører parallelt i en threadpool og muterer alle den samme
# STATE — kør API-kald ét ad gangen.
_api_lock = asyncio.Lock()


@app.middleware("http")
async def serialize_api_calls(request: Request, call_next):
    if not request.url.path.startswith("/api/"):
        return await call_next(request)
    async with _api_lock:
        return await call_next(request)


class RowPatch(BaseModel):
    field: str
    value: Optional[object] = None


class SpecialRowCreate(BaseModel):
    hal: str
    type: str


class ReorderPayload(BaseModel):
    hal: str
    orderedIds: List[str]


class SwapWarmupTimePayload(BaseModel):
    draggedId: str
    targetId: str


class HallName(BaseModel):
    name: str


class HallRename(BaseModel):
    oldName: str
    newName: str


class ShowHallStartTime(BaseModel):
    name: str
    startTime: str


@app.get("/api/state")
def get_state():
    return actions.payload(STATE)


@app.post("/api/upload")
async def upload(files: List[UploadFile] = File(...), show_hal: Optional[str] = Form(None)):
    data = [(f.filename, await f.read()) for f in files]
    return run_action(actions.upload, data, show_hal)


@app.patch("/api/rows/{row_id}")
def patch_row(row_id: str, patch: RowPatch):
    return run_action(actions.patch_row, row_id, patch.field, patch.value)


@app.delete("/api/rows/{row_id}")
def delete_row(row_id: str):
    return run_action(actions.delete_row, row_id)


@app.post("/api/rows/special")
def create_special_row(payload: SpecialRowCreate):
    return run_action(actions.add_special_row, payload.hal, payload.type)


@app.post("/api/rows/reorder")
def reorder_rows(payload: ReorderPayload):
    return run_action(actions.reorder_rows, payload.hal, payload.orderedIds)


@app.post("/api/rows/swap-warmup-time")
def swap_warmup_time(payload: SwapWarmupTimePayload):
    return run_action(actions.swap_warmup_time, payload.draggedId, payload.targetId)


@app.post("/api/reset")
def reset_rows():
    return run_action(actions.reset_rows)


@app.post("/api/halls/warmup")
def create_warmup_hall(payload: HallName):
    return run_action(actions.create_warmup_hall, payload.name)


@app.patch("/api/halls/warmup")
def rename_warmup_hall(payload: HallRename):
    return run_action(actions.rename_warmup_hall, payload.oldName, payload.newName)


@app.delete("/api/halls/warmup")
def delete_warmup_hall(payload: HallName):
    return run_action(actions.delete_warmup_hall, payload.name)


@app.post("/api/halls/warmup/priority")
def set_priority_hall(payload: HallName):
    return run_action(actions.set_priority_hall, payload.name)


@app.post("/api/halls/show")
def create_show_hall(payload: HallName):
    return run_action(actions.create_show_hall, payload.name)


@app.patch("/api/halls/show")
def rename_show_hall(payload: HallRename):
    return run_action(actions.rename_show_hall, payload.oldName, payload.newName)


@app.post("/api/halls/show/starttime")
def set_show_hall_start_time(payload: ShowHallStartTime):
    return run_action(actions.set_show_hall_start_time, payload.name, payload.startTime)


@app.delete("/api/halls/show")
def delete_show_hall(payload: HallName):
    return run_action(actions.delete_show_hall, payload.name)


@app.get("/api/export.xlsx")
def export_xlsx():
    return Response(
        actions.export_xlsx(STATE),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="opvisning_med_opvarmning.xlsx"'},
    )


app.mount("/", StaticFiles(directory=str(BASE_DIR / "static"), html=True), name="static")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8877"))
    print(f"Opvarmningsplanlægger kører på http://localhost:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port)
```

- [ ] **Step 4: Run tests to verify nothing changed**

Run: `python test_api.py && python test_actions.py && python test_engine.py`
Expected: all three `... passed, 0 failed`.

Then check the real data still loads: `python -c "import app; print(len(app.STATE['raw_rows']))"` prints the same row count as before (73 on the author's machine).

- [ ] **Step 5: Commit**

```bash
git add webapp/app.py webapp/test_api.py
git commit -m "Make app.py a thin HTTP shell around planner.actions"
```

---

### Task 3: `api.js` (HTTP-transport) og en browsertest i repoet

**Files:**
- Create: `webapp/static/config.js`
- Create: `webapp/static/api.js`
- Modify: `webapp/static/app.js` (funktionerne `readState`, `apiGet`, `apiJSON`, `uploadFiles`, `init`)
- Modify: `webapp/static/index.html` (eksport-knap, script-tags)
- Create: `webapp/test_e2e.py`

**Interfaces:**
- Consumes: HTTP-endpoints fra Task 2.
- Produces (global `Api` i `api.js`, bruges af `app.js` og udvides i Task 6–7):
  - `Api.mode: "server" | "browser"`
  - `Api.start(onStatus: (text) => void) -> Promise<void>`
  - `Api.request(method: string, url: string, body?: object) -> Promise<payload>`; kaster `ApiError` med `.message`, `.status`
  - `Api.upload(files: File[], hal: string|null) -> Promise<payload>`
  - `Api.exportPlan() -> Promise<void>`
  - `class ApiError extends Error { status }`
- `window.PLANNER_CONFIG = { mode, wheels? }` fra `config.js`.
- `test_e2e.py` CLI: `python test_e2e.py server` (og i Task 6: `browser`).

- [ ] **Step 1: Write the failing test**

Create `webapp/test_e2e.py`:

```python
"""
Browsertest med Playwright og Microsoft Edge.

  python test_e2e.py server    tester python app.py (egen server, midlertidig state)
  python test_e2e.py browser   tester den byggede browserudgave (Task 6)

Kræver: pip install playwright   (bruger den installerede Edge; ingen download)
"""
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from io import BytesIO
from pathlib import Path

import pandas as pd
from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
PASS, FAIL = [], []


def check(name, condition, detail=""):
    (PASS.append(name) if condition else FAIL.append((name, detail)))
    print(("OK   " if condition else "FEJL ") + name + (f"  ({detail})" if detail and not condition else ""))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(url, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(url)
            return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError(f"{url} svarede ikke")


def excel_file(tmp):
    df = pd.DataFrame({
        "Tid": ["09:00"] + [""] * 5,
        "Varighed": [10] * 6,
        "Holdnavn": [f"Hold {i}" for i in range(1, 7)],
        "Antal deltagere": [20] * 6,
        "Alder": ["voksen"] * 6,
    })
    path = Path(tmp) / "program.xlsx"
    df.to_excel(path, index=False)
    return path


def start_server(tmp):
    port = free_port()
    env = dict(os.environ, STATE_FILE=str(Path(tmp) / "state.json"), PORT=str(port))
    proc = subprocess.Popen([sys.executable, "app.py"], cwd=HERE, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}/"
    wait_for(url + "api/state")
    return proc, url


def common_flow(page, url, xlsx, dialogs, errors):
    """Hele forløbet fra tom plan til eksport — ens for begge udgaver."""
    page.goto(url)
    page.wait_for_selector("#onboarding:not(.hidden)", timeout=120_000)
    check("tom plan viser 'Kom i gang'", page.inner_text("#page-title") == "Kom i gang")
    check("Hent Excel-plan er skjult uden hold", page.is_hidden("#btn-export"))

    for name in ["Varm 1", "Varm 2"]:
        page.fill("#onb-warmup-form input", name)
        page.press("#onb-warmup-form input", "Enter")
    page.wait_for_function("document.querySelectorAll('#onb-warmup-list li').length === 2")
    for i, (name, start) in enumerate([("Sal A", "9.15"), ("Sal B", "10:00")], start=1):
        page.fill("#onb-show-form input >> nth=0", name)
        page.fill("#onb-show-form input >> nth=1", start)
        page.click("#onb-show-form button")
        page.wait_for_function(f"document.querySelectorAll('#onb-show-list li').length === {i}")
    check("haller oprettet på startsiden", "start 09:15" in page.locator("#onb-show-list li").first.inner_text())

    page.set_input_files("#file-input", str(xlsx))
    page.wait_for_selector("#overview-data:not(.hidden)")
    check("Excel lægges i den første hal",
          page.locator(".hall-row-name").all_inner_texts() == ["Sal A", "Sal B"])
    check("tidslinjen har blokke", page.locator(".tl-block").count() >= 6)

    page.locator(".hall-row").first.click()
    team_row = page.locator("#table-body tr:not(.row-special)").first
    team_row.locator("select").select_option("Sal B")
    page.wait_for_timeout(500)
    moved = page.evaluate("() => STATE.rows.find(r => r.hold === 'Hold 1')")
    check("flyttet hold får ny tid og opvarmning",
          moved["opvisningHal"] == "Sal B" and moved["opvisningTid"] == "10:00" and moved["status"] == "OK", moved)

    page.fill("#hal-start-time", "abc")
    page.locator("#hal-start-time").blur()
    page.wait_for_timeout(500)
    check("ugyldig starttid giver dansk besked", any("gyldigt klokkeslæt" in d for d in dialogs), dialogs)

    with page.expect_file_chooser() as fc:
        page.click("#btn-upload")
    garbage = Path(xlsx).with_name("skrald.xlsx")
    garbage.write_bytes(b"ikke excel")
    count_before = page.evaluate("() => STATE.rows.length")
    fc.value.set_files(str(garbage))
    page.wait_for_timeout(1000)
    check("ugyldig Excel giver besked og ændrer intet",
          any("skrald.xlsx" in d for d in dialogs) and page.evaluate("() => STATE.rows.length") == count_before)

    with page.expect_download() as dl:
        page.click("#btn-export")
    check("eksport henter opvisning_med_opvarmning.xlsx",
          dl.value.suggested_filename == "opvisning_med_opvarmning.xlsx")
    data = Path(dl.value.path()).read_bytes()
    sheets = list(pd.read_excel(BytesIO(data), sheet_name=None))
    check("eksport har ét ark pr. opvisningshal først", sheets[:2] == ["Opvisning Sal A", "Opvisning Sal B"], sheets)


def run(mode):
    tmp = tempfile.mkdtemp()
    xlsx = excel_file(tmp)
    procs = []
    try:
        if mode == "server":
            proc, url = start_server(tmp)
            procs.append(proc)
        else:
            raise SystemExit("browser-udgaven testes fra Task 6")

        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            context = browser.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True)
            page = context.new_page()
            dialogs, errors = [], []
            page.on("dialog", lambda d: (dialogs.append(d.message), d.accept()))
            page.on("pageerror", lambda e: errors.append(str(e)))
            common_flow(page, url, xlsx, dialogs, errors)
            check("ingen JavaScript-fejl", not errors, errors)
            browser.close()
    finally:
        for proc in procs:
            proc.terminate()
            proc.wait(timeout=10)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return not FAIL


if __name__ == "__main__":
    sys.exit(0 if run(sys.argv[1] if len(sys.argv) > 1 else "server") else 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python test_e2e.py server`
Expected: FAIL on "eksport henter opvisning_med_opvarmning.xlsx" (today `#btn-export` is a link, and the expected `ApiError`-based handling does not exist yet) — the other checks should pass. If an earlier check fails, fix the test before continuing.

- [ ] **Step 3: Write `config.js` and `api.js`**

Create `webapp/static/config.js`:

```js
// Standard: serverudgaven (python app.py). build_site.py overskriver denne
// fil i browserudgaven med { mode: "browser", wheels: [...] }.
window.PLANNER_CONFIG = { mode: "server" };
```

Create `webapp/static/api.js`:

```js
"use strict";

// Ét sted hvor frontenden kalder handlinger. "server" bruger HTTP mod
// app.py; "browser" (Task 6) kører Python-motoren i browseren via Pyodide.

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

const Api = (() => {
  const config = window.PLANNER_CONFIG || { mode: "server" };

  async function readJson(res) {
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new ApiError(data.error || `Noget gik galt (fejl ${res.status}).`, res.status);
    return data;
  }

  const server = {
    async start() {},
    async request(method, url, body) {
      const init = { method };
      if (body !== undefined) {
        init.headers = { "Content-Type": "application/json" };
        init.body = JSON.stringify(body);
      }
      return readJson(await fetch(url, init));
    },
    async upload(files, hal) {
      const fd = new FormData();
      files.forEach((f) => fd.append("files", f));
      if (hal) fd.append("show_hal", hal);
      return readJson(await fetch("/api/upload", { method: "POST", body: fd }));
    },
    async exportPlan() {
      window.location.href = "/api/export.xlsx";
    },
  };

  const transport = server;

  return {
    mode: config.mode,
    start: (onStatus) => transport.start(onStatus),
    request: (method, url, body) => transport.request(method, url, body),
    upload: (files, hal) => transport.upload(files, hal),
    exportPlan: () => transport.exportPlan(),
  };
})();
```

- [ ] **Step 4: Use `Api` in `app.js` and `index.html`**

In `webapp/static/index.html`, replace the export link

```html
        <a id="btn-export" class="btn btn-primary" href="/api/export.xlsx">
```
and its closing `</a>` with
```html
        <button id="btn-export" type="button" class="btn btn-primary">
```
and `</button>` (keep the SVG and "Hent Excel-plan" text inside). Replace the two script tags at the bottom with:

```html
<script src="vendor/bootstrap.bundle.min.js"></script>
<script src="config.js"></script>
<script src="api.js?v=1"></script>
<script src="app.js?v=38"></script>
```

In `webapp/static/app.js`, replace the block from `// Alle kald returnerer den nye state.` through the end of `apiJSON` with:

```js
// Alle kald returnerer den nye state. Ved en fejl vises beskeden, og den
// nuværende STATE returneres uændret — så et "STATE = await ..." aldrig
// overskriver state med et fejlsvar.
async function handle(promise) {
  try {
    return await promise;
  } catch (e) {
    alert(e instanceof ApiError ? e.message : `Noget gik galt: ${e.message || e}`);
    return STATE;
  }
}
async function apiGet(url) {
  return handle(Api.request("GET", url));
}
async function apiJSON(url, method, body) {
  return handle(Api.request(method, url, body));
}
```

In `uploadFiles`, replace

```js
  const fd = new FormData();
  xlsx.forEach((f) => fd.append("files", f));
  if (hal) fd.append("show_hal", hal);
  STATE = await readState(await fetch("/api/upload", { method: "POST", body: fd }));
```
with
```js
  STATE = await handle(Api.upload(xlsx, hal));
```

In `init()`, add as the first lines of the function:

```js
  await Api.start(() => {});
  document.getElementById("btn-export").addEventListener("click", () => handle(Api.exportPlan()));
```

Search `app.js` for any remaining `fetch(` or `readState(`; there must be none.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python test_e2e.py server`
Expected: all checks OK, `... passed, 0 failed`.

- [ ] **Step 6: Commit**

```bash
git add webapp/static/config.js webapp/static/api.js webapp/static/app.js webapp/static/index.html webapp/test_e2e.py
git commit -m "Route frontend calls through api.js; add browser test to repo"
```

---

### Task 4: `planner/browser.py` — JSON-broen til Pyodide

**Files:**
- Create: `webapp/planner/browser.py`
- Modify: `webapp/test_actions.py` (tilføj bro-tests før opsummeringen)

**Interfaces:**
- Consumes: `planner.actions` (Task 1).
- Produces (alle tager og returnerer tekst; JS kalder dem via `pyodide.pyimport("planner.browser")`):
  - `load(plan_json: str) -> str` → `{"ok": true, "plan": {...}}` eller `{"ok": false}` hvis ulæselig
  - `call(plan_json: str, name: str, args_json: str) -> str` → `{"ok": true, "plan": {...}, "payload": {...}}` eller `{"ok": false, "error": str, "status": int}`
  - `upload_files(plan_json: str, paths_json: str, show_hal: str) -> str` (samme svar som `call`; `paths_json` er en JSON-liste af stier i Pyodides filsystem; filnavnet er stiens sidste del)
  - `export_to(plan_json: str, out_path: str) -> str` → `{"ok": true}`
  - `import_plan(text: str) -> str` → `{"ok": true, "plan": {...}}` eller `{"ok": false, "error": str, "status": 400}`
  - `ACTIONS: set` — navnene `call` accepterer (plus `"payload"`)

- [ ] **Step 1: Write the failing test**

In `webapp/test_actions.py`, insert before `print(f"\n{len(PASS)} passed ...")` in `run()`:

```python
    # ---------- browser-bro (planner.browser) ----------
    import os
    import tempfile

    from planner import browser

    res = json.loads(browser.load(""))
    check("bridge load('') gives an empty plan", res["ok"] and res["plan"] == actions.new_plan())
    res = json.loads(browser.load('{"show_halls": ["Gammel"]}'))
    check("bridge load migrates an old plan", res["ok"] and res["plan"]["show_halls"][0]["name"] == "Gammel")
    check("bridge load reports broken JSON", json.loads(browser.load("{ødelagt"))["ok"] is False)
    check("bridge load reports wrong shape", json.loads(browser.load("[1, 2]"))["ok"] is False)

    res = json.loads(browser.call("", "create_warmup_hall", json.dumps({"name": "Varm 1"})))
    check("bridge call runs an action and returns plan + payload",
          res["ok"] and res["plan"]["warmup_halls"] == ["Varm 1"] and res["payload"]["warmupHalls"] == ["Varm 1"])
    plan_json = json.dumps(res["plan"])
    res = json.loads(browser.call(plan_json, "set_show_hall_start_time", json.dumps({"name": "X", "start_time": "abc"})))
    check("bridge call returns ActionError as ok=false with status",
          res == {"ok": False, "error": "'abc' er ikke et gyldigt klokkeslæt — skriv fx 09:30", "status": 400}, res)
    res = json.loads(browser.call(plan_json, "__import__", "{}"))
    check("bridge call refuses unknown action names", res["ok"] is False and res["status"] == 400)
    res = json.loads(browser.call(plan_json, "payload", "{}"))
    check("bridge call 'payload' returns view without changes", res["ok"] and res["plan"] == json.loads(plan_json))

    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "dag.xlsx")
    with open(path, "wb") as f:
        f.write(excel_bytes([("Hold 1", 10)]))
    res = json.loads(browser.call(plan_json, "create_show_hall", json.dumps({"name": "Sal A"})))
    res = json.loads(browser.upload_files(json.dumps(res["plan"]), json.dumps([path]), "Sal A"))
    check("bridge upload_files reads files from paths",
          res["ok"] and [r["Hold"] for r in res["plan"]["raw_rows"]] == ["Hold 1"], res.get("error"))
    bad = os.path.join(tmpdir, "skrald.xlsx")
    with open(bad, "wb") as f:
        f.write(b"nej")
    res2 = json.loads(browser.upload_files(json.dumps(res["plan"]), json.dumps([bad]), ""))
    check("bridge upload_files returns a Danish error for a bad file",
          res2["ok"] is False and "skrald.xlsx" in res2["error"])

    out = os.path.join(tmpdir, "ud.xlsx")
    check("bridge export_to writes an xlsx",
          json.loads(browser.export_to(json.dumps(res["plan"]), out))["ok"] and open(out, "rb").read(2) == b"PK")

    res = json.loads(browser.import_plan("ikke json"))
    check("bridge import_plan rejects bad file", res == {"ok": False, "error": "Filen er ikke en gyldig plan.", "status": 400})
    res = json.loads(browser.import_plan(plan_json))
    check("bridge import_plan accepts a saved plan", res["ok"] and res["plan"]["warmup_halls"] == ["Varm 1"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python test_actions.py`
Expected: FAIL with `ImportError: cannot import name 'browser' from 'planner'`

- [ ] **Step 3: Write minimal implementation**

Create `webapp/planner/browser.py`:

```python
"""
Bro mellem JavaScript (Pyodide i browseren) og planner.actions.

Alt ind og ud er JSON-tekst, så JS aldrig skal håndtere Python-objekter.
Planen ejes af JS (gemmes i localStorage); hvert kald får den nuværende plan
med og returnerer den nye.
"""

import json
from pathlib import Path

from . import actions

# De handlinger call() må køre. Navnene og argumenterne svarer til
# funktionerne i planner.actions.
ACTIONS = {
    "patch_row", "delete_row", "add_special_row", "reorder_rows", "swap_warmup_time",
    "reset_rows", "create_warmup_hall", "rename_warmup_hall", "delete_warmup_hall",
    "set_priority_hall", "create_show_hall", "rename_show_hall",
    "set_show_hall_start_time", "delete_show_hall",
}


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _plan(plan_json: str) -> dict:
    return actions.import_plan(plan_json) if plan_json else actions.new_plan()


def _result(plan: dict) -> str:
    return _dump({"ok": True, "plan": plan, "payload": actions.payload(plan)})


def _error(e: actions.ActionError) -> str:
    return _dump({"ok": False, "error": e.message, "status": e.status})


def load(plan_json: str) -> str:
    try:
        return _dump({"ok": True, "plan": _plan(plan_json)})
    except actions.ActionError:
        return _dump({"ok": False})


def call(plan_json: str, name: str, args_json: str) -> str:
    try:
        plan = _plan(plan_json)
        if name == "payload":
            return _result(plan)
        if name not in ACTIONS:
            raise actions.ActionError(f"Ukendt handling: {name}")
        getattr(actions, name)(plan, **json.loads(args_json or "{}"))
        return _result(plan)
    except actions.ActionError as e:
        return _error(e)


def upload_files(plan_json: str, paths_json: str, show_hal: str) -> str:
    try:
        plan = _plan(plan_json)
        files = [(Path(p).name, Path(p).read_bytes()) for p in json.loads(paths_json)]
        actions.upload(plan, files, show_hal or None)
        return _result(plan)
    except actions.ActionError as e:
        return _error(e)


def export_to(plan_json: str, out_path: str) -> str:
    Path(out_path).write_bytes(actions.export_xlsx(_plan(plan_json)))
    return _dump({"ok": True})


def import_plan(text: str) -> str:
    try:
        return _dump({"ok": True, "plan": actions.import_plan(text)})
    except actions.ActionError as e:
        return _error(e)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python test_actions.py`
Expected: `... passed, 0 failed`

- [ ] **Step 5: Commit**

```bash
git add webapp/planner/browser.py webapp/test_actions.py
git commit -m "Add JSON bridge between Pyodide and planner.actions"
```

---

### Task 5: `build_site.py` — statisk side med Pyodide hostet lokalt

**Files:**
- Create: `webapp/build_site.py`
- Create: `webapp/test_build_site.py`
- Modify: `.gitignore` (tilføj `site/` og `webapp/.build-cache/`)

**Interfaces:**
- Consumes: `webapp/static/`, `webapp/engine/`, `webapp/planner/`.
- Produces: `build(out: Path) -> None` i `build_site.py` og CLI `python build_site.py [--out DIR]` (standard `../site`). Output-mappen indeholder:
  - alt fra `static/` med `config.js` overskrevet til `window.PLANNER_CONFIG = {"mode": "browser", "wheels": [...]};`
  - `planner.zip` med `engine/**/*.py` og `planner/**/*.py`
  - `pyodide/`: kernefilerne fra `pyodide-core-314.0.7.tar.bz2` + `pyodide-lock.json` + wheels for `pandas`, `numpy`, `python-dateutil`, `pytz`, `six`
  - `wheels/`: `openpyxl-3.1.5-py2.py3-none-any.whl`, `et_xmlfile-2.0.0-py3-none-any.whl`
  - `.nojekyll`

- [ ] **Step 1: Write the failing test**

Create `webapp/test_build_site.py`:

```python
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

    for f in ["pyodide.js", "pyodide.asm.wasm", "pyodide.asm.js", "python_stdlib.zip", "pyodide-lock.json"]:
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python test_build_site.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'build_site'`

- [ ] **Step 3: Write minimal implementation**

Create `webapp/build_site.py`:

```python
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
```

Append to `.gitignore` (repo root):

```
# Genereret browserudgave og downloads til den
site/
webapp/.build-cache/
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python test_build_site.py`
Expected: `... passed, 0 failed` (first run downloads ~30–40 MB).

If the `pyodide/…` file checks fail, list the tarball (`python -c "import glob,tarfile;print(tarfile.open(glob.glob('.build-cache/*pyodide-core-314.0.7.tar.bz2')[0]).getnames())"`) and adjust `_pyodide` to the real layout — do not change the test's expected file names, they are what `loadPyodide` needs.

- [ ] **Step 5: Commit**

```bash
git add webapp/build_site.py webapp/test_build_site.py .gitignore
git commit -m "Add build_site.py: static site with locally hosted Pyodide"
```

---

### Task 6: Browser-transport — Pyodide, `localStorage` og indlæsningsskærm

**Files:**
- Modify: `webapp/static/api.js` (hele filen erstattes)
- Modify: `webapp/static/app.js` (`init`)
- Modify: `webapp/static/index.html` (indlæsningsskærm)
- Modify: `webapp/static/style.css` (indlæsningsskærm)
- Modify: `webapp/test_e2e.py` (browser-tilstand + browser-specifikke tests)

**Interfaces:**
- Consumes: `build_site.build(out)` (Task 5), `planner.browser` (Task 4), `Api` fra Task 3.
- Produces (tilføjet til `Api`):
  - `Api.onExternalChange(callback: () => void)` — kaldes, når planen ændres i en anden fane
  - `Api.planKey = "opvarmning_plan_v1"`
  - Browser-tilstand: `Api.start(onStatus)` kaster `ApiError("Kunne ikke indlæse planlæggeren. Tjek internetforbindelsen og genindlæs siden.", 0)` hvis Pyodide ikke kan hentes.

- [ ] **Step 1: Write the failing test**

In `webapp/test_e2e.py`, replace

```python
        else:
            raise SystemExit("browser-udgaven testes fra Task 6")
```
with
```python
        else:
            import build_site
            root = Path(tmp) / "www"
            build_site.build(root / "Gymnastik")      # samme understi som GitHub Pages
            port = free_port()
            procs.append(subprocess.Popen(
                [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", str(root)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            url = f"http://127.0.0.1:{port}/Gymnastik/"
            wait_for(url)
```

and replace the block from `            common_flow(page, url, xlsx, dialogs, errors)` through `            browser.close()` with:

```python
            common_flow(page, url, xlsx, dialogs, errors)
            check("ingen JavaScript-fejl", not errors, errors)
            if mode == "browser":
                browser_only(browser, context, page, url, dialogs)
            browser.close()
```

Add this function above `run`:

```python
def browser_only(browser, context, page, url, dialogs):
    """Det der kun gælder browserudgaven: lagring, faner og fejl ved indlæsning."""
    rows = page.evaluate("() => STATE.rows.length")
    stored = page.evaluate("() => JSON.parse(localStorage.getItem('opvarmning_plan_v1')).raw_rows.length")
    check("planen gemmes i localStorage", stored == rows, (stored, rows))

    page.reload()
    page.wait_for_selector("#overview-data:not(.hidden)", timeout=120_000)
    check("planen er der efter genindlæsning", page.evaluate("() => STATE.rows.length") == rows)

    other = context.new_page()
    other.goto(url)
    other.wait_for_selector("#overview-data:not(.hidden)", timeout=120_000)
    page.click(".rail-link[data-view=program]")
    page.click(".add-special[data-type=pause]")
    other.wait_for_function(f"() => STATE.rows.length === {rows + 1}", timeout=10_000)
    check("ændring i én fane vises i den anden", other.evaluate("() => STATE.rows.length") == rows + 1)
    other.close()

    page.evaluate("() => localStorage.setItem('opvarmning_plan_v1', '{ødelagt')")
    page.reload()
    page.wait_for_selector("#onboarding:not(.hidden)", timeout=120_000)
    broken = page.evaluate("() => Object.keys(localStorage).filter(k => k.startsWith('opvarmning_plan_broken_'))")
    check("ulæselig plan giver tom plan og gemmes til side", len(broken) == 1, broken)

    blocked = browser.new_context()
    blocked.add_init_script("Storage.prototype.setItem = function () { throw new Error('QuotaExceededError'); };")
    bpage = blocked.new_page()
    bdialogs = []
    bpage.on("dialog", lambda d: (bdialogs.append(d.message), d.accept()))
    bpage.goto(url)
    bpage.wait_for_selector("#onboarding:not(.hidden)", timeout=120_000)
    bpage.fill("#onb-warmup-form input", "Varm 1")
    bpage.press("#onb-warmup-form input", "Enter")
    bpage.wait_for_function("() => document.querySelectorAll('#onb-warmup-list li').length === 1")
    bpage.fill("#onb-warmup-form input", "Varm 2")
    bpage.press("#onb-warmup-form input", "Enter")
    bpage.wait_for_function("() => document.querySelectorAll('#onb-warmup-list li').length === 2")
    check("uden localStorage virker appen og siger det én gang",
          len([d for d in bdialogs if "Gem plan" in d]) == 1, bdialogs)
    blocked.close()

    offline = browser.new_context()
    offline.route("**/pyodide.asm.wasm", lambda r: r.abort())
    opage = offline.new_page()
    opage.goto(url)
    opage.wait_for_selector("#boot-text:has-text('Kunne ikke indlæse planlæggeren')", timeout=60_000)
    check("Pyodide der ikke kan hentes giver dansk fejl", True)
    offline.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python test_e2e.py browser`
Expected: FAIL — the page stays on the server transport, so the first `fetch("/api/state")` gets a 404 from `http.server` and "tom plan viser 'Kom i gang'" times out or fails.

- [ ] **Step 3: Write the browser transport**

Replace `webapp/static/api.js`:

```js
"use strict";

// Ét sted hvor frontenden kalder handlinger. "server" bruger HTTP mod
// app.py; "browser" kører Python-motoren i browseren via Pyodide og gemmer
// planen i localStorage. Begge returnerer den samme visning (payload).

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

const Api = (() => {
  const config = window.PLANNER_CONFIG || { mode: "server" };
  const PLAN_KEY = "opvarmning_plan_v1";

  async function readJson(res) {
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new ApiError(data.error || `Noget gik galt (fejl ${res.status}).`, res.status);
    return data;
  }

  function download(blob, filename) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  // ---------- server (python app.py) ----------
  const server = {
    async start() {},
    async request(method, url, body) {
      const init = { method };
      if (body !== undefined) {
        init.headers = { "Content-Type": "application/json" };
        init.body = JSON.stringify(body);
      }
      return readJson(await fetch(url, init));
    },
    async upload(files, hal) {
      const fd = new FormData();
      files.forEach((f) => fd.append("files", f));
      if (hal) fd.append("show_hal", hal);
      return readJson(await fetch("/api/upload", { method: "POST", body: fd }));
    },
    async exportPlan() {
      window.location.href = "/api/export.xlsx";
    },
    onExternalChange() {},
  };

  // ---------- browser (Pyodide + localStorage) ----------
  // Samme URL'er som serveren, oversat til handlinger i planner.actions.
  const ROUTES = [
    ["GET", /^\/api\/state$/, () => ["payload", {}]],
    ["PATCH", /^\/api\/rows\/([^/]+)$/, (m, b) => ["patch_row", { row_id: decodeURIComponent(m[1]), field: b.field, value: b.value ?? null }]],
    ["DELETE", /^\/api\/rows\/([^/]+)$/, (m) => ["delete_row", { row_id: decodeURIComponent(m[1]) }]],
    ["POST", /^\/api\/rows\/special$/, (m, b) => ["add_special_row", { hal: b.hal, row_type: b.type }]],
    ["POST", /^\/api\/rows\/reorder$/, (m, b) => ["reorder_rows", { hal: b.hal, ordered_ids: b.orderedIds }]],
    ["POST", /^\/api\/rows\/swap-warmup-time$/, (m, b) => ["swap_warmup_time", { dragged_id: b.draggedId, target_id: b.targetId }]],
    ["POST", /^\/api\/reset$/, () => ["reset_rows", {}]],
    ["POST", /^\/api\/halls\/warmup$/, (m, b) => ["create_warmup_hall", { name: b.name }]],
    ["PATCH", /^\/api\/halls\/warmup$/, (m, b) => ["rename_warmup_hall", { old_name: b.oldName, new_name: b.newName }]],
    ["DELETE", /^\/api\/halls\/warmup$/, (m, b) => ["delete_warmup_hall", { name: b.name }]],
    ["POST", /^\/api\/halls\/warmup\/priority$/, (m, b) => ["set_priority_hall", { name: b.name }]],
    ["POST", /^\/api\/halls\/show$/, (m, b) => ["create_show_hall", { name: b.name }]],
    ["PATCH", /^\/api\/halls\/show$/, (m, b) => ["rename_show_hall", { old_name: b.oldName, new_name: b.newName }]],
    ["POST", /^\/api\/halls\/show\/starttime$/, (m, b) => ["set_show_hall_start_time", { name: b.name, start_time: b.startTime }]],
    ["DELETE", /^\/api\/halls\/show$/, (m, b) => ["delete_show_hall", { name: b.name }]],
  ];

  let py = null;
  let bridge = null;
  let planJson = "";
  let storageWarned = false;
  let externalChange = () => {};

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = src;
      s.onload = resolve;
      s.onerror = () => reject(new Error(`kunne ikke hente ${src}`));
      document.head.appendChild(s);
    });
  }

  function readStored() {
    try { return localStorage.getItem(PLAN_KEY) || ""; } catch (e) { return ""; }
  }

  function store(json) {
    planJson = json;
    try {
      localStorage.setItem(PLAN_KEY, json);
    } catch (e) {
      if (!storageWarned) {
        storageWarned = true;
        alert("Planen kan ikke gemmes i denne browser (fx i et privat vindue). "
          + "Brug Gem plan under Haller, før du lukker siden.");
      }
    }
  }

  function loadStoredPlan() {
    const stored = readStored();
    const res = JSON.parse(bridge.load(stored));
    if (res.ok) {
      planJson = JSON.stringify(res.plan);
      return;
    }
    // Ulæselig plan: læg den til side, så den kan reddes, og start forfra.
    try {
      localStorage.setItem(`opvarmning_plan_broken_${Date.now()}`, stored);
      localStorage.removeItem(PLAN_KEY);
    } catch (e) { /* intet at gøre */ }
    planJson = "";
  }

  function answer(resJson) {
    const res = JSON.parse(resJson);
    if (!res.ok) throw new ApiError(res.error, res.status);
    store(JSON.stringify(res.plan));
    return res.payload;
  }

  const browserT = {
    async start(onStatus) {
      try {
        onStatus("Henter Python …");
        await loadScript("pyodide/pyodide.js");
        py = await loadPyodide({ indexURL: new URL("pyodide/", document.baseURI).href });
        onStatus("Henter pandas …");
        await py.loadPackage(["pandas"]);
        onStatus("Gør planlæggeren klar …");
        const sitePackages = py.runPython("import sysconfig; sysconfig.get_path('purelib')");
        for (const whl of config.wheels || []) {
          const buf = await (await fetch(`wheels/${whl}`)).arrayBuffer();
          py.unpackArchive(buf, "zip", { extractDir: sitePackages });
        }
        const code = await (await fetch("planner.zip")).arrayBuffer();
        py.unpackArchive(code, "zip", { extractDir: "/home/pyodide/app" });
        py.runPython("import sys; sys.path.insert(0, '/home/pyodide/app')");
        bridge = py.pyimport("planner.browser");
      } catch (e) {
        console.error(e);
        throw new ApiError("Kunne ikke indlæse planlæggeren. Tjek internetforbindelsen og genindlæs siden.", 0);
      }
      loadStoredPlan();
      window.addEventListener("storage", (e) => {
        if (e.key !== PLAN_KEY) return;
        loadStoredPlan();
        externalChange();
      });
    },
    async request(method, url, body) {
      const route = ROUTES.find(([m, re]) => m === method && re.test(url));
      if (!route) throw new ApiError(`Ukendt handling: ${method} ${url}`, 400);
      const [name, args] = route[2](url.match(route[1]), body || {});
      return answer(bridge.call(planJson, name, JSON.stringify(args)));
    },
    async upload(files, hal) {
      const paths = [];
      for (const [i, f] of files.entries()) {
        const dir = `/tmp/upload_${Date.now()}_${i}`;
        py.FS.mkdirTree(dir);
        const path = `${dir}/${f.name}`;
        py.FS.writeFile(path, new Uint8Array(await f.arrayBuffer()));
        paths.push(path);
      }
      return answer(bridge.upload_files(planJson, JSON.stringify(paths), hal || ""));
    },
    async exportPlan() {
      const out = "/tmp/opvisning_med_opvarmning.xlsx";
      bridge.export_to(planJson, out);
      const bytes = py.FS.readFile(out);
      download(new Blob([bytes], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }),
        "opvisning_med_opvarmning.xlsx");
    },
    onExternalChange(cb) { externalChange = cb; },
  };

  const transport = config.mode === "browser" ? browserT : server;

  return {
    mode: config.mode,
    planKey: PLAN_KEY,
    start: (onStatus) => transport.start(onStatus),
    request: (method, url, body) => transport.request(method, url, body),
    upload: (files, hal) => transport.upload(files, hal),
    exportPlan: () => transport.exportPlan(),
    onExternalChange: (cb) => transport.onExternalChange(cb),
  };
})();
```

- [ ] **Step 4: Loading screen and start-up**

In `webapp/static/index.html`, insert right after `<body>`:

```html
<div id="boot" class="boot hidden" role="status" aria-live="polite">
  <div class="boot-box">
    <span class="brand-mark" aria-hidden="true">
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 2.5"/><path d="M9 2h6"/><path d="M12 2v3"/></svg>
    </span>
    <p id="boot-text" class="boot-text">Gør klar …</p>
    <p class="boot-hint">Første gang tager det ca. 20 sekunder.</p>
  </div>
</div>
```

and bump `api.js?v=1` to `api.js?v=2`, `app.js?v=38` to `app.js?v=39`, `style.css?v=…` to the next number.

Append to `webapp/static/style.css` (before the `@media (prefers-reduced-motion` rule):

```css
/* ---------- Indlæsningsskærm (browserudgaven) ---------- */

.boot {
  position: fixed; inset: 0; z-index: 2000;
  display: flex; align-items: center; justify-content: center;
  background: var(--chalk);
}
.boot-box { text-align: center; max-width: 360px; padding: 24px; }
.boot-box .brand-mark { width: 44px; height: 44px; margin-bottom: 16px; }
.boot-text { font-size: 17px; font-weight: 600; margin: 0 0 6px; }
.boot-hint { color: var(--slate); margin: 0; }
.boot.failed .boot-text { color: var(--signal); }
.boot.failed .boot-hint { display: none; }
```

In `webapp/static/app.js`, replace the first two lines of `init()` added in Task 3

```js
  await Api.start(() => {});
  document.getElementById("btn-export").addEventListener("click", () => handle(Api.exportPlan()));
```
with
```js
  const boot = document.getElementById("boot");
  const bootText = document.getElementById("boot-text");
  if (Api.mode === "browser") boot.classList.remove("hidden");
  try {
    await Api.start((text) => { bootText.textContent = text; });
  } catch (e) {
    bootText.textContent = e.message;
    boot.classList.add("failed");
    return;
  }
  boot.classList.add("hidden");
  Api.onExternalChange(async () => {
    STATE = await apiGet("/api/state");
    render();
  });
  document.getElementById("btn-export").addEventListener("click", () => handle(Api.exportPlan()));
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python test_e2e.py browser && python test_e2e.py server`
Expected: both `... passed, 0 failed`. The browser run builds the site first (cached downloads after the first time).

- [ ] **Step 6: Commit**

```bash
git add webapp/static/api.js webapp/static/app.js webapp/static/index.html webapp/static/style.css webapp/test_e2e.py
git commit -m "Run the planner in the browser with Pyodide and localStorage"
```

---

### Task 7: Data-sektion — Om data, Gem plan, Åbn plan, Slet alle data

**Files:**
- Modify: `webapp/static/index.html` (Haller-panelet)
- Modify: `webapp/static/api.js` (tre nye metoder)
- Modify: `webapp/static/app.js` (`init`, ny `onOpenPlan`)
- Modify: `webapp/static/style.css`
- Modify: `webapp/test_e2e.py`

**Interfaces:**
- Consumes: `planner.browser.import_plan` (Task 4), browser-transporten (Task 6).
- Produces (tilføjet til `Api`; i server-tilstand kaster de `ApiError`, og sektionen er skjult):
  - `Api.savePlanFile() -> Promise<void>` — downloader `opvarmningsplan.json`
  - `Api.openPlanFile(text: string) -> Promise<payload>` — kaster `ApiError("Filen er ikke en gyldig plan.", 400)` uden at ændre planen
  - `Api.clearAllData() -> void` — fjerner alle `localStorage`-nøgler, der starter med `opvarmning_`

- [ ] **Step 1: Write the failing test**

In `webapp/test_e2e.py`, append to the end of `browser_only` (after the offline block):

```python
    # ---------- data-sektionen ----------
    page.goto(url)
    page.wait_for_selector("#boot.hidden", state="attached", timeout=120_000)
    page.click("#btn-halls")
    page.wait_for_selector("#halls-panel.show")
    check("Om data-teksten vises",
          "Dine data gemmes kun i denne browser. De sendes ikke til nogen server. Skriv ikke personnavne i Excel-filen."
          in page.inner_text("#data-section"))
    page.fill("#warmup-hall-form input", "Varm X")
    page.press("#warmup-hall-form input", "Enter")
    page.wait_for_function("() => STATE.warmupHalls.includes('Varm X')")

    with page.expect_download() as dl:
        page.click("#btn-save-plan")
    check("Gem plan henter opvarmningsplan.json", dl.value.suggested_filename == "opvarmningsplan.json")
    saved = Path(dl.value.path())

    bad = saved.with_name("forkert.json")
    bad.write_text('{"raw_rows": "nej"}', encoding="utf-8")
    before = page.evaluate("() => JSON.stringify(STATE.warmupHalls)")
    page.set_input_files("#plan-file-input", str(bad))
    page.wait_for_timeout(500)
    check("Åbn plan med ugyldig fil giver besked og ændrer intet",
          any("ikke en gyldig plan" in d for d in dialogs) and page.evaluate("() => JSON.stringify(STATE.warmupHalls)") == before)

    page.click("#btn-clear-data")   # bekræftelsen accepteres af dialog-handleren
    page.wait_for_selector("#onboarding:not(.hidden)", timeout=120_000)
    left = page.evaluate("() => Object.keys(localStorage).filter(k => k.startsWith('opvarmning_'))")
    check("Slet alle data fjerner alt og viser 'Kom i gang'", left == [] and page.evaluate("() => STATE.warmupHalls.length") == 0, left)

    page.click("#btn-halls")
    page.wait_for_selector("#halls-panel.show")
    page.set_input_files("#plan-file-input", str(saved))
    page.wait_for_function("() => STATE.warmupHalls.includes('Varm X')", timeout=10_000)
    check("Åbn plan indlæser en gemt plan", True)
```

And in `run()`, right after `common_flow(...)` for server mode, add a check that the section is hidden there:

```python
            if mode == "server":
                check("data-sektionen er skjult i serverudgaven", page.is_hidden("#data-section"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python test_e2e.py browser`
Expected: FAIL on "Om data-teksten vises" (`#data-section` does not exist).

- [ ] **Step 3: Write minimal implementation**

In `webapp/static/index.html`, insert before `<div class="hall-group danger-zone">` in the Haller panel:

```html
    <div id="data-section" class="hall-group data-section hidden">
      <h3 class="hall-group-title">Om data</h3>
      <p class="hall-group-text">Dine data gemmes kun i denne browser. De sendes ikke til nogen server. Skriv ikke personnavne i Excel-filen.</p>
      <div class="data-actions">
        <button id="btn-save-plan" type="button" class="btn btn-sm btn-outline-secondary">Gem plan</button>
        <button id="btn-open-plan" type="button" class="btn btn-sm btn-outline-secondary">Åbn plan</button>
        <input type="file" id="plan-file-input" accept=".json,application/json" class="visually-hidden" tabindex="-1">
        <button id="btn-clear-data" type="button" class="btn btn-sm btn-outline-danger">Slet alle data</button>
      </div>
    </div>
```

Append to `webapp/static/style.css` (before `@media (prefers-reduced-motion`):

```css
.data-actions { display: flex; flex-wrap: wrap; gap: 8px; }
```

In `webapp/static/api.js`, add to `server`:

```js
    async savePlanFile() { throw new ApiError("Kun i browserudgaven.", 400); },
    async openPlanFile() { throw new ApiError("Kun i browserudgaven.", 400); },
    clearAllData() {},
```

add to `browserT`:

```js
    async savePlanFile() {
      download(new Blob([planJson || JSON.stringify(JSON.parse(bridge.load("")).plan)], { type: "application/json" }),
        "opvarmningsplan.json");
    },
    async openPlanFile(text) {
      const res = JSON.parse(bridge.import_plan(text));
      if (!res.ok) throw new ApiError(res.error, res.status);
      store(JSON.stringify(res.plan));
      return answer(bridge.call(planJson, "payload", "{}"));
    },
    clearAllData() {
      try {
        Object.keys(localStorage).filter((k) => k.startsWith("opvarmning_")).forEach((k) => localStorage.removeItem(k));
      } catch (e) { /* intet gemt */ }
    },
```

and to the returned object:

```js
    savePlanFile: () => transport.savePlanFile(),
    openPlanFile: (text) => transport.openPlanFile(text),
    clearAllData: () => transport.clearAllData(),
```

In `webapp/static/app.js`, add at the end of `init()`:

```js
  if (Api.mode === "browser") {
    document.getElementById("data-section").classList.remove("hidden");
    const planInput = document.getElementById("plan-file-input");
    document.getElementById("btn-save-plan").addEventListener("click", () => handle(Api.savePlanFile()));
    document.getElementById("btn-open-plan").addEventListener("click", () => planInput.click());
    planInput.addEventListener("change", () => onOpenPlan(planInput));
    document.getElementById("btn-clear-data").addEventListener("click", () => {
      if (!confirm("Slet planen og alle haller fra denne browser? Det kan ikke fortrydes.")) return;
      Api.clearAllData();
      location.reload();
    });
  }
```

and add this function next to `onReset`:

```js
async function onOpenPlan(input) {
  const file = input.files[0];
  input.value = "";
  if (!file) return;
  if (STATE.rows.length && !confirm("Erstat den nuværende plan med planen fra filen?")) return;
  STATE = await handle(Api.openPlanFile(await file.text()));
  activeHal = STATE.showHalls.length ? STATE.showHalls[0].name : null;
  saveActiveHal();
  render();
}
```

Bump the `?v=` numbers for `api.js`, `app.js` and `style.css` in `index.html`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python test_e2e.py browser && python test_e2e.py server`
Expected: both `... passed, 0 failed`.

- [ ] **Step 5: Commit**

```bash
git add webapp/static/index.html webapp/static/api.js webapp/static/app.js webapp/static/style.css webapp/test_e2e.py
git commit -m "Add data section: about data, save/open plan, delete all data"
```

---

### Task 8: GitHub Actions-udgivelse og dokumentation

**Files:**
- Create: `.github/workflows/pages.yml`
- Modify: `webapp/README.md`
- Modify: `webapp/requirements.txt`

**Interfaces:**
- Consumes: `test_engine.py`, `test_actions.py`, `test_api.py`, `build_site.py` (Task 1–5).
- Produces: udgivelse til `https://chjorsal.github.io/Gymnastik/` ved push til `main`.

- [ ] **Step 1: Write the workflow**

Create `.github/workflows/pages.yml`:

```yaml
name: Udgiv på GitHub Pages

on:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: true

jobs:
  build:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: webapp
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - name: Installér
        run: pip install -r requirements.txt
      - name: Test
        run: |
          python test_engine.py
          python test_actions.py
          python test_api.py
      - name: Byg siden
        run: python build_site.py --out ../site
      - uses: actions/upload-pages-artifact@v3
        with:
          path: site

  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - id: deployment
        uses: actions/deploy-pages@v4
```

- [ ] **Step 2: Validate the workflow locally**

Run (from repo root): `python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/pages.yml')); print('ok')"`
Expected: `ok` (install `pyyaml` in the scratch environment if missing; do not add it to `requirements.txt`).

Then run the same commands the workflow runs, from `webapp/`:
`pip install -r requirements.txt && python test_engine.py && python test_actions.py && python test_api.py && python build_site.py --out ../site`
Expected: all tests `0 failed`, "Bygget til …/site".

- [ ] **Step 3: Update requirements and README**

Replace `webapp/requirements.txt`:

```
fastapi
uvicorn
pandas
openpyxl
python-multipart
# kun til browsertesten (test_e2e.py):
# playwright
```

In `webapp/README.md`, replace the `## Kodestruktur` section (to the end of the file) with:

````markdown
## Kodestruktur

```
app.py              webserver (FastAPI) — tynd skal om planner.actions
planner/
  actions.py        alle handlinger på en plan (upload, ret, flyt, haller, eksport)
  browser.py        JSON-bro til browserudgaven (Pyodide)
engine/             beregningsmotoren — bruges af både hjemmesiden og scriptet
  config.py         faste standardværdier og nøgleordslister
  rules.py          holdtype, alder, opvarmnings-/gangtid og prioritet
  values.py         robuste konverteringer (NaN, klokkeslæt, id'er)
  importer.py       Excel -> rækker -> DataFrame med opvisningstider
  placement.py      placeringsalgoritmen for opvarmning
  serialize.py      plan -> JSON til frontenden
  export.py         plan -> Excel-fil
static/             frontend (HTML, CSS, JS); api.js vælger server eller browser
build_site.py       bygger browserudgaven til ../site
```

## To udgaver

- **Server** (`python app.py`): planen gemmes i `state.json`.
- **Browser** (GitHub Pages): Python-motoren kører i browseren med Pyodide,
  og planen gemmes i brugerens egen browser (`localStorage`). Ingen data
  sendes til en server. Byg lokalt med `python build_site.py` og åbn
  `../site/index.html` via en webserver, fx
  `python -m http.server --directory ../site`.

Udgivelse: hvert push til `main` tester, bygger og udgiver siden via
`.github/workflows/pages.yml` på https://chjorsal.github.io/Gymnastik/.
Engangsopsætning på GitHub: Settings → Pages → Source: **GitHub Actions**.

## Test

```
python test_engine.py        motoren
python test_actions.py       handlinger og browser-bro (uden server)
python test_api.py           røgtest af serveren (starter sin egen)
python test_build_site.py    browserudgavens build (kræver internet første gang)
python test_e2e.py server    browsertest mod serveren   (kræver playwright + Edge)
python test_e2e.py browser   browsertest mod browserudgaven
```

Kommandolinje-versionen (`../lav_opvarmning_final.py fil1.xlsx ...`) bruger
den samme `engine`. Kør én dag ad gangen.
````

- [ ] **Step 4: Run the full suite**

Run: `python test_engine.py && python test_actions.py && python test_api.py && python test_build_site.py && python test_e2e.py server && python test_e2e.py browser`
Expected: every run ends with `0 failed`.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/pages.yml webapp/README.md webapp/requirements.txt
git commit -m "Publish the browser version to GitHub Pages via GitHub Actions"
```

- [ ] **Step 6: Hand-off (requires the owner)**

Do **not** push or merge without the owner's explicit yes. When approved:
1. Merge `redesign` into `main` and push `main`.
2. Owner enables Settings → Pages → Source: GitHub Actions.
3. Watch the "Udgiv på GitHub Pages" run; open `https://chjorsal.github.io/Gymnastik/` and do one upload and one export.
