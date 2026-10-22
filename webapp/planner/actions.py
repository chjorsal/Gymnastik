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
import re
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

# Længste opvarmning: den må starte højst 45 min før holdet går på og skal
# slutte, så der er 5 min til at gå over.
MAX_WARMUP_MINUTES = engine.MAX_START_BEFORE_MIN - engine.GANG_MIN

# En ny plan starter med én opvisningshal, så man kan trække Excel-filen
# direkte ind på den. Navnet kan rettes bagefter.
DEFAULT_SHOW_HALL = "Hal 1"


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


def start_plan() -> dict:
    """Planen en ny bruger starter med: en tom plan med opvisningshallen Hal 1."""
    plan = new_plan()
    create_show_hall(plan, DEFAULT_SHOW_HALL)
    return plan


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
            if reclassified != "hold" and engine.is_team_by_forening(row.get("Hold"), row.get("Forening")):
                reclassified = "hold"
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


DEFAULT_EXPORT_NAME = "opvisning_med_opvarmning"
_ILLEGAL_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_FILENAMES = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
                       *(f"lpt{i}" for i in range(1, 10))}
MAX_EXPORT_NAME = 100


def export_filename(name: Optional[str]) -> str:
    """Brugerens navn til Excel-filen gjort sikkert: tegn Windows ikke
    tillader bliver til mellemrum, højst 100 tegn, og altid med .xlsx."""
    text = " ".join(_ILLEGAL_FILENAME_CHARS.sub(" ", str(name or "")).split())
    if text.lower().endswith(".xlsx"):
        text = text[:-5]
    text = text.strip(" .")[:MAX_EXPORT_NAME].rstrip(" .")
    if not text:
        text = DEFAULT_EXPORT_NAME
    first, dot, rest = text.partition(".")
    if first.lower() in _RESERVED_FILENAMES:   # fx CON eller con.backup
        text = f"{first}_{dot}{rest}"
    return f"{text}.xlsx"


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


def _rows_in(plan: dict, hal_name: str) -> List[dict]:
    return [r for r in plan["raw_rows"] if r["OpvisningHal"] == hal_name]


def _next_order(plan: dict, hal_name: str) -> int:
    orders = [r["Order"] for r in _rows_in(plan, hal_name)]
    return (max(orders) + 1) if orders else 0


def _efterskole_hall(plan: dict) -> Optional[str]:
    """Efterskolernes hal: hallen med stjernen (ellers den første)."""
    if plan["priority_hall"] in plan["warmup_halls"]:
        return plan["priority_hall"]
    return plan["warmup_halls"][0] if plan["warmup_halls"] else None


def _is_efterskole(row: dict) -> bool:
    """Som motoren afgør det: Holdtype-kolonnen eller 'efterskole' i navnet."""
    return engine.read_holdtype(row.get("HoldtypeRaw")) == "efterskole" or (
        engine.read_holdtype(row.get("HoldtypeRaw")) == "ukendt"
        and any(w in str(row.get("Hold") or "").lower() for w in ("efterskole", "akademiet")))


def _find_row(plan: dict, row_id: str) -> Optional[dict]:
    return next((r for r in plan["raw_rows"] if r["id"] == row_id), None)


def _views(plan: dict) -> dict:
    return {r["id"]: r for r in engine.to_row_dicts(_compute(plan), plan["warmup_halls"])}


def _ok_ids(views: dict) -> set:
    return {rid for rid, r in views.items() if r["status"] == "OK"}


def _effective_minutes(view: dict) -> int:
    o = view["opvarmningMinOverride"]
    return o if o is not None else view["opvarmningMinDefault"]


# ======================================================
# RÆKKER
# ======================================================

def upload(plan: dict, files: List[Tuple[str, bytes]], show_hal: Optional[str] = None) -> None:
    """Indlæser Excel-filer i én opvisningshal. Uden show_hal bruges den
    første opvisningshal, og findes der ingen, oprettes Hal 1. Alle filer
    valideres, før planen ændres."""
    first_hal = plan["show_halls"][0]["name"] if plan["show_halls"] else DEFAULT_SHOW_HALL
    hal_name = (show_hal or "").strip() or first_hal

    loaded = []  # (rækker, foreslået starttid) pr. fil
    for filename, content in files:
        try:
            loaded.append(engine.load_excel_bytes(filename, content, hal_name, 0))
        except Exception as e:
            raise ActionError(f"Kunne ikke læse '{filename}' — er det en gyldig Excel-fil (.xlsx)? ({e})")

    file_start = next((start for _, start in loaded if start), None)
    hal = _find_show_hal(plan, hal_name)
    if hal is None:
        plan["show_halls"].append({"name": hal_name, "startTime": file_start or "09:00"})
    elif file_start and not hal.get("startTimeSet") and not _rows_in(plan, hal_name):
        # Tom hal: filens første 'Tid' gælder, medmindre brugeren selv har
        # skrevet en starttid for hallen.
        hal["startTime"] = file_start

    order = _next_order(plan, hal_name)
    for rows, _ in loaded:
        for row in rows:
            row["Order"] = order
            order += 1
        plan["raw_rows"].extend(rows)


def upload_to_halls(plan: dict, groups: List[Tuple[str, List[Tuple[str, bytes]]]]) -> None:
    """Indlæser filer i flere opvisningshaller på én gang ("Lav opvarmningsplan"
    på Kom i gang). groups: [(hal, [(filnavn, indhold)])]. Er blot én fil
    ugyldig, ændres planen slet ikke."""
    if not any(files for _, files in groups):
        raise ActionError("Læg mindst én Excel-fil klar under en opvisningshal")
    trial = copy.deepcopy(plan)
    for hal, files in groups:
        if not (hal or "").strip():
            raise ActionError("Vælg hvilken opvisningshal filen skal i")
        upload(trial, files, hal)
    plan.clear()
    plan.update(trial)


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
        if value is not None and value > MAX_WARMUP_MINUTES:
            raise ActionError(f"Opvarmningen kan højst vare {MAX_WARMUP_MINUTES} min — den må starte højst "
                              f"{engine.MAX_START_BEFORE_MIN} min før holdet går på, og der skal være "
                              f"{engine.GANG_MIN} min til at gå over")
    if key == "Hold":
        if row.get("Type") == "hold" and not row.get("Manual"):
            raise ActionError("Holdnavn fra Excel-importen kan ikke ændres")
        value = str(value or "").strip()
        row["HoldEdited"] = True
    if key == "OpvisningHal":
        name = str(value or "").strip()
        if not name:
            raise ActionError("Vælg hvilken opvisningshal holdet skal i")
        if _find_show_hal(plan, name) is None:
            plan["show_halls"].append({"name": name, "startTime": "09:00"})
        if name and name != row["OpvisningHal"]:
            row["Order"] = _next_order(plan, name)
        value = name
    if key == "OpvarmningHalOverride":
        name = str(value or "").strip()
        value = name if name in plan["warmup_halls"] else None
        if value and _is_efterskole(row) and value != _efterskole_hall(plan):
            raise ActionError(f"Efterskoler varmer kun op i efterskolernes hal ({_efterskole_hall(plan)}). "
                              "Flyt stjernen under Haller, hvis det skal være en anden hal")
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
    plan["raw_rows"].append(engine.new_row(
        name, "hold", hal, MANUAL_TEAM_MINUTES, _next_order(plan, hal),
        OpvarmningMinOverride=MANUAL_TEAM_MINUTES, Manual=True,
    ))


def reorder_rows(plan: dict, hal: str, ordered_ids: List[str]) -> None:
    """Ny rækkefølge i en opvisningshal. Id'er fra andre haller og dubletter
    ignoreres, og punkter der mangler i listen, beholder deres indbyrdes
    rækkefølge til sidst — så to punkter aldrig får samme plads."""
    in_hal = sorted((r for r in plan["raw_rows"] if r["OpvisningHal"] == hal), key=lambda r: r["Order"])
    by_id = {r["id"]: r for r in in_hal}
    wanted = list(dict.fromkeys(rid for rid in ordered_ids if rid in by_id))
    rest = [r["id"] for r in in_hal if r["id"] not in set(wanted)]
    for i, rid in enumerate(wanted + rest):
        by_id[rid]["Order"] = i


def swap_warmup_time(plan: dict, dragged_id: str, target_id: str) -> None:
    """Det trukne hold overtager målholdets (tidligere) opvarmningstid, og
    målholdet får det trukne holds (senere) tid. Afvises, hvis et af holdene
    så ikke kan nå sin opvisning."""
    dragged = _find_row(plan, dragged_id)
    target = _find_row(plan, target_id)
    if dragged is None or target is None:
        raise ActionError("Hold ikke fundet", 404)

    rows_now = _views(plan)
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

    after = _views(plan)
    if after[dragged_id]["status"] != "OK" or after[target_id]["status"] != "OK":
        for r, start, hal in before:
            r["OpvarmningStartOverride"], r["OpvarmningHalOverride"] = start, hal
        raise ActionError(
            f"Byttet giver ikke tid nok: '{target['Hold']}' kan ikke nå sin opvisning med det senere tidspunkt"
        )


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
    if _is_efterskole(row) and hal != _efterskole_hall(plan):
        raise ActionError(f"Efterskoler varmer kun op i efterskolernes hal ({_efterskole_hall(plan)})")
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
            f"Der er ikke plads til '{row['Hold']}' i {hal} kl. {start_n} — tiden overlapper et andet "
            f"hold, holdet når ikke sin opvisning, eller opvarmningen starter mere end "
            f"{engine.MAX_START_BEFORE_MIN} min før holdet går på"
        )


SOLVE_MIN_MINUTES = 10     # kortere opvarmning end dette foreslås aldrig
# Efterskoler og DGI-hold beholder altid deres 30 min, medmindre I selv
# ændrer det — de forkortes aldrig af "Find løsning".
PROTECTED_TYPES = {"efterskole", "dgi"}
SOLVE_MAX_REDUCTION = 5    # højst så mange minutter kortere pr. hold
SOLVE_MAX_NEIGHBOURS = 6   # højst så mange hold omkring holdet forkortes


def _fits(work: dict, team_id: str, ok_now: set, change) -> Optional[dict]:
    """En kopi af work med change(kopi) lavet — hvis holdet så får plads, og
    ingen af holdene i ok_now mister deres. Ellers None."""
    trial = copy.deepcopy(work)
    change(trial)
    after = _views(trial)
    return trial if after[team_id]["status"] == "OK" and ok_now <= _ok_ids(after) else None


def _lock_to(team_id: str, hal: str):
    def change(trial):
        _find_row(trial, team_id)["OpvarmningHalOverride"] = hal
    return change


def _halls_for(plan: dict, v: dict) -> List[str]:
    """De haller holdet må varme op i: efterskoler kun i prioritetshallen."""
    if v["holdtype"] == "efterskole":
        hal = _efterskole_hall(plan)
        return [hal] if hal else []
    return list(plan["warmup_halls"])


def _try_other_halls(work: dict, u: dict, ok_now: set, halls: List[str]) -> Optional[dict]:
    """Giv holdet pladsen i en af hallerne først; de andre hold kan så rykke
    over i andre haller. Koster ingen minutter."""
    for hal in halls:
        trial = _fits(work, u["id"], ok_now, _lock_to(u["id"], hal))
        if trial:
            return trial
    return None


def _earliest_start(v: dict) -> int:
    """Det tidligste, holdets opvarmning må starte (minutter fra dagens start):
    højst 45 min før det går på, og højst 30 min ventetid efter opvarmningen."""
    warm = _effective_minutes(v)
    return max(v["opvisningMin"] - engine.MAX_START_BEFORE_MIN,
               v["opvisningMin"] - engine.GANG_MIN - engine.MAX_EARLY_TOTAL_MIN - warm)


def _try_earlier_neighbour(work: dict, u: dict, views: dict, ok_now: set, halls: List[str],
                           user_fixed: set) -> Optional[dict]:
    """Ryk ét af holdene, der varmer op i u's tidsrum, lidt tidligere (inden
    for dets egne grænser), så der bliver et hul til u. Siden lægger ellers
    altid opvarmningen så sent som muligt. Det hold, der rykkes, får en fast
    tid; ingen kortere opvarmning. Mindste flytning først."""
    lo = u["opvisningMin"] - engine.MAX_START_BEFORE_MIN
    hi = u["opvisningMin"] - engine.GANG_MIN
    near = [v for v in views.values()
            if v["status"] == "OK" and v["id"] not in user_fixed and v["opvarmningHalBeregnet"] in halls
            and v["opvarmningStartMin"] < hi and v["opvarmningSlutMin"] > lo]
    # Præcis den flytning, der giver u plads lige efter holdet (u så sent som
    # muligt); ellers ingen. Kæder af flere hold klares af _try_repack.
    u_latest_start = hi - _effective_minutes(u)
    options = sorted(
        ((v["opvarmningSlutMin"] - u_latest_start, v) for v in near
         if 0 < v["opvarmningSlutMin"] - u_latest_start <= v["opvarmningStartMin"] - _earliest_start(v)),
        key=lambda sv: sv[0])
    for shift, v in options:
        start = v["opvarmningStartMin"] - shift

        def change(trial, v=v, start=start):
            row = _find_row(trial, v["id"])
            row["OpvarmningStartOverride"] = f"{start // 60:02d}:{start % 60:02d}"
            row["OpvarmningHalOverride"] = v["opvarmningHalBeregnet"]
        trial = _fits(work, u["id"], ok_now, change)
        if trial:
            return trial
    return None


REPACK_MAX_TEAMS = 12   # højst så mange hold i én kæde, der pakkes om


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _try_repack(work: dict, plan: dict, u: dict, views: dict, ok_now: set, hal: str,
                time_fixed: set) -> Optional[dict]:
    """Pak holdene i hallen bagfra. Kæden er holdet uden plads plus de hold,
    der KUN kan være i hallen (efterskoler i efterskolernes hal og hold låst
    til hallen) og hvis tidsrum hænger sammen med det. Det hold, der går senest
    på, lægges så sent som muligt; det næste så sent som muligt, men før det
    forrige — osv. (findes der en plads til alle, finder den den). Hold med en
    fast tid, som brugeren selv har sat, står fast; kæden lægges uden om dem.
    Almindelige hold i hallen finder selv en anden hal, når planen regnes om."""
    eft_hall = _efterskole_hall(plan)

    def bound(v):
        lock = engine.override_str(_find_row(work, v["id"]).get("OpvarmningHalOverride"))
        if v["holdtype"] == "efterskole":
            return hal == eft_hall
        return lock == hal

    def window(v):
        return _earliest_start(v), v["opvisningMin"] - engine.GANG_MIN

    obstacles = sorted((v["opvarmningStartMin"], v["opvarmningSlutMin"]) for v in views.values()
                       if v["status"] == "OK" and v["opvarmningHalBeregnet"] == hal and v["id"] in time_fixed)
    candidates = [v for v in views.values()
                  if v["status"] == "OK" and v["opvarmningHalBeregnet"] == hal and v["id"] not in time_fixed
                  and v["id"] != u["id"] and bound(v)]
    chain, (lo, hi) = [u], window(u)
    grew = True
    while grew and len(chain) < REPACK_MAX_TEAMS:
        grew = False
        for v in candidates:
            w0, w1 = window(v)
            if v not in chain and w0 < hi and w1 > lo:
                chain.append(v)
                lo, hi = min(lo, w0), max(hi, w1)
                grew = True
    if len(chain) < 2:
        return None

    plan_times, cursor = {}, None
    for v in sorted(chain, key=lambda v: (window(v)[1], v["opvisningMin"]), reverse=True):
        earliest, end = window(v)
        if cursor is not None:
            end = min(end, cursor)
        warm = _effective_minutes(v)
        moved = True
        while moved:   # uden om faste tider
            moved = False
            for a, b in obstacles:
                if end - warm < b and a < end:
                    end, moved = a, True
        if end - warm < earliest:
            return None
        plan_times[v["id"]] = end - warm
        cursor = end - warm

    def change(trial):
        for rid, start in plan_times.items():
            row = _find_row(trial, rid)
            row["OpvarmningStartOverride"] = _hhmm(start)
            row["OpvarmningHalOverride"] = hal
    return _fits(work, u["id"], ok_now, change)


def _try_shorter(work: dict, u: dict, views: dict, ok_now: set, halls: List[str]) -> Optional[dict]:
    """Forkort holdet selv og holdene, der varmer op samtidig i de haller,
    holdet kan bruge (ned til 10 min, aldrig efterskoler eller DGI-hold).
    Små ændringer på få hold først."""
    latest = u["opvisningMin"] - engine.gang_tid()
    window = (max(latest - engine.MAX_EARLY_TOTAL_MIN - _effective_minutes(u),
                  u["opvisningMin"] - engine.MAX_START_BEFORE_MIN), latest)
    centre = sum(window) / 2
    neighbours = sorted(
        (v for v in views.values()
         if v["status"] == "OK" and v["holdtype"] not in PROTECTED_TYPES and v["opvarmningHalBeregnet"] in halls
         and v["opvarmningStartMin"] < window[1] and v["opvarmningSlutMin"] > window[0]),
        key=lambda v: abs((v["opvarmningStartMin"] + v["opvarmningSlutMin"]) / 2 - centre),
    )[:SOLVE_MAX_NEIGHBOURS]
    own = [] if u["holdtype"] in PROTECTED_TYPES else [u]
    attempts = sorted(
        ((d, n) for d in range(1, SOLVE_MAX_REDUCTION + 1) for n in range(len(neighbours) + 1)),
        key=lambda dn: (dn[0] * (len(own) + dn[1]), dn[0]),
    )
    for d, n in attempts:
        group = own + neighbours[:n]
        minutes = {v["id"]: max(SOLVE_MIN_MINUTES, _effective_minutes(v) - d) for v in group}
        if all(minutes[v["id"]] == _effective_minutes(v) for v in group):
            continue

        def change(trial, minutes=minutes):
            for rid, m in minutes.items():
                _find_row(trial, rid)["OpvarmningMinOverride"] = m
        trial = _fits(work, u["id"], ok_now, change)
        if trial:
            return trial
    return None


# Holdene kan kun ønske, om de går på før eller efter kl. 13. Et forslag om
# at flytte et hold i programmet må aldrig flytte et hold over den grænse.
NOON_SPLIT_MIN = 13 * 60
PROGRAM_MOVE_MAX_TEAMS = 5   # begræns beregningen, hvis rigtig mange hold mangler plads


def _after_one(minutes: Optional[int]) -> bool:
    return minutes is not None and minutes >= NOON_SPLIT_MIN


def _crowded_by(views: dict, u: dict, hal: Optional[str]) -> Optional[str]:
    """Det hold, der varmer op i hallen i det tidsrum, u skulle have brugt —
    det nærmeste, målt på hvornår de går på. None hvis der ikke er et."""
    if not hal:
        return None
    lo = u["opvisningMin"] - engine.MAX_START_BEFORE_MIN
    hi = u["opvisningMin"] - engine.GANG_MIN
    near = [v for v in views.values() if v["status"] == "OK" and v["opvarmningHalBeregnet"] == hal
            and v["opvarmningStartMin"] < hi and v["opvarmningSlutMin"] > lo]
    return min(near, key=lambda v: abs(v["opvisningMin"] - u["opvisningMin"]))["hold"] if near else None


def _program_move(plan: dict, views: dict, u: dict) -> Optional[dict]:
    """Det nærmeste sted i programmet (samme opvisningshal), hvor holdet får
    plads, uden at andre hold mister deres plads, og uden at noget hold
    skifter side af kl. 13. None hvis der ikke er et."""
    hal = u["opvisningHal"]
    order = [r["id"] for r in sorted(_rows_in(plan, hal), key=lambda r: r["Order"])]
    ok_now = _ok_ids(views)
    sides = {rid: _after_one(views[rid]["opvisningMin"]) for rid in order}
    rest = [rid for rid in order if rid != u["id"]]
    current = order.index(u["id"])
    # nærmeste pladser først; den første, der virker, er den mindste flytning
    for pos in sorted(range(len(order)), key=lambda pos: (abs(pos - current), pos)):
        new = rest[:pos] + [u["id"]] + rest[pos:]
        if new == order:
            continue
        if _after_one(views[u["id"]]["opvisningMin"]) != _after_one(
                views[order[pos if pos < current else pos]]["opvisningMin"]):
            continue   # holdet ville skifte side af kl. 13
        trial = copy.deepcopy(plan)
        reorder_rows(trial, hal, new)
        after = _views(trial)
        if after[u["id"]]["status"] != "OK" or not ok_now <= _ok_ids(after):
            continue
        if any(_after_one(after[rid]["opvisningMin"]) != sides[rid] for rid in order):
            continue
        break
    else:
        return None
    i = new.index(u["id"])
    return {"id": u["id"], "hold": u["hold"], "opvisningHal": hal,
            "fromTid": u["opvisningTid"], "toTid": after[u["id"]]["opvisningTid"],
            "after": views[new[i - 1]]["hold"] if i else None, "orderedIds": new}


def solve_warmups(plan: dict) -> dict:
    """Prøver at give hold uden plads en opvarmning. For hvert hold, efter
    opvisningstid: først en anden hal (koster ingen minutter), så at rykke et
    andet holds opvarmning tidligere, så kortere opvarmning til holdet og
    holdene omkring det. Ingen andre hold må miste
    deres plads, og der regnes forfra efter hver løsning.

    Hold, som brugeren selv har lagt i en hal eller på et tidspunkt, flyttes
    aldrig. Står et låst hold stadig uden plads, men er der plads i en anden
    hal, kommer det med som et tip, så brugeren selv kan vælge. Ellers kan
    der komme et forslag om at flytte holdet i programmet (programMoves).
    Ændrer ikke planen — returnerer forslaget."""
    work = copy.deepcopy(plan)
    original = _views(plan)
    raw_before = {r["id"]: r for r in plan["raw_rows"]}
    user_fixed = {r["id"] for r in plan["raw_rows"]
                  if engine.override_str(r.get("OpvarmningHalOverride")) or engine.override_str(r.get("OpvarmningStartOverride"))}
    # Hold med en tid, brugeren selv har sat, rykkes aldrig i tid. (Hold, der
    # kun er låst til en hal, må gerne rykkes — de bliver i hallen.)
    time_fixed = {r["id"] for r in plan["raw_rows"] if engine.override_str(r.get("OpvarmningStartOverride"))}
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
            trial = None
            # (efterskoler har kun én hal — dér er "en anden hal" ingen løsning)
            if u["id"] not in user_fixed and u["holdtype"] != "efterskole":
                trial = _try_other_halls(work, u, ok_now, _halls_for(plan, u))
            if trial is None:
                locked = engine.override_str(_find_row(work, u["id"]).get("OpvarmningHalOverride"))
                halls = [locked] if locked in plan["warmup_halls"] and u["holdtype"] != "efterskole" else _halls_for(plan, u)
                trial = _try_earlier_neighbour(work, u, views, ok_now, halls, time_fixed)
            if trial is None:
                for hal in halls:
                    trial = _try_repack(work, plan, u, views, ok_now, hal, time_fixed)
                    if trial:
                        break
            if trial is None:
                trial = _try_shorter(work, u, views, ok_now, halls)
            if trial is None:
                tried_without_luck.add(u["id"])
                continue
            work = trial
            progress = True
            break   # regn forfra efter hver løsning

    final = _views(work)
    changes, moves, earlier = [], [], []
    for row in work["raw_rows"]:
        rid, v = row["id"], final[row["id"]]
        where = {"id": rid, "hold": v["hold"], "opvisningHal": v["opvisningHal"], "opvisningTid": v["opvisningTid"]}
        before, after = _effective_minutes(original[rid]), _effective_minutes(v)
        if before != after:
            changes.append({**where, "from": before, "to": after})
        new_start = engine.override_str(row.get("OpvarmningStartOverride"))
        if new_start and new_start != engine.override_str(raw_before[rid].get("OpvarmningStartOverride")):
            # "changed": false = tiden er den samme, men holdet låses, så
            # kæden holder (vises ikke, men kommer med i Brug løsningen)
            earlier.append({**where, "hal": v["opvarmningHalBeregnet"], "start": new_start,
                            "fromStart": original[rid]["opvarmningStart"], "fromEnd": original[rid]["opvarmningSlut"],
                            "toStart": v["opvarmningStart"], "toEnd": v["opvarmningSlut"],
                            "changed": (original[rid]["opvarmningStart"], original[rid]["opvarmningHalBeregnet"])
                            != (v["opvarmningStart"], v["opvarmningHalBeregnet"])})
            continue
        new_hal = engine.override_str(row.get("OpvarmningHalOverride"))
        if new_hal and new_hal != engine.override_str(raw_before[rid].get("OpvarmningHalOverride")):
            moves.append({**where, "toHal": new_hal})

    was_unplaced = [v for v in original.values() if v["needsWarmup"] and v["status"] == "KAN IKKE PLANLÆGGES"]
    remaining = [v for v in was_unplaced if final[v["id"]]["status"] != "OK"]
    hints = []
    ok_final = _ok_ids(final)
    for v in remaining:
        locked = engine.override_str(raw_before[v["id"]].get("OpvarmningHalOverride"))
        if not locked or engine.override_str(raw_before[v["id"]].get("OpvarmningStartOverride")):
            continue
        for hal in _halls_for(plan, v):
            if hal != locked and _fits(work, v["id"], ok_final, _lock_to(v["id"], hal)):
                hints.append({"id": v["id"], "hold": v["hold"], "lockedHal": locked, "freeHal": hal})
                break
    # Hold, der stadig ikke kan få plads: ligger de for tæt på et andet hold i
    # programmet, foreslås et andet tidspunkt (beregnet på planen, som den er).
    program_moves, crowded = [], []
    hinted = {h["id"] for h in hints}
    for v in remaining:
        if v["id"] in hinted or len(program_moves) >= PROGRAM_MOVE_MAX_TEAMS or v["opvisningMin"] is None:
            continue
        move = _program_move(plan, original, original[v["id"]])
        hal = engine.override_str(raw_before[v["id"]].get("OpvarmningHalOverride"))
        if v["holdtype"] == "efterskole":
            hal = _efterskole_hall(plan)
        if not move:
            by = _crowded_by(original, original[v["id"]], hal)
            if by:   # ingen plads at flytte til — sig i det mindste hvorfor
                crowded.append({"id": v["id"], "hold": v["hold"], "crowdedBy": by, "warmupHal": hal,
                                "opvisningTid": v["opvisningTid"], "opvisningHal": v["opvisningHal"]})
        if move:
            move["warmupHal"] = hal
            move["crowdedBy"] = _crowded_by(original, original[v["id"]], hal)
            program_moves.append(move)
    order = lambda c: (c["opvisningHal"], c["opvisningTid"])
    return {
        "changes": sorted(changes, key=order),
        "moves": sorted(moves, key=order),
        "earlier": sorted(earlier, key=order),
        "placed": [v["hold"] for v in was_unplaced if final[v["id"]]["status"] == "OK"],
        "remaining": [v["hold"] for v in remaining],
        "hints": hints,
        "programMoves": program_moves,
        "crowded": crowded,
    }


def apply_solution(plan: dict, changes: List[dict]) -> None:
    """Bruger løsningen fra "Find løsning": {"id", "minutes"} giver holdet en
    ny opvarmningstid, {"id", "hal"} lægger det i en opvarmningshal. Alt
    tjekkes, før noget ændres."""
    todo = []
    for c in changes:
        row = _find_row(plan, c.get("id"))
        if row is None:
            raise ActionError("Et af holdene findes ikke længere — find løsningen igen", 404)
        if "minutes" in c:
            try:
                minutes = int(c.get("minutes"))
            except (TypeError, ValueError):
                raise ActionError("Ugyldig opvarmningstid")
            if minutes < 1:
                raise ActionError("Opvarmningstiden skal være mindst 1 min")
            todo.append((row, "OpvarmningMinOverride", minutes))
        if "hal" in c:
            if c["hal"] not in plan["warmup_halls"]:
                raise ActionError("Opvarmningshallen findes ikke længere — find løsningen igen")
            todo.append((row, "OpvarmningHalOverride", c["hal"]))
        if "start" in c:
            start = normalize_hhmm(c["start"])
            if start is None:
                raise ActionError("Ugyldigt tidspunkt i løsningen — find løsningen igen")
            todo.append((row, "OpvarmningStartOverride", start))
    for row, key, value in todo:
        row[key] = value


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


def _check_new_hall_name(old: str, new: str, taken) -> None:
    if new != old and new in taken:
        raise ActionError(f"Der findes allerede en hal, der hedder '{new}'")


def rename_warmup_hall(plan: dict, old_name: str, new_name: str) -> None:
    old, new = (old_name or "").strip(), (new_name or "").strip()
    _check_new_hall_name(old, new, plan["warmup_halls"])
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
    _check_new_hall_name(old, new, show_hal_names(plan))
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
        hal["startTimeSet"] = True   # en senere fil må ikke overskrive den


def delete_show_hall(plan: dict, name: str) -> None:
    name = (name or "").strip()
    plan["show_halls"] = [h for h in plan["show_halls"] if h["name"] != name]
    plan["raw_rows"] = [r for r in plan["raw_rows"] if r["OpvisningHal"] != name]
