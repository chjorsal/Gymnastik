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

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return not FAIL


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
