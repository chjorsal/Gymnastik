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
