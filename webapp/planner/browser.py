"""
Bro mellem JavaScript (Pyodide i browseren) og planner.actions.

Alt ind og ud er JSON-tekst, så JS aldrig skal håndtere Python-objekter.
Planen ejes af JS (gemmes i localStorage); hvert kald får den nuværende plan
med og returnerer den nye.
"""

import functools
import json
import traceback
from pathlib import Path

from . import actions

# De handlinger call() må køre. Navnene og argumenterne svarer til
# funktionerne i planner.actions.
ACTIONS = {
    "patch_row", "delete_row", "add_special_row", "add_team", "place_warmup", "move_rows", "delete_rows", "apply_solution", "reorder_rows", "swap_warmup_time",
    "reset_rows", "create_warmup_hall", "rename_warmup_hall", "delete_warmup_hall",
    "set_priority_hall", "create_show_hall", "rename_show_hall",
    "set_show_hall_start_time", "delete_show_hall",
    "set_efterskole_day", "remove_efterskole_list", "assign_efterskole", "unassign_efterskole",
}


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _plan(plan_json: str) -> dict:
    return actions.import_plan(plan_json) if plan_json else actions.start_plan()


def _result(plan: dict) -> str:
    return _dump({"ok": True, "plan": plan, "payload": actions.payload(plan)})


def _error(e: actions.ActionError) -> str:
    return _dump({"ok": False, "error": e.message, "status": e.status})


UNEXPECTED = "Det lykkedes ikke — planlæggeren fik nogle oplysninger, den ikke forstod. Planen er ikke ændret."


def _safe(fn):
    """En pæn dansk fejl (ok=false) i stedet for et Python-nedbrud i
    browseren. Planen ændres ikke: JS beholder sin plan, når svaret er en fejl.
    Detaljerne skrives i browserens konsol."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except actions.ActionError as e:
            return _error(e)
        except Exception:
            traceback.print_exc()
            return _dump({"ok": False, "error": UNEXPECTED, "status": 500})
    return wrapper


def load(plan_json: str) -> str:
    """En ulæselig gemt plan giver ok=false, så JS kan lægge den til side."""
    try:
        return _dump({"ok": True, "plan": _plan(plan_json)})
    except Exception:
        return _dump({"ok": False})


@_safe
def call(plan_json: str, name: str, args_json: str) -> str:
    plan = _plan(plan_json)
    if name == "payload":
        return _result(plan)
    if name not in ACTIONS:
        raise actions.ActionError(f"Ukendt handling: {name}")
    getattr(actions, name)(plan, **json.loads(args_json or "{}"))
    return _result(plan)


@_safe
def upload_files(plan_json: str, paths_json: str, show_hal: str) -> str:
    plan = _plan(plan_json)
    files = [(Path(p).name, Path(p).read_bytes()) for p in json.loads(paths_json)]
    actions.upload(plan, files, show_hal or None)
    return _result(plan)


@_safe
def upload_efterskoler(plan_json: str, path: str) -> str:
    plan = _plan(plan_json)
    actions.import_efterskoler(plan, Path(path).name, Path(path).read_bytes())
    return _result(plan)


@_safe
def upload_files_to_halls(plan_json: str, items_json: str) -> str:
    """items: [[sti, hal], ...] — filerne lægges i hver deres hal på én gang."""
    plan = _plan(plan_json)
    groups = {}
    for path, hal in json.loads(items_json):
        groups.setdefault(hal, []).append((Path(path).name, Path(path).read_bytes()))
    actions.upload_to_halls(plan, list(groups.items()))
    return _result(plan)


@_safe
def export_to(plan_json: str, out_path: str, name: str = "") -> str:
    """Skriver Excel-planen til out_path og returnerer det filnavn, den skal
    hentes som (brugerens navn gjort sikkert)."""
    Path(out_path).write_bytes(actions.export_xlsx(_plan(plan_json)))
    return _dump({"ok": True, "filename": actions.export_filename(name)})


@_safe
def import_plan(text: str) -> str:
    return _dump({"ok": True, "plan": actions.import_plan(text)})


@_safe
def solve(plan_json: str) -> str:
    """Find løsning — ændrer intet, returnerer forslaget."""
    return _dump({"ok": True, "solution": actions.solve_warmups(_plan(plan_json))})
