"""
Opvarmningsplanlægger — lokal webserver (generation 2.1).

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
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import engine

BASE_DIR = Path(__file__).parent
# STATE_FILE kan peges et andet sted hen (fx en kopi når test_api.py køres),
# så testene aldrig rører den rigtige state.json.
STATE_FILE = Path(os.environ.get("STATE_FILE", BASE_DIR / "state.json"))

DEFAULT_STATE = {
    "warmup_halls": ["Hal 3 A", "Hal 3 B", "Hal 4"],
    "priority_hall": "Hal 4",
    "show_halls": [],   # [{"name": str, "startTime": "HH:MM"}]
    "raw_rows": [],
}


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for key, default in DEFAULT_STATE.items():
                data.setdefault(key, default)
            # migrering: ældre state havde show_halls som en liste af strenge
            data["show_halls"] = [
                {"name": h, "startTime": "09:00"} if isinstance(h, str) else h
                for h in data["show_halls"]
            ]
            # engangsrettelse: en tidligere bug gav tomme "andet"-rækker den
            # synlige label "Andet" ved import, hvilket fik dem til fejlagtigt
            # at blive genklassificeret som "hold" ved næste genstart. Ret
            # dem tilbage før den normale genklassificering nedenfor kører.
            for row in data["raw_rows"]:
                if row.get("Type") == "hold" and row.get("Hold") == "Andet":
                    row["Type"] = "andet"
                    row["Hold"] = ""

            # migrering: rækker der er mærket "hold" eller det generiske
            # "andet" ud fra en ældre nøgleordsliste (fx "Dørene åbner")
            # genklassificeres, så kun rigtige hold fra Excel-importen
            # tæller som hold. Manuelt oprettede pause/fane-punkter og
            # punkter brugeren selv har omdøbt (HoldEdited) røres ikke.
            for row in data["raw_rows"]:
                if row.get("Type") in ("hold", "andet") and not row.get("HoldEdited"):
                    reclassified = engine.classify_type(row.get("Hold", ""))
                    if reclassified != row.get("Type"):
                        row["Type"] = reclassified
                row.pop("NeedsWarmup", None)
            return data
        except Exception as e:
            # Overskriv ALDRIG en fil vi ikke kunne læse — flyt den til side,
            # så data kan reddes, før der startes forfra med tom state.
            broken = STATE_FILE.with_name(f"{STATE_FILE.stem}.broken-{time.strftime('%Y%m%d-%H%M%S')}.json")
            os.replace(STATE_FILE, broken)
            print(f"ADVARSEL: kunne ikke læse {STATE_FILE.name} ({e}). Flyttet til {broken.name}.")
    return json.loads(json.dumps(DEFAULT_STATE))


STATE = load_state()


def save_state():
    # Skriv til en midlertidig fil og byt den ind atomisk, så et nedbrud
    # midt i skrivningen aldrig efterlader en halv state.json.
    tmp = STATE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(STATE, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)


def find_show_hal(name: str) -> Optional[dict]:
    return next((h for h in STATE["show_halls"] if h["name"] == name), None)


def show_hal_names() -> List[str]:
    return [h["name"] for h in STATE["show_halls"]]


def next_order(hal_name: str) -> int:
    orders = [r["Order"] for r in STATE["raw_rows"] if r["OpvisningHal"] == hal_name]
    return (max(orders) + 1) if orders else 0


def recompute_df():
    df = engine.build_dataframe(STATE["raw_rows"], STATE["show_halls"])
    return engine.compute_plan(df, STATE["warmup_halls"], STATE["priority_hall"])


def full_state_payload() -> dict:
    df = recompute_df()
    return {
        "warmupHalls": STATE["warmup_halls"],
        "priorityHall": STATE["priority_hall"],
        "showHalls": STATE["show_halls"],
        "rows": engine.to_row_dicts(df, STATE["warmup_halls"]),
        "schedule": engine.to_schedule(df),
    }


def _commit() -> dict:
    """Gemmer state til disk og returnerer den friske, genberegnede payload —
    den sidste linje i praktisk talt hvert endpoint der ændrer noget."""
    save_state()
    return full_state_payload()


app = FastAPI(title="Opvarmningsplanlægger")

# Synkrone endpoints kører parallelt i en threadpool og muterer alle den
# samme globale STATE — kør API-kald ét ad gangen, så to samtidige ændringer
# ikke overskriver hinanden.
_api_lock = asyncio.Lock()


@app.middleware("http")
async def serialize_api_calls(request: Request, call_next):
    if not request.url.path.startswith("/api/"):
        return await call_next(request)
    async with _api_lock:
        return await call_next(request)


# ======================================================
# STATE / RÆKKER
# ======================================================

@app.get("/api/state")
def get_state():
    return full_state_payload()


@app.post("/api/upload")
async def upload(files: List[UploadFile] = File(...), show_hal: Optional[str] = Form(None)):
    existing_names = {h["name"] for h in STATE["show_halls"]}
    pending_new_names = set()
    planned = []  # (hal_name, is_new_hal, suggested_start, rows) — intet er skrevet til STATE endnu

    for file in files:
        content = await file.read()
        explicit_name = (show_hal or "").strip()
        if explicit_name:
            # Brugeren har eksplicit peget på en hal — tilføj til den, selv
            # hvis den allerede findes og har hold i sig.
            hal_name = explicit_name
        else:
            # Automatisk navngivning må aldrig stille flette ind i en
            # allerede eksisterende hal (fx to forskellige dages "Arena") —
            # gør navnet unikt hvis det kolliderer, også inden for samme upload.
            base_name = engine.clean_hal_name(Path(file.filename).stem)
            hal_name = base_name
            suffix = 2
            while hal_name in existing_names or hal_name in pending_new_names:
                hal_name = f"{base_name} ({suffix})"
                suffix += 1

        is_new_hal = hal_name not in existing_names and hal_name not in pending_new_names
        if is_new_hal:
            pending_new_names.add(hal_name)

        try:
            rows, suggested_start = engine.load_excel_bytes(file.filename, content, hal_name, 0)
        except Exception as e:
            # Valider ALT før noget som helst skrives til state, så en
            # ugyldig/korrupt fil midt i en batch ikke efterlader delvist
            # importerede data.
            return JSONResponse(
                {"error": f"Kunne ikke læse '{file.filename}' — er det en gyldig Excel-fil (.xlsx)? ({e})"},
                status_code=400,
            )

        planned.append((hal_name, is_new_hal, suggested_start, rows))

    for hal_name, is_new_hal, suggested_start, rows in planned:
        if is_new_hal and find_show_hal(hal_name) is None:
            STATE["show_halls"].append({
                "name": hal_name,
                "startTime": suggested_start or "09:00",
            })
        start_order = next_order(hal_name)
        for i, row in enumerate(rows):
            row["Order"] = start_order + i
        STATE["raw_rows"].extend(rows)

    return _commit()


class RowPatch(BaseModel):
    field: str
    value: Optional[object] = None


EDITABLE_FIELD_MAP = {
    "hold": "Hold",
    "varighed": "Varighed",
    "opvarmningMin": "OpvarmningMinOverride",
    "opvisningHal": "OpvisningHal",
    "opvarmningHal": "OpvarmningHalOverride",
    "opvarmningStart": "OpvarmningStartOverride",
}


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


@app.patch("/api/rows/{row_id}")
def patch_row(row_id: str, patch: RowPatch):
    if patch.field not in EDITABLE_FIELD_MAP:
        return JSONResponse({"error": f"Ukendt felt: {patch.field}"}, status_code=400)

    key = EDITABLE_FIELD_MAP[patch.field]
    row = next((r for r in STATE["raw_rows"] if r["id"] == row_id), None)
    if row is None:
        return JSONResponse({"error": "Punkt ikke fundet"}, status_code=404)

    value = patch.value
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
            return JSONResponse({"error": "Holdnavn fra Excel-importen kan ikke ændres"}, status_code=400)
        value = str(value or "").strip()
        row["HoldEdited"] = True
    if key == "OpvisningHal":
        name = str(value or "").strip()
        if name and find_show_hal(name) is None:
            STATE["show_halls"].append({"name": name, "startTime": "09:00"})
        if name and name != row["OpvisningHal"]:
            row["Order"] = next_order(name)
        value = name
    if key == "OpvarmningHalOverride":
        name = str(value or "").strip()
        value = name if name in STATE["warmup_halls"] else None
    if key == "OpvarmningStartOverride":
        value = normalize_hhmm(value)

    row[key] = value
    return _commit()


@app.delete("/api/rows/{row_id}")
def delete_row(row_id: str):
    STATE["raw_rows"] = [r for r in STATE["raw_rows"] if r["id"] != row_id]
    return _commit()


class SpecialRowCreate(BaseModel):
    hal: str
    type: str


@app.post("/api/rows/special")
def create_special_row(payload: SpecialRowCreate):
    if payload.type not in ("pause", "faneindmarch", "faneudmarch", "dorene_aabner"):
        return JSONResponse({"error": "Ukendt type"}, status_code=400)
    if find_show_hal(payload.hal) is None:
        return JSONResponse({"error": "Opvisningshal ikke fundet"}, status_code=404)

    row = engine.new_special_row(payload.hal, payload.type, next_order(payload.hal))
    STATE["raw_rows"].append(row)
    return _commit()


class ReorderPayload(BaseModel):
    hal: str
    orderedIds: List[str]


@app.post("/api/rows/reorder")
def reorder_rows(payload: ReorderPayload):
    by_id = {r["id"]: r for r in STATE["raw_rows"] if r["OpvisningHal"] == payload.hal}
    for i, rid in enumerate(payload.orderedIds):
        if rid in by_id:
            by_id[rid]["Order"] = i
    return _commit()


class SwapWarmupTimePayload(BaseModel):
    draggedId: str
    targetId: str


@app.post("/api/rows/swap-warmup-time")
def swap_warmup_time(payload: SwapWarmupTimePayload):
    """Træk-og-slip inde i en opvarmningshal: det trukne hold overtager
    målholdets (tidligere) opvarmningstidspunkt, og målholdet får det
    trukne holds (senere) tidspunkt i stedet. Kun tilladt når holdet der
    trækkes rent faktisk rykker TIDLIGERE — ikke omvendt."""
    dragged = next((r for r in STATE["raw_rows"] if r["id"] == payload.draggedId), None)
    target = next((r for r in STATE["raw_rows"] if r["id"] == payload.targetId), None)
    if dragged is None or target is None:
        return JSONResponse({"error": "Hold ikke fundet"}, status_code=404)

    df = recompute_df()
    rows_now = {r["id"]: r for r in engine.to_row_dicts(df, STATE["warmup_halls"])}
    dragged_now = rows_now.get(payload.draggedId)
    target_now = rows_now.get(payload.targetId)
    if not dragged_now or not target_now or not dragged_now["opvarmningStart"] or not target_now["opvarmningStart"]:
        return JSONResponse(
            {"error": "Begge hold skal have en beregnet opvarmningstid lige nu"}, status_code=400
        )

    if target_now["opvarmningStart"] >= dragged_now["opvarmningStart"]:
        return JSONResponse(
            {"error": "Kan kun trække et hold til et tidligere tidspunkt"}, status_code=400
        )

    before = [(r, r["OpvarmningStartOverride"], r["OpvarmningHalOverride"]) for r in (dragged, target)]
    dragged["OpvarmningStartOverride"] = target_now["opvarmningStart"]
    target["OpvarmningStartOverride"] = dragged_now["opvarmningStart"]
    # Lås også hallen, så holdene bytter plads i DENNE hal og ikke havner i
    # den første ledige hal på listen.
    dragged["OpvarmningHalOverride"] = target_now["opvarmningHalBeregnet"]
    target["OpvarmningHalOverride"] = dragged_now["opvarmningHalBeregnet"]

    # Målholdet får det trukne holds SENERE tidspunkt — fortryd byttet hvis
    # et af holdene så ikke længere kan nå sin opvisning.
    after = {r["id"]: r for r in engine.to_row_dicts(recompute_df(), STATE["warmup_halls"])}
    if after[dragged["id"]]["status"] != "OK" or after[target["id"]]["status"] != "OK":
        for r, start, hal in before:
            r["OpvarmningStartOverride"], r["OpvarmningHalOverride"] = start, hal
        return JSONResponse(
            {"error": f"Byttet giver ikke tid nok: '{target['Hold']}' kan ikke nå sin opvisning med det senere tidspunkt"},
            status_code=400,
        )
    return _commit()


@app.post("/api/reset")
def reset_rows():
    STATE["raw_rows"] = []
    return _commit()


# ======================================================
# HAL-STYRING (opvarmnings- og opvisningshaller)
# ======================================================

class HallCreate(BaseModel):
    name: str


class HallRename(BaseModel):
    oldName: str
    newName: str


class HallDelete(BaseModel):
    name: str


class ShowHallStartTime(BaseModel):
    name: str
    startTime: str


@app.post("/api/halls/warmup")
def create_warmup_hall(payload: HallCreate):
    name = payload.name.strip()
    if name and name not in STATE["warmup_halls"]:
        STATE["warmup_halls"].append(name)
        if STATE["priority_hall"] is None:
            STATE["priority_hall"] = name
    return _commit()


@app.patch("/api/halls/warmup")
def rename_warmup_hall(payload: HallRename):
    old, new = payload.oldName.strip(), payload.newName.strip()
    if old in STATE["warmup_halls"] and new:
        STATE["warmup_halls"] = [new if h == old else h for h in STATE["warmup_halls"]]
        if STATE["priority_hall"] == old:
            STATE["priority_hall"] = new
        for r in STATE["raw_rows"]:
            if r.get("OpvarmningHalOverride") == old:
                r["OpvarmningHalOverride"] = new
    return _commit()


@app.delete("/api/halls/warmup")
def delete_warmup_hall(payload: HallDelete):
    name = payload.name.strip()
    STATE["warmup_halls"] = [h for h in STATE["warmup_halls"] if h != name]
    if STATE["priority_hall"] == name:
        STATE["priority_hall"] = STATE["warmup_halls"][0] if STATE["warmup_halls"] else None
    return _commit()


@app.post("/api/halls/warmup/priority")
def set_priority_hall(payload: HallCreate):
    name = payload.name.strip()
    if name in STATE["warmup_halls"]:
        STATE["priority_hall"] = name
    return _commit()


@app.post("/api/halls/show")
def create_show_hall(payload: HallCreate):
    name = payload.name.strip()
    if name and find_show_hal(name) is None:
        STATE["show_halls"].append({"name": name, "startTime": "09:00"})
    return _commit()


@app.patch("/api/halls/show")
def rename_show_hall(payload: HallRename):
    old, new = payload.oldName.strip(), payload.newName.strip()
    hal = find_show_hal(old)
    if hal and new:
        hal["name"] = new
        for r in STATE["raw_rows"]:
            if r["OpvisningHal"] == old:
                r["OpvisningHal"] = new
    return _commit()


@app.post("/api/halls/show/starttime")
def set_show_hall_start_time(payload: ShowHallStartTime):
    start = normalize_hhmm(payload.startTime)
    if start is None:
        return JSONResponse(
            {"error": f"'{payload.startTime}' er ikke et gyldigt klokkeslæt — skriv fx 09:30"},
            status_code=400,
        )
    hal = find_show_hal(payload.name.strip())
    if hal:
        hal["startTime"] = start
    return _commit()


@app.delete("/api/halls/show")
def delete_show_hall(payload: HallDelete):
    name = payload.name.strip()
    STATE["show_halls"] = [h for h in STATE["show_halls"] if h["name"] != name]
    STATE["raw_rows"] = [r for r in STATE["raw_rows"] if r["OpvisningHal"] != name]
    return _commit()


# ======================================================
# EKSPORT
# ======================================================

@app.get("/api/export.xlsx")
def export_xlsx():
    df = recompute_df()
    buf = engine.build_workbook(df)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="opvisning_med_opvarmning.xlsx"'},
    )


# ======================================================
# STATISKE FILER (frontend)
# ======================================================

app.mount("/", StaticFiles(directory=str(BASE_DIR / "static"), html=True), name="static")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8877"))
    print(f"Opvarmningsplanlægger kører på http://localhost:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port)
