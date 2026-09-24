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
