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
    # omdøbt (HoldEdited) eller selv tilføjet (Manual) røres ikke.
    for row in data["raw_rows"]:
        if row.get("Type") in ("hold", "andet") and not row.get("HoldEdited") and not row.get("Manual"):
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
        if row.get("Type") == "hold" and not row.get("Manual"):
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


def move_rows(plan: dict, row_ids: List[str], hal: str) -> None:
    """Flytter flere hold/punkter til en anden opvisningshal på én gang. De
    lægges nederst i hallen i den rækkefølge, de havde i programmet."""
    if not row_ids:
        raise ActionError("Vælg mindst ét hold")
    if _find_show_hal(plan, hal) is None:
        raise ActionError("Opvisningshal ikke fundet", 404)
    wanted = set(row_ids)
    rows = [r for r in plan["raw_rows"] if r["id"] in wanted]
    if not rows:
        raise ActionError("De valgte hold findes ikke længere", 404)
    order = _next_order(plan, hal)
    for r in sorted(rows, key=lambda r: (r["OpvisningHal"], r["Order"])):
        if r["OpvisningHal"] == hal:
            continue
        r["OpvisningHal"] = hal
        r["Order"] = order
        order += 1


def delete_rows(plan: dict, row_ids: List[str]) -> None:
    """Sletter flere hold/punkter på én gang (fx ved afbud)."""
    if not row_ids:
        raise ActionError("Vælg mindst ét hold")
    wanted = set(row_ids)
    plan["raw_rows"] = [r for r in plan["raw_rows"] if r["id"] not in wanted]


def add_special_row(plan: dict, hal: str, row_type: str) -> None:
    if row_type not in SPECIAL_TYPES:
        raise ActionError("Ukendt type")
    if _find_show_hal(plan, hal) is None:
        raise ActionError("Opvisningshal ikke fundet", 404)
    plan["raw_rows"].append(engine.new_special_row(hal, row_type, _next_order(plan, hal)))


MANUAL_TEAM_MINUTES = 15   # standard for et hold tilføjet i hånden: opvisning og opvarmning


def add_team(plan: dict, hal: str, name: str) -> None:
    """Tilføjer et hold i hånden (fx tilmeldt på bagkant) nederst i hallen med
    15 min opvisning og 15 min opvarmning. Begge kan rettes bagefter."""
    name = (name or "").strip()
    if not name:
        raise ActionError("Skriv et holdnavn")
    if _find_show_hal(plan, hal) is None:
        raise ActionError("Opvisningshal ikke fundet", 404)
    plan["raw_rows"].append({
        "id": engine.new_id(),
        "Hold": name,
        "Type": "hold",
        "AntalPersoner": 0,
        "HoldtypeRaw": None,
        "AlderRaw": None,
        "OpvisningHal": hal,
        "Varighed": MANUAL_TEAM_MINUTES,
        "OpvarmningMinOverride": MANUAL_TEAM_MINUTES,
        "OpvarmningHalOverride": None,
        "OpvarmningStartOverride": None,
        "Order": _next_order(plan, hal),
        "Manual": True,
    })


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


def _views(plan: dict) -> dict:
    return {r["id"]: r for r in engine.to_row_dicts(_compute(plan), plan["warmup_halls"])}


def _ok_ids(views: dict) -> set:
    return {rid for rid, r in views.items() if r["status"] == "OK"}


def place_warmup(plan: dict, row_id: str, hal: str, start: str) -> None:
    """Lægger et holds opvarmning fast i en bestemt hal og et bestemt
    tidspunkt (træk-og-slip på tidslinjen). Afvises, hvis holdet så ikke kan
    nå sin opvisning, eller hvis det skubber et andet hold ud."""
    row = _find_row(plan, row_id)
    if row is None:
        raise ActionError("Hold ikke fundet", 404)
    if row.get("Type") != "hold":
        raise ActionError("Kun hold har opvarmning — pauser og andre programpunkter kan ikke placeres")
    if hal not in plan["warmup_halls"]:
        raise ActionError("Opvarmningshal ikke fundet")
    start_n = normalize_hhmm(start)
    if start_n is None:
        raise ActionError(f"'{start}' er ikke et gyldigt klokkeslæt — skriv fx 09:30")

    ok_before = _ok_ids(_views(plan)) - {row_id}
    before = (row.get("OpvarmningHalOverride"), row.get("OpvarmningStartOverride"))
    row["OpvarmningHalOverride"], row["OpvarmningStartOverride"] = hal, start_n
    after = _views(plan)
    if after[row_id]["status"] != "OK" or not ok_before <= _ok_ids(after):
        row["OpvarmningHalOverride"], row["OpvarmningStartOverride"] = before
        raise ActionError(
            f"Der er ikke plads til '{row['Hold']}' i {hal} kl. {start_n} — tiden overlapper "
            "et andet hold, eller holdet når ikke sin opvisning"
        )


SUGGEST_MIN_MINUTES = 10   # kortere opvarmning end dette foreslås aldrig
# Efterskoler og DGI-hold beholder altid deres 30 min, medmindre I selv
# ændrer det — de forkortes aldrig af forslag eller "Find løsning".
PROTECTED_TYPES = {"efterskole", "dgi"}
SUGGEST_MAX_TEAMS = 10     # begræns beregningen, hvis rigtig mange hold mangler plads


def suggest_warmups(plan: dict) -> List[dict]:
    """For hvert hold uden plads: den længste opvarmning ned til 10 min, der
    giver plads uden at skubbe andre hold ud. Ændrer ikke planen."""
    views = _views(plan)
    ok_before = _ok_ids(views)
    unplaced = [r for r in views.values() if r["needsWarmup"] and r["status"] == "KAN IKKE PLANLÆGGES"
                and r["holdtype"] not in PROTECTED_TYPES]
    suggestions = []
    for u in unplaced[:SUGGEST_MAX_TEAMS]:
        current = u["opvarmningMinOverride"] if u["opvarmningMinOverride"] is not None else u["opvarmningMinDefault"]
        for minutes in range(current - 1, SUGGEST_MIN_MINUTES - 1, -1):
            trial = copy.deepcopy(plan)
            _find_row(trial, u["id"])["OpvarmningMinOverride"] = minutes
            after = _views(trial)
            r = after[u["id"]]
            if r["status"] == "OK" and ok_before <= _ok_ids(after):
                suggestions.append({
                    "id": u["id"], "hold": u["hold"], "minutes": minutes,
                    "hal": r["opvarmningHalBeregnet"], "start": r["opvarmningStart"], "end": r["opvarmningSlut"],
                    "opvisningHal": u["opvisningHal"], "opvisningTid": u["opvisningTid"],
                })
                break
    return suggestions


SOLVE_MAX_REDUCTION = 5    # højst så mange minutter kortere pr. hold
SOLVE_MAX_NEIGHBOURS = 6   # højst så mange hold omkring holdet forkortes


def _effective_minutes(view: dict) -> int:
    o = view["opvarmningMinOverride"]
    return o if o is not None else view["opvarmningMinDefault"]


def solve_warmups(plan: dict) -> dict:
    """Prøver at give hold uden plads en opvarmning ved at forkorte holdet
    selv og holdene, der varmer op samtidig (ned til 10 min, aldrig
    efterskoler eller DGI-hold). Små ændringer på få hold foretrækkes. Holdene tages ét ad
    gangen efter opvisningstid, og der regnes forfra efter hver løsning.
    Ændrer ikke planen — returnerer forslaget."""
    work = copy.deepcopy(plan)
    original = _views(plan)
    progress = True
    tried_without_luck = set()
    while progress:
        progress = False
        views = _views(work)
        ok_now = _ok_ids(views)
        unplaced = sorted(
            (v for v in views.values() if v["needsWarmup"] and v["status"] == "KAN IKKE PLANLÆGGES"
             and v["id"] not in tried_without_luck),
            key=lambda v: v["opvisningMin"] if v["opvisningMin"] is not None else 0,
        )
        for u in unplaced:
            walk = engine.gang_tid()
            latest = u["opvisningMin"] - walk
            window = (latest - engine.MAX_EARLY_TOTAL_MIN - _effective_minutes(u), latest)
            centre = sum(window) / 2
            neighbours = sorted(
                (v for v in views.values()
                 if v["status"] == "OK" and v["holdtype"] not in PROTECTED_TYPES
                 and v["opvarmningStartMin"] < window[1] and v["opvarmningSlutMin"] > window[0]),
                key=lambda v: abs((v["opvarmningStartMin"] + v["opvarmningSlutMin"]) / 2 - centre),
            )[:SOLVE_MAX_NEIGHBOURS]
            own = [] if u["holdtype"] in PROTECTED_TYPES else [u]
            # billigste forsøg først: få minutter på få hold
            attempts = sorted(
                ((d, n) for d in range(1, SOLVE_MAX_REDUCTION + 1) for n in range(len(neighbours) + 1)),
                key=lambda dn: (dn[0] * (len(own) + dn[1]), dn[0]),
            )
            for d, n in attempts:
                group = own + neighbours[:n]
                changes = {v["id"]: max(SUGGEST_MIN_MINUTES, _effective_minutes(v) - d) for v in group}
                if all(changes[v["id"]] == _effective_minutes(v) for v in group):
                    continue
                trial = copy.deepcopy(work)
                for rid, minutes in changes.items():
                    _find_row(trial, rid)["OpvarmningMinOverride"] = minutes
                after = _views(trial)
                if after[u["id"]]["status"] == "OK" and ok_now <= _ok_ids(after):
                    work = trial
                    progress = True
                    break
            else:
                tried_without_luck.add(u["id"])
                continue
            break   # regn forfra efter hver løsning

    final = _views(work)
    changes = []
    for rid, v in final.items():
        before, after = _effective_minutes(original[rid]), _effective_minutes(v)
        if before != after:
            changes.append({"id": rid, "hold": v["hold"], "from": before, "to": after,
                            "opvisningHal": v["opvisningHal"], "opvisningTid": v["opvisningTid"]})
    was_unplaced = [v for v in original.values() if v["needsWarmup"] and v["status"] == "KAN IKKE PLANLÆGGES"]
    return {
        "changes": sorted(changes, key=lambda c: (c["opvisningHal"], c["opvisningTid"])),
        "placed": [v["hold"] for v in was_unplaced if final[v["id"]]["status"] == "OK"],
        "remaining": [v["hold"] for v in was_unplaced if final[v["id"]]["status"] != "OK"],
    }


def apply_warmup_minutes(plan: dict, changes: List[dict]) -> None:
    """Sætter opvarmningstiden for flere hold på én gang (fra "Find løsning")."""
    rows = []
    for c in changes:
        row = _find_row(plan, c.get("id"))
        if row is None:
            raise ActionError("Et af holdene findes ikke længere — find løsningen igen", 404)
        try:
            minutes = int(c.get("minutes"))
        except (TypeError, ValueError):
            raise ActionError("Ugyldig opvarmningstid")
        if minutes < 1:
            raise ActionError("Opvarmningstiden skal være mindst 1 min")
        rows.append((row, minutes))
    for row, minutes in rows:
        row["OpvarmningMinOverride"] = minutes


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
