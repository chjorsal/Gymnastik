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

from testkit import check, excel_bytes, summary


def raises(fn, status=None):
    """Kører fn og returnerer ActionError, hvis den kastes (ellers None)."""
    try:
        fn()
    except ActionError as e:
        if status is None or e.status == status:
            return e
        return None
    return None


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
    check("upload without any hall creates 'Hal 1' (not a name from the file)",
          plan2["show_halls"] == [{"name": "Hal 1", "startTime": "09:00"}], plan2["show_halls"])
    plan3 = plan_with_halls()
    actions.upload(plan3, [("Hal2.xlsx", excel_bytes([("A", 10)]))])
    check("upload without a chosen hall uses the first show hall",
          plan3["raw_rows"][0]["OpvisningHal"] == "Sal A" and len(plan3["show_halls"]) == 2)

    # ---------- standardhallen Hal 1 og træk af filer ind på en hal ----------
    sp = actions.start_plan()
    check("start_plan has one show hall 'Hal 1' at 09:00 and nothing else",
          sp == {"warmup_halls": [], "priority_hall": None,
                 "show_halls": [{"name": "Hal 1", "startTime": "09:00"}], "raw_rows": []}, sp)
    check("start_plan returns a fresh copy", actions.start_plan()["show_halls"] is not sp["show_halls"])
    check("new_plan stays empty (used for migration and tests)", actions.new_plan()["show_halls"] == [])

    actions.upload(sp, [("Arena.xlsx", excel_bytes([("A", 10)], start="10:30"))], show_hal="Hal 1")
    check("file dropped on the empty default hall lands there, not in a hall named after the file",
          [h["name"] for h in sp["show_halls"]] == ["Hal 1"] and sp["raw_rows"][0]["OpvisningHal"] == "Hal 1")
    check("empty hall without a typed start time takes the file's first Tid",
          sp["show_halls"][0]["startTime"] == "10:30", sp["show_halls"])
    actions.upload(sp, [("Mere.xlsx", excel_bytes([("B", 10)], start="13:00"))], show_hal="Hal 1")
    check("a second file in a hall with teams keeps the hall's start time and goes last",
          sp["show_halls"][0]["startTime"] == "10:30" and [r["Order"] for r in sp["raw_rows"]] == [0, 1])

    sp = actions.start_plan()
    actions.set_show_hall_start_time(sp, "Hal 1", "8.15")
    actions.upload(sp, [("x.xlsx", excel_bytes([("A", 10)], start="10:30"))], show_hal="Hal 1")
    check("a start time the user typed is never overwritten by the file",
          sp["show_halls"][0]["startTime"] == "08:15", sp["show_halls"])

    sp = actions.start_plan()
    actions.create_show_hall(sp, "Hal 2")
    actions.upload(sp, [("a.xlsx", excel_bytes([("A1", 10), ("A2", 10)])),
                        ("b.xlsx", excel_bytes([("B1", 10)]))], show_hal="Hal 2")
    check("several files dropped on one hall all go into that hall, in file order",
          [(r["Hold"], r["OpvisningHal"], r["Order"]) for r in sp["raw_rows"]]
          == [("A1", "Hal 2", 0), ("A2", "Hal 2", 1), ("B1", "Hal 2", 2)], sp["raw_rows"])
    check("Hal 1 stays empty when files go to Hal 2", not [r for r in sp["raw_rows"] if r["OpvisningHal"] == "Hal 1"])

    empty = actions.new_plan()
    actions.upload(empty, [("Arena_færdig.xlsx", excel_bytes([("A", 10)], start="11:00"))], show_hal="Hal 1")
    check("upload button with no halls creates 'Hal 1' with the file's start time",
          empty["show_halls"] == [{"name": "Hal 1", "startTime": "11:00"}], empty["show_halls"])

    # ---------- Lav opvarmningsplan: filer til flere haller på én gang ----------
    mp = actions.start_plan()
    actions.create_show_hall(mp, "Hal 2")
    actions.upload_to_halls(mp, [
        ("Hal 1", [("arena.xlsx", excel_bytes(["A1", "A2"], start="08:30"))]),
        ("Hal 2", [("hal2a.xlsx", excel_bytes(["B1"], start="10:00")), ("hal2b.xlsx", excel_bytes(["B2"]))]),
    ])
    check("upload_to_halls puts each file in its own hall, in order",
          [(r["Hold"], r["OpvisningHal"], r["Order"]) for r in mp["raw_rows"]]
          == [("A1", "Hal 1", 0), ("A2", "Hal 1", 1), ("B1", "Hal 2", 0), ("B2", "Hal 2", 1)], mp["raw_rows"])
    check("upload_to_halls gives each empty hall its own file's start time",
          [h["startTime"] for h in mp["show_halls"]] == ["08:30", "10:00"], mp["show_halls"])

    mp = actions.start_plan()
    actions.create_show_hall(mp, "Hal 2")
    before = copy.deepcopy(mp)
    err = raises(lambda: actions.upload_to_halls(mp, [
        ("Hal 1", [("god.xlsx", excel_bytes(["A1"]))]),
        ("Hal 2", [("skrald.xlsx", b"ikke excel")]),
    ]), 400)
    check("one bad file -> nothing is loaded in any hall",
          err is not None and "skrald.xlsx" in err.message and mp == before, err and err.message)
    check("upload_to_halls with no files -> 400",
          raises(lambda: actions.upload_to_halls(mp, [("Hal 1", [])]), 400) is not None and mp == before)
    check("upload_to_halls with a blank hall -> 400",
          raises(lambda: actions.upload_to_halls(mp, [("  ", [("a.xlsx", excel_bytes(["A"]))])]), 400) is not None
          and mp == before)
    actions.upload_to_halls(mp, [("Ny hal", [("n.xlsx", excel_bytes(["N"]))])])
    check("upload_to_halls creates a hall that does not exist yet",
          [h["name"] for h in mp["show_halls"]] == ["Hal 1", "Hal 2", "Ny hal"])

    # ---------- et hold låst til en hal går forud for hold, der kan flytte ----------
    # Som "Larving": A kan varme op hvor som helst og går på lidt før L. L er
    # låst til V1 (holdet kan ikke være i V2). Før tog A pladsen i V1, så L
    # stod uden plads, selv om A lige så godt kunne være i V2.
    lk = actions.new_plan()
    for hal in ("V1", "V2"):
        actions.create_warmup_hall(lk, hal)
    for sal, team, start in (("S1", "A", "10:00"), ("S2", "L", "10:10")):
        actions.create_show_hall(lk, sal)
        actions.set_show_hall_start_time(lk, sal, start)
        actions.upload(lk, [("d.xlsx", excel_bytes([team]))], show_hal=sal)
    ids = {r["Hold"]: r["id"] for r in lk["raw_rows"]}
    for team in ("A", "L"):
        actions.patch_row(lk, ids[team], "opvarmningMin", 30)
    actions.patch_row(lk, ids["L"], "opvarmningHal", "V1")
    views = {r["hold"]: r for r in actions.payload(lk)["rows"]}
    check("a team locked to a hall gets room there; the free team moves to the other hall",
          (views["L"]["status"], views["L"]["opvarmningHalBeregnet"]) == ("OK", "V1")
          and (views["A"]["status"], views["A"]["opvarmningHalBeregnet"]) == ("OK", "V2"),
          {k: (v["status"], v["opvarmningHalBeregnet"], v["opvarmningStart"]) for k, v in views.items()})
    actions.patch_row(lk, ids["L"], "opvarmningHal", "")
    views = {r["hold"]: r for r in actions.payload(lk)["rows"]}
    check("without the lock both teams still get room", all(v["status"] == "OK" for v in views.values()))

    # ---------- opvarmningen starter højst 45 min før holdet går på ----------
    # Efterskolen E (går på 09:30) placeres først og tager V1 08:55–09:25. X
    # går på 09:20 med 30 min opvarmning; uden grænsen ville X få 08:25–08:55,
    # dvs. starte 55 min før.
    st = actions.new_plan()
    actions.create_warmup_hall(st, "V1")
    for sal, team, start in (("S1", "Testby Efterskole", "09:30"), ("S2", "X", "09:20")):
        actions.create_show_hall(st, sal)
        actions.set_show_hall_start_time(st, sal, start)
        actions.upload(st, [("d.xlsx", excel_bytes([team]))], show_hal=sal)
    for r in st["raw_rows"]:
        r["OpvarmningMinOverride"] = 30
    rows = {r["hold"]: r for r in actions.payload(st)["rows"]}
    check("no warm-up starts more than 45 min before the team is on the floor",
          rows["X"]["status"] != "OK" or rows["X"]["opvisningMin"] - rows["X"]["opvarmningStartMin"] <= 45,
          (rows["X"]["status"], rows["X"]["opvarmningStart"]))
    check("the efterskole keeps its slot", rows["Testby Efterskole"]["status"] == "OK")
    actions.create_warmup_hall(st, "V2")
    a = next(r for r in st["raw_rows"] if r["Hold"] == "X")       # X går på 09:20
    err = raises(lambda: actions.place_warmup(st, a["id"], "V2", "08:30"), 400)
    check("a fixed time more than 45 min before the show is refused", err is not None and "45 min" in err.message,
          err and err.message)
    check("warm-up minutes above 40 are refused (45 min minus 5 min walk)",
          raises(lambda: actions.patch_row(st, a["id"], "opvarmningMin", 41), 400) is not None
          and a["OpvarmningMinOverride"] == 30)
    actions.patch_row(st, a["id"], "opvarmningMin", 40)
    check("40 min warm-up is allowed", a["OpvarmningMinOverride"] == 40)

    # ---------- omdøb haller: navne skal være unikke ----------
    rp = plan_with_halls()
    actions.upload(rp, [("d.xlsx", excel_bytes([("A", 10)]))], show_hal="Sal A")
    before = copy.deepcopy(rp)
    err = raises(lambda: actions.rename_show_hall(rp, "Sal A", " Sal B "), 400)
    check("renaming a show hall to an existing name -> 400, nothing merged",
          err is not None and "Sal B" in err.message and rp == before, err and err.message)
    err = raises(lambda: actions.rename_warmup_hall(rp, "Varm 1", "Varm 2"), 400)
    check("renaming a warm-up hall to an existing name -> 400, unchanged",
          err is not None and rp == before, err and err.message)
    actions.rename_show_hall(rp, "Sal A", "Sal A")
    actions.rename_warmup_hall(rp, "Varm 1", "Varm 1")
    check("renaming a hall to its own name is allowed and changes nothing", rp == before)
    actions.rename_show_hall(rp, "Sal A", "Arena")
    check("renaming a show hall moves its teams along",
          [h["name"] for h in rp["show_halls"]] == ["Arena", "Sal B"] and rp["raw_rows"][0]["OpvisningHal"] == "Arena")

    # ---------- filnavn til Excel-eksporten ----------
    cases = {
        "Opvarmningsplan Lørdag": "Opvarmningsplan Lørdag.xlsx",
        "  plan  med   luft  ": "plan med luft.xlsx",
        "Arena/Hal2: lørdag?": "Arena Hal2 lørdag.xlsx",
        'a<b>c"d|e*f\\g': "a b c d e f g.xlsx",
        "tab\tog\nlinje": "tab og linje.xlsx",
        "Plan.XLSX": "Plan.xlsx",
        "Plan.xlsx.xlsx": "Plan.xlsx.xlsx",
        "punktum til sidst...": "punktum til sidst.xlsx",
        "": "opvisning_med_opvarmning.xlsx",
        None: "opvisning_med_opvarmning.xlsx",
        "   ": "opvisning_med_opvarmning.xlsx",
        "///": "opvisning_med_opvarmning.xlsx",
        "CON": "CON_.xlsx",
        "lpt1.plan": "lpt1_.plan.xlsx",
        "console": "console.xlsx",
    }
    got = {k: actions.export_filename(k) for k in cases}
    check("export_filename cleans names (illegal chars, spaces, .xlsx, empty, reserved)", got == cases,
          {k: v for k, v in got.items() if v != cases[k]})
    long_name = actions.export_filename("x" * 300)
    check("export_filename caps the name at 100 characters + .xlsx", long_name == "x" * 100 + ".xlsx", len(long_name))

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

    # ---------- tilføj hold manuelt (tilmelding på bagkant) ----------
    plan_t = plan_with_halls()
    actions.upload(plan_t, [("d.xlsx", excel_bytes([("Hold 1", 10)]))], show_hal="Sal A")
    check("add_team without a name -> 400", raises(lambda: actions.add_team(plan_t, "Sal A", "  "), 400) is not None)
    check("add_team in unknown hall -> 404", raises(lambda: actions.add_team(plan_t, "Ingen", "Nyt"), 404) is not None)
    actions.add_team(plan_t, "Sal A", "  Sent hold ")
    new = plan_t["raw_rows"][-1]
    check("add_team puts a 15/15 team last in the hall",
          (new["Hold"], new["Type"], new["Varighed"], new["OpvarmningMinOverride"], new["Order"])
          == ("Sent hold", "hold", 15, 15, 1), new)
    view = {r["id"]: r for r in actions.payload(plan_t)["rows"]}[new["id"]]
    check("added team gets a warm-up slot", view["status"] == "OK" and view["opvarmningStart"] != "", view)
    check("added team is marked manual in the view", view["manual"] is True)
    actions.patch_row(plan_t, new["id"], "hold", "Omdøbt hold")
    check("an added team can be renamed", new["Hold"] == "Omdøbt hold")
    check("an Excel team still cannot be renamed",
          raises(lambda: actions.patch_row(plan_t, plan_t["raw_rows"][0]["id"], "hold", "X"), 400) is not None)
    actions.patch_row(plan_t, new["id"], "hold", "Opvisning")
    check("a manual team is never reclassified by migrate",
          actions.migrate(json.loads(json.dumps(plan_t)))["raw_rows"][-1]["Type"] == "hold")
    sheets = pd.read_excel(BytesIO(actions.export_xlsx(plan_t)), sheet_name=None)
    check("added team is in the Excel export", "Opvisning" in list(sheets["Opvisning Sal A"]["Hold"]))
    actions.delete_row(plan_t, new["id"])
    sheets = pd.read_excel(BytesIO(actions.export_xlsx(plan_t)), sheet_name=None)
    check("deleted team is gone from the Excel export", list(sheets["Opvisning Sal A"]["Hold"]) == ["Hold 1"])
    res = json.loads(__import__("planner.browser", fromlist=["x"]).call(
        json.dumps(plan_t), "add_team", json.dumps({"hal": "Sal A", "name": "Via bro"})))
    check("browser bridge allows add_team", res["ok"] and res["plan"]["raw_rows"][-1]["Hold"] == "Via bro", res.get("error"))

    # ---------- placér opvarmning i et hul (træk på tidslinjen) ----------
    plan_p = actions.new_plan()
    actions.create_warmup_hall(plan_p, "V1")
    actions.create_show_hall(plan_p, "Sal")
    actions.upload(plan_p, [("d.xlsx", excel_bytes([("A", 30), ("B", 30)]))], show_hal="Sal")
    a, b = plan_p["raw_rows"]
    check("place_warmup unknown team -> 404", raises(lambda: actions.place_warmup(plan_p, "x", "V1", "08:00"), 404) is not None)
    check("place_warmup unknown hall -> 400", raises(lambda: actions.place_warmup(plan_p, a["id"], "Nope", "08:00"), 400) is not None)
    check("place_warmup bad time -> 400", raises(lambda: actions.place_warmup(plan_p, a["id"], "V1", "kl 8"), 400) is not None)
    actions.place_warmup(plan_p, b["id"], "V1", "9.10")
    vb = {r["id"]: r for r in actions.payload(plan_p)["rows"]}[b["id"]]
    check("place_warmup pins hall and start time", (vb["opvarmningHalBeregnet"], vb["opvarmningStart"], vb["status"])
          == ("V1", "09:10", "OK"), vb)
    before = copy.deepcopy(plan_p)
    err = raises(lambda: actions.place_warmup(plan_p, a["id"], "V1", "09:15"), 400)
    check("place_warmup on an occupied slot is refused, plan unchanged",
          err is not None and "ikke plads" in err.message and plan_p == before, err and err.message)
    err = raises(lambda: actions.place_warmup(plan_p, a["id"], "V1", "08:50"), 400)
    check("place_warmup that ends after the show is refused", err is not None and plan_p == before)

    # ---------- kortere opvarmning giver plads (ned til 10 min) ----------
    plan_s2 = actions.new_plan()
    actions.create_warmup_hall(plan_s2, "V1")
    actions.create_show_hall(plan_s2, "Sal")
    actions.upload(plan_s2, [("d.xlsx", excel_bytes([(c, 12) for c in "ABCDEF"]))], show_hal="Sal")
    # én hal, et hold hvert 12. minut: B, D og F får ikke plads med 15 min
    # (B ville skulle vente mere end 25 min)
    unplaced = [r["hold"] for r in actions.payload(plan_s2)["rows"] if r["status"] != "OK"]
    check("scenario: B, D and F have no room with 15 min", unplaced == ["B", "D", "F"], unplaced)
    f_id = next(r["id"] for r in plan_s2["raw_rows"] if r["Hold"] == "F")
    actions.patch_row(plan_s2, f_id, "opvarmningMin", 12)
    f = {r["hold"]: r for r in actions.payload(plan_s2)["rows"]}["F"]
    check("F fits with 12 min warm-up (09:43)", (f["status"], f["opvarmningStart"]) == ("OK", "09:43"), f)

    # ---------- kanttilfælde ----------
    plan_e = actions.new_plan()
    actions.create_warmup_hall(plan_e, "V1")
    actions.create_show_hall(plan_e, "Sal")
    actions.upload(plan_e, [("d.xlsx", excel_bytes([("A", 30), ("B", 30)]))], show_hal="Sal")
    actions.add_special_row(plan_e, "Sal", "pause")
    pause_id = plan_e["raw_rows"][-1]["id"]
    err = raises(lambda: actions.place_warmup(plan_e, pause_id, "V1", "08:00"), 400)
    check("a pause cannot be given a warm-up", err is not None and "Kun hold" in err.message, err and err.message)
    check("place_warmup rejects 24:00", raises(lambda: actions.place_warmup(plan_e, plan_e["raw_rows"][0]["id"], "V1", "24:00"), 400) is not None)
    a_id = plan_e["raw_rows"][0]["id"]
    actions.place_warmup(plan_e, a_id, "V1", "08:20")
    va = {r["id"]: r for r in actions.payload(plan_e)["rows"]}[a_id]
    check("an already placed team can be moved to a free slot", (va["opvarmningStart"], va["status"]) == ("08:20", "OK"), va)

    plan_n = actions.new_plan()
    actions.create_show_hall(plan_n, "Sal")
    actions.upload(plan_n, [("d.xlsx", excel_bytes([("A", 10)]))], show_hal="Sal")
    sol_n = actions.solve_warmups(plan_n)
    check("no warm-up halls -> solve changes nothing", sol_n["changes"] == [] and sol_n["placed"] == [], sol_n)
    check("place_warmup without warm-up halls is refused",
          raises(lambda: actions.place_warmup(plan_n, plan_n["raw_rows"][0]["id"], "V1", "08:00"), 400) is not None)

    plan_10 = actions.new_plan()
    actions.create_warmup_hall(plan_10, "V1")
    actions.create_show_hall(plan_10, "Sal")
    actions.upload(plan_10, [("d.xlsx", excel_bytes([(c, 12) for c in "ABCDEF"]))], show_hal="Sal")
    for r in plan_10["raw_rows"]:
        if r["Hold"] == "F":
            r["OpvarmningMinOverride"] = 10
    sol_10 = actions.solve_warmups(plan_10)
    check("solve never takes a team below 10 min",
          all(c["to"] >= 10 for c in sol_10["changes"]) and all(c["hold"] != "F" for c in sol_10["changes"]), sol_10)

    weird = '<script>alert("x")</script> Ø-hold & co'
    actions.add_team(plan_e, "Sal", weird)
    check("team names with HTML/special characters are stored as plain text", plan_e["raw_rows"][-1]["Hold"] == weird)
    check("very long team name is accepted and exported",
          actions.add_team(plan_e, "Sal", "X" * 300) is None and pd.read_excel(BytesIO(actions.export_xlsx(plan_e)), sheet_name=None) is not None)

    # ---------- flyt / slet flere hold på én gang ----------
    plan_b = plan_with_halls()
    actions.upload(plan_b, [("d.xlsx", excel_bytes([(f"H{i}", 10) for i in range(1, 7)]))], show_hal="Sal A")
    actions.upload(plan_b, [("e.xlsx", excel_bytes([("B1", 10)]))], show_hal="Sal B")
    ids = {r["Hold"]: r["id"] for r in plan_b["raw_rows"]}
    before = copy.deepcopy(plan_b)
    check("move_rows to unknown hall -> 404",
          raises(lambda: actions.move_rows(plan_b, [ids["H1"]], "Ingen"), 404) is not None and plan_b == before)
    check("move_rows with nothing selected -> 400", raises(lambda: actions.move_rows(plan_b, [], "Sal B"), 400) is not None)
    check("move_rows with only unknown ids -> 404", raises(lambda: actions.move_rows(plan_b, ["x", "y"], "Sal B"), 404) is not None)
    # valgt i "forkert" rækkefølge: rækkefølgen i hallen skal bevares
    actions.move_rows(plan_b, [ids["H5"], ids["H2"], ids["H4"], "ukendt"], "Sal B")
    sal_b = sorted((r for r in plan_b["raw_rows"] if r["OpvisningHal"] == "Sal B"), key=lambda r: r["Order"])
    check("moved teams go last in the target hall in their original order",
          [r["Hold"] for r in sal_b] == ["B1", "H2", "H4", "H5"], [r["Hold"] for r in sal_b])
    check("orders in the target hall are unique", len({r["Order"] for r in sal_b}) == len(sal_b))
    left = [r["Hold"] for r in plan_b["raw_rows"] if r["OpvisningHal"] == "Sal A"]
    check("other teams stay in the source hall", sorted(left) == ["H1", "H3", "H6"], left)
    view = {r["hold"]: r for r in actions.payload(plan_b)["rows"]}
    check("moved teams get new show times from the target hall", view["H2"]["opvisningTid"] == "09:10", view["H2"])
    actions.move_rows(plan_b, [ids["B1"]], "Sal B")
    check("moving a team to the hall it is already in changes nothing",
          next(r for r in plan_b["raw_rows"] if r["Hold"] == "B1")["Order"] == 0)

    check("delete_rows with nothing selected -> 400", raises(lambda: actions.delete_rows(plan_b, []), 400) is not None)
    actions.delete_rows(plan_b, [ids["H1"], ids["H3"], "ukendt"])
    check("delete_rows removes all selected and ignores unknown ids",
          sorted(r["Hold"] for r in plan_b["raw_rows"]) == ["B1", "H2", "H4", "H5", "H6"])
    res = json.loads(__import__("planner.browser", fromlist=["x"]).call(
        json.dumps(plan_b), "move_rows", json.dumps({"row_ids": [ids["H6"]], "hal": "Sal B"})))
    check("browser bridge allows move_rows", res["ok"], res.get("error"))
    res = json.loads(__import__("planner.browser", fromlist=["x"]).call(
        json.dumps(plan_b), "delete_rows", json.dumps({"row_ids": [ids["H6"]]})))
    check("browser bridge allows delete_rows", res["ok"] and len(res["plan"]["raw_rows"]) == 4, res.get("error"))

    # ---------- find løsning: forkort holdet og holdene omkring det ----------
    before = copy.deepcopy(plan_s2)
    missing = [r["hold"] for r in actions.payload(plan_s2)["rows"] if r["status"] != "OK"]
    sol = actions.solve_warmups(plan_s2)
    check("solve does not change the plan", plan_s2 == before)
    check("solve places at least one team without room", len(sol["placed"]) >= 1 and set(sol["placed"]) <= set(missing), sol)
    check("every team without room is either placed or remaining", sorted(sol["placed"] + sol["remaining"]) == sorted(missing))
    check("solve never goes below 10 min", all(c["to"] >= 10 for c in sol["changes"]), sol["changes"])
    check("solve also shortens teams around the one without room",
          any(c["hold"] not in missing for c in sol["changes"]), sol["changes"])
    check("solve changes each team by at most 5 min", all(c["from"] - c["to"] <= 5 for c in sol["changes"]), sol["changes"])
    ok_before = {r["hold"] for r in actions.payload(plan_s2)["rows"] if r["status"] == "OK"}
    applied = copy.deepcopy(plan_s2)
    actions.apply_solution(applied, [{"id": c["id"], "minutes": c["to"]} for c in sol["changes"]]
                           + [{"id": m["id"], "hal": m["toHal"]} for m in sol["moves"]])
    view = {r["hold"]: r for r in actions.payload(applied)["rows"]}
    check("applying the solution places exactly the promised teams",
          {h for h in missing if view[h]["status"] == "OK"} == set(sol["placed"]), (sol["placed"], sol["remaining"]))
    check("applying the solution keeps every team that already had room",
          all(view[h]["status"] == "OK" for h in ok_before))
    check("remaining lists the teams still without room",
          sorted(sol["remaining"]) == sorted(h for h in missing if view[h]["status"] != "OK"))

    plan_eft = actions.new_plan()
    actions.create_warmup_hall(plan_eft, "V1")
    actions.create_show_hall(plan_eft, "Sal")
    actions.upload(plan_eft, [("d.xlsx", excel_bytes([("Testby Efterskole", 12), ("A", 12), ("B", 12), ("C", 12)]))],
                   show_hal="Sal")
    sol_e = actions.solve_warmups(plan_eft)
    check("efterskoler are never shortened by solve", all("Efterskole" not in c["hold"] for c in sol_e["changes"]), sol_e)

    plan_dgi = actions.new_plan()
    actions.create_warmup_hall(plan_dgi, "V1")
    actions.create_show_hall(plan_dgi, "Sal")
    actions.upload(plan_dgi, [("d.xlsx", excel_bytes([("DGI Østjylland Rephold", 12), ("A", 12), ("B", 12), ("C", 12),
                                                         ("DGI MiniMix", 12), ("D", 12)]))], show_hal="Sal")
    sol_d = actions.solve_warmups(plan_dgi)
    check("DGI teams are never shortened by solve", all("DGI" not in c["hold"] for c in sol_d["changes"]), sol_d["changes"])
    check("apply_solution rejects unknown team", raises(lambda: actions.apply_solution(
        plan_eft, [{"id": "x", "minutes": 12}]), 404) is not None)
    check("apply_solution rejects < 1 min", raises(lambda: actions.apply_solution(
        plan_eft, [{"id": plan_eft["raw_rows"][1]["id"], "minutes": 0}]), 400) is not None)
    before = copy.deepcopy(plan_eft)
    check("apply_solution rejects an unknown hall and changes nothing", raises(lambda: actions.apply_solution(
        plan_eft, [{"id": plan_eft["raw_rows"][1]["id"], "minutes": 12},
                   {"id": plan_eft["raw_rows"][2]["id"], "hal": "Findes ikke"}]), 400) is not None and plan_eft == before)
    check("solve with nothing to solve returns empty", actions.solve_warmups(actions.new_plan())
          == {"changes": [], "moves": [], "placed": [], "remaining": [], "hints": []})

    # ---------- Find løsning prøver også andre haller ----------
    # A går på kl. 10 og tager V1 09:40–09:55. L går på 10:10, men V2 er
    # optaget af P (fast tid 09:30–10:10), så L står uden plads. Får L pladsen
    # i V1 først, kan A bare varme op lidt tidligere — ingen kortere opvarmning.
    mv = actions.new_plan()
    for hal in ("V1", "V2"):
        actions.create_warmup_hall(mv, hal)
    for sal, team, start in (("S1", "A", "10:00"), ("S2", "L", "10:10"), ("S3", "P", "10:15")):
        actions.create_show_hall(mv, sal)
        actions.set_show_hall_start_time(mv, sal, start)
        actions.upload(mv, [("d.xlsx", excel_bytes([team]))], show_hal=sal)
    for r in mv["raw_rows"]:
        r["OpvarmningMinOverride"] = {"A": 15, "L": 30, "P": 40}[r["Hold"]]
        if r["Hold"] == "P":
            r["OpvarmningHalOverride"], r["OpvarmningStartOverride"] = "V2", "09:30"
    missing = [r["hold"] for r in actions.payload(mv)["rows"] if r["status"] != "OK"]
    check("scenario: L has no room", missing == ["L"], missing)
    before = copy.deepcopy(mv)
    sol = actions.solve_warmups(mv)
    check("solve finds room by giving L a hall first, with no shorter warm-ups",
          sol["placed"] == ["L"] and sol["changes"] == [] and [(m["hold"], m["toHal"]) for m in sol["moves"]] == [("L", "V1")],
          sol)
    check("solve with moves does not change the plan", mv == before)
    actions.apply_solution(mv, [{"id": m["id"], "hal": m["toHal"]} for m in sol["moves"]])
    check("applying the move gives every team room", all(r["status"] == "OK" for r in actions.payload(mv)["rows"]))

    # Et hold, brugeren selv har låst til en hal, flyttes aldrig — men der
    # kommer et tip, hvis der er plads i en anden hal.
    hl = actions.new_plan()
    for hal in ("V1", "V2"):
        actions.create_warmup_hall(hl, hal)
    for sal, team, start in (("S1", "A", "10:00"), ("S2", "L", "10:00")):
        actions.create_show_hall(hl, sal)
        actions.set_show_hall_start_time(hl, sal, start)
        actions.upload(hl, [("d.xlsx", excel_bytes([team]))], show_hal=sal)
    ids = {r["Hold"]: r["id"] for r in hl["raw_rows"]}
    actions.place_warmup(hl, ids["A"], "V1", "09:40")          # A fast i V1 09:40–09:55
    actions.patch_row(hl, ids["L"], "opvarmningHal", "V1")      # L låst til V1, hvor der ikke er plads
    for r in hl["raw_rows"]:
        if r["Hold"] == "A":
            r["OpvarmningStartOverride"] = "09:15"              # A optager hele L's vindue
            r["OpvarmningMinOverride"] = 40
    views = {r["hold"]: r for r in actions.payload(hl)["rows"]}
    check("scenario: locked L has no room in V1", views["L"]["status"] != "OK", views["L"])
    sol = actions.solve_warmups(hl)
    check("solve never moves a team the user locked to a hall",
          all(m["hold"] != "L" for m in sol["moves"]) and "L" in sol["remaining"], sol)
    check("solve tells where a locked team would have room",
          [(h["hold"], h["lockedHal"], h["freeHal"]) for h in sol["hints"]] == [("L", "V1", "V2")], sol["hints"])

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
    check("bridge load('') gives the start plan with Hal 1", res["ok"] and res["plan"] == actions.start_plan())
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
    second = os.path.join(tmpdir, "hal2.xlsx")
    with open(second, "wb") as f:
        f.write(excel_bytes([("Hold 2", 10)]))
    res_h = json.loads(browser.upload_files_to_halls(json.dumps(actions.start_plan()),
                                                     json.dumps([[path, "Hal 1"], [second, "Hal 2"]])))
    check("bridge upload_files_to_halls loads each file into its hall",
          res_h["ok"] and [(r["Hold"], r["OpvisningHal"]) for r in res_h["plan"]["raw_rows"]]
          == [("Hold 1", "Hal 1"), ("Hold 2", "Hal 2")], res_h.get("error"))
    bad = os.path.join(tmpdir, "skrald.xlsx")
    with open(bad, "wb") as f:
        f.write(b"nej")
    res2 = json.loads(browser.upload_files(json.dumps(res["plan"]), json.dumps([bad]), ""))
    check("bridge upload_files returns a Danish error for a bad file",
          res2["ok"] is False and "skrald.xlsx" in res2["error"])
    res3 = json.loads(browser.upload_files_to_halls(json.dumps(res["plan"]), json.dumps([[path, "Sal A"], [bad, "Sal B"]])))
    check("bridge upload_files_to_halls refuses the whole batch on a bad file",
          res3["ok"] is False and "skrald.xlsx" in res3["error"])

    out = os.path.join(tmpdir, "ud.xlsx")
    exp = json.loads(browser.export_to(json.dumps(res["plan"]), out))
    check("bridge export_to writes an xlsx with the default name",
          exp == {"ok": True, "filename": "opvisning_med_opvarmning.xlsx"} and open(out, "rb").read(2) == b"PK", exp)
    exp = json.loads(browser.export_to(json.dumps(res["plan"]), out, "Lørdag: Arena"))
    check("bridge export_to returns the cleaned user name", exp["filename"] == "Lørdag Arena.xlsx", exp)

    res = json.loads(browser.import_plan("ikke json"))
    check("bridge import_plan rejects bad file", res == {"ok": False, "error": "Filen er ikke en gyldig plan.", "status": 400})
    res = json.loads(browser.import_plan(plan_json))
    check("bridge import_plan accepts a saved plan", res["ok"] and res["plan"]["warmup_halls"] == ["Varm 1"])

    return summary()


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
