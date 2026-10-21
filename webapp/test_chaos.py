"""
Kaos-test af planner.actions: tilfældige brugere, der prøver alt — mærkelige
navne, tider og tal, ødelagte filer, omrokeringer, Find løsning osv.

Efter hvert skridt tjekkes, at planen hænger sammen (ingen overlap, rigtige
opvisningstider, opvarmning 5–45 min før, ingen forsvundne hold, gem og åbn
giver samme plan ...). Kun ActionError (en pæn dansk besked) må komme ud af en
handling — alt andet er en fejl.

Kør: python test_chaos.py [BRUGERE] [SKRIDT] [START]     (standard 3 x 80)
Bruger rigtige Excel-filer fra projektmappen, hvis de findes (*_færdig.xlsx).
"""
import copy
import json
import random
import sys
import tempfile
import traceback
from io import BytesIO
from pathlib import Path

import pandas as pd

import engine
from planner import actions as A
from planner import browser
from testkit import excel_bytes

HERE = Path(__file__).parent
REAL = [(f.name, f.read_bytes()) for f in sorted(HERE.parent.glob("*_færdig.xlsx"))] or [
    # uden de rigtige filer: et stort, tæt program i to haller
    (f"dag_{hal}.xlsx", excel_bytes([(f"{hal} hold {i}", 8 + i % 7) for i in range(30)], start="08:30"))
    for hal in ("Arena", "Hal2")]

WEIRD_TEXT = ["", " ", "   Hal  ", "Arena", "Hal 1", "Hal 2", "Hal 3 A", "Hal 4", "æøå ÆØÅ", "<b>x</b>",
              "a/b\\c:*?", "x" * 300, "0", "null", "Opvisning", "Pause", "Dørene åbner", "😀 emoji", "\t\n"]
WEIRD_TIMES = ["", "9", "09", "9:30", "09:30", "9.30", "930", "0930", "23:59", "00:00", "24:00", "25:00",
               "12:60", "-1", "abc", "9:3", "  10:15 ", "1:2:3", "7.5", None, 930, 9.5]
WEIRD_NUM = [None, "", 0, 1, 5, 10, 15, 30, 40, 41, 60, 999, -5, "12", "abc", 9.7, "9.7", [1], {"a": 1}, True]


def odd_excels():
    def frame(df):
        buf = BytesIO()
        df.to_excel(buf, index=False)
        return buf.getvalue()
    return [
        ("tom.xlsx", frame(pd.DataFrame())),
        ("kun_header.xlsx", frame(pd.DataFrame(columns=["Tid", "Varighed", "Holdnavn"]))),
        ("andre_kolonner.xlsx", frame(pd.DataFrame({"Navn": ["A", "B"], "Tid": ["x", "y"]}))),
        ("negativ.xlsx", frame(pd.DataFrame({"Tid": ["09:00", ""], "Varighed": [-10, 999],
                                             "Holdnavn": ["Neg", "Stor"], "Antal deltagere": ["mange", None]}))),
        ("tekst_varighed.xlsx", frame(pd.DataFrame({"Tid": ["kl 9"], "Varighed": ["ti"], "Holdnavn": [None],
                                                    "Forening": ["Kun forening"]}))),
        ("dubletter.xlsx", frame(pd.DataFrame({"Tid": ["10:00"] * 3, "Varighed": [5, 5, 5],
                                               "Holdnavn": ["Samme", "Samme", "Samme"],
                                               "Holdtype": ["efterskole", "DGI", "Dans"]}))),
        ("sen.xlsx", frame(pd.DataFrame({"Tid": ["23:30"] + [""] * 5, "Varighed": [20] * 6,
                                         "Holdnavn": [f"Nat {i}" for i in range(6)]}))),
        ("skrald.xlsx", b"ikke en excel-fil"),
        ("tom_fil.xlsx", b""),
        ("lille.xlsx", excel_bytes(["L1", "L2", "L3"])),
    ]


ODD = odd_excels()


def mins(hhmm):
    h, m = map(int, hhmm.split(":"))
    return h * 60 + m


def check_plan(plan, where):
    """Alle de ting, der altid skal passe. Returnerer en liste af brud."""
    errs = []
    try:
        json.dumps(plan)
    except Exception as e:
        errs.append(f"plan kan ikke gemmes som JSON: {e}")
    names = [h["name"] for h in plan["show_halls"]]
    if len(names) != len(set(names)):
        errs.append(f"to opvisningshaller med samme navn: {names}")
    if len(plan["warmup_halls"]) != len(set(plan["warmup_halls"])):
        errs.append(f"to opvarmningshaller med samme navn: {plan['warmup_halls']}")
    if plan["warmup_halls"] and plan["priority_hall"] not in plan["warmup_halls"]:
        errs.append(f"prioritetshal {plan['priority_hall']!r} findes ikke")
    if not plan["warmup_halls"] and plan["priority_hall"] is not None:
        errs.append("prioritetshal sat uden opvarmningshaller")
    for r in plan["raw_rows"]:
        if r["OpvisningHal"] not in names:
            errs.append(f"hold {r['Hold']!r} ligger i en hal, der ikke findes: {r['OpvisningHal']!r}")
    ids = [r["id"] for r in plan["raw_rows"]]
    if len(ids) != len(set(ids)):
        errs.append("to rækker med samme id")
    for h in plan["show_halls"]:
        orders = [r["Order"] for r in plan["raw_rows"] if r["OpvisningHal"] == h["name"]]
        if len(orders) != len(set(orders)):
            errs.append(f"to rækker med samme plads i rækkefølgen i {h['name']}: {sorted(orders)}")
        if A.normalize_hhmm(h["startTime"]) != h["startTime"]:
            errs.append(f"ugyldig starttid gemt: {h['startTime']!r}")
    try:
        pay = A.payload(plan)
        json.dumps(pay)
    except Exception:
        return errs + ["payload fejler: " + traceback.format_exc(limit=3)]
    rows = pay["rows"]
    # opvisningstider: hallens start + varigheder i rækkefølge
    for h in plan["show_halls"]:
        t = mins(h["startTime"])
        for r in sorted((r for r in rows if r["opvisningHal"] == h["name"]), key=lambda r: r["order"]):
            if r["opvisningMin"] != t:
                errs.append(f"forkert opvisningstid for {r['hold']}: {r['opvisningMin']} != {t}")
                break
            t += r["varighed"]
    by_hall = {}
    for r in rows:
        if r["status"] == "OK":
            if not r["needsWarmup"]:
                errs.append(f"{r['hold']} har opvarmning, men skal ikke varme op")
            if r["opvarmningHalBeregnet"] not in plan["warmup_halls"]:
                errs.append(f"{r['hold']} varmer op i en hal, der ikke findes")
            warm = r["opvarmningMinOverride"] if r["opvarmningMinOverride"] is not None else r["opvarmningMinDefault"]
            if r["opvarmningSlutMin"] - r["opvarmningStartMin"] != warm:
                errs.append(f"{r['hold']}: opvarmningen er ikke {warm} min lang")
            if r["opvarmningSlutMin"] > r["opvisningMin"] - engine.GANG_MIN:
                errs.append(f"{r['hold']}: opvarmningen slutter for sent")
            if r["opvarmningStartMin"] < r["opvisningMin"] - engine.MAX_START_BEFORE_MIN:
                errs.append(f"{r['hold']}: opvarmningen starter mere end 45 min før")
            if not r["opvarmningStartOverride"] and r["opvarmningSlutMin"] < r["opvisningMin"] - engine.GANG_MIN - engine.MAX_EARLY_TOTAL_MIN:
                errs.append(f"{r['hold']}: venter mere end 30 min")
            by_hall.setdefault(r["opvarmningHalBeregnet"], []).append(r)
        elif r["status"] not in ("IGNORERET", "KAN IKKE PLANLÆGGES", "MANGLER"):
            errs.append(f"ukendt status {r['status']!r}")
        if r["needsWarmup"] and r["status"] == "IGNORERET":
            errs.append(f"{r['hold']} skal varme op, men er ignoreret")
        if r["needsWarmup"] and plan["warmup_halls"] and r["status"] == "MANGLER":
            errs.append(f"{r['hold']} har status MANGLER, selv om der er haller")
    for hal, lst in by_hall.items():
        lst.sort(key=lambda r: r["opvarmningStartMin"])
        for a, b in zip(lst, lst[1:]):
            if b["opvarmningStartMin"] < a["opvarmningSlutMin"]:
                errs.append(f"overlap i {hal}: {a['hold']} og {b['hold']}")
    # gem og åbn igen giver samme plan
    try:
        again = A.import_plan(json.dumps(plan))
        if A.payload(again)["rows"] != rows:
            errs.append("planen ser anderledes ud efter gem og åbn")
    except Exception:
        errs.append("gem og åbn fejler: " + traceback.format_exc(limit=3))
    return errs


def random_step(rng, plan, log):
    rows = plan["raw_rows"]
    ids = [r["id"] for r in rows]
    show = [h["name"] for h in plan["show_halls"]]
    warm = plan["warmup_halls"]
    pick = lambda seq, *extra: rng.choice(list(seq) + list(extra)) if (seq or extra) else None
    any_id = lambda: pick(ids, "findes-ikke", "")
    name = lambda: pick(WEIRD_TEXT + show + warm)
    choice = rng.choices(
        ["upload", "upload_to_halls", "patch", "delete_row", "move_rows", "delete_rows", "special", "team",
         "place", "reorder", "swap", "solve", "apply_junk", "reset", "warm_create", "warm_rename", "warm_delete",
         "prio", "show_create", "show_rename", "show_time", "show_delete", "export", "reopen"],
        weights=[4, 2, 14, 2, 3, 1, 3, 3, 6, 4, 4, 2, 1, 0.3, 2, 1.5, 1, 1, 2, 1.5, 3, 0.8, 0.5, 1])[0]
    if choice == "upload":
        files = rng.sample(REAL + ODD, rng.randint(1, 2))
        hal = pick(show, None, "", "Ny hal", *WEIRD_TEXT[:4])
        log.append(f"upload {[f for f, _ in files]} -> {hal!r}")
        A.upload(plan, files, hal)
    elif choice == "upload_to_halls":
        groups = [(pick(show, "Ny hal", " "), rng.sample(REAL + ODD, 1)) for _ in range(rng.randint(0, 3))]
        log.append(f"upload_to_halls {[(h, [f for f, _ in fs]) for h, fs in groups]}")
        A.upload_to_halls(plan, groups)
    elif choice == "patch":
        field = rng.choice(["hold", "varighed", "opvarmningMin", "opvisningHal", "opvarmningHal", "opvarmningStart", "nope"])
        value = {"hold": name, "varighed": lambda: pick(WEIRD_NUM), "opvarmningMin": lambda: pick(WEIRD_NUM),
                 "opvisningHal": name, "opvarmningHal": lambda: pick(warm, "", None, "Findes ikke"),
                 "opvarmningStart": lambda: pick(WEIRD_TIMES), "nope": lambda: 1}[field]()
        rid = any_id()
        log.append(f"patch {rid} {field}={value!r}")
        A.patch_row(plan, rid, field, value)
    elif choice == "delete_row":
        rid = any_id()
        log.append(f"delete_row {rid}")
        A.delete_row(plan, rid)
    elif choice == "move_rows":
        sel = rng.sample(ids, min(len(ids), rng.randint(0, 6))) + rng.choice([[], ["findes-ikke"]])
        hal = pick(show, "Findes ikke")
        log.append(f"move_rows {len(sel)} -> {hal!r}")
        A.move_rows(plan, sel, hal)
    elif choice == "delete_rows":
        sel = rng.sample(ids, min(len(ids), rng.randint(0, 4)))
        log.append(f"delete_rows {len(sel)}")
        A.delete_rows(plan, sel)
    elif choice == "special":
        t = rng.choice(["pause", "faneindmarch", "faneudmarch", "dorene_aabner", "fest", "hold", "andet"])
        hal = pick(show, "Findes ikke")
        log.append(f"special {t} -> {hal!r}")
        A.add_special_row(plan, hal, t)
    elif choice == "team":
        hal = pick(show, "Findes ikke")
        n = name()
        log.append(f"add_team {n!r} -> {hal!r}")
        A.add_team(plan, hal, n)
    elif choice == "place":
        rid, hal, t = any_id(), pick(warm, "Findes ikke"), pick(WEIRD_TIMES)
        log.append(f"place {rid} {hal!r} {t!r}")
        A.place_warmup(plan, rid, hal, t)
    elif choice == "reorder":
        hal = pick(show, "Findes ikke")
        in_hal = [r["id"] for r in rows if r["OpvisningHal"] == hal]
        rng.shuffle(in_hal)
        mode = rng.choice(["all", "some", "dupes", "foreign"])
        if mode == "some":
            in_hal = in_hal[: rng.randint(0, len(in_hal))]
        elif mode == "dupes" and in_hal:
            in_hal = in_hal + in_hal[:2]
        elif mode == "foreign":
            in_hal = in_hal + rng.sample(ids, min(2, len(ids)))
        log.append(f"reorder {hal!r} {mode} {len(in_hal)}")
        A.reorder_rows(plan, hal, in_hal)
    elif choice == "swap":
        a, b = any_id(), any_id()
        log.append(f"swap {a} {b}")
        A.swap_warmup_time(plan, a, b)
    elif choice == "solve":
        before = copy.deepcopy(plan)
        s = A.solve_warmups(plan)
        if plan != before:
            raise AssertionError("solve_warmups ændrede planen")
        json.dumps(s)
        log.append(f"solve placed={len(s['placed'])} changes={len(s['changes'])} moves={len(s['moves'])}")
        if rng.random() < 0.8:
            v0 = A._views(plan)
            ok_before = A._ok_ids(v0)
            unplaced_before = {i for i, v in v0.items() if v["needsWarmup"] and v["status"] == "KAN IKKE PLANLÆGGES"}
            A.apply_solution(plan, [{"id": c["id"], "minutes": c["to"]} for c in s["changes"]]
                             + [{"id": m["id"], "hal": m["toHal"]} for m in s["moves"]])
            views = A._views(plan)
            ok_after = A._ok_ids(views)
            lost = ok_before - ok_after
            if lost:
                raise AssertionError(f"Brug løsningen fik {len(lost)} hold til at miste plads")
            got = sum(views[i]["status"] == "OK" for i in unplaced_before)
            if got != len(s["placed"]):
                raise AssertionError(f"Brug løsningen lovede {len(s['placed'])} hold plads, men gav {got}")
    elif choice == "apply_junk":
        junk = rng.choice([[{"id": any_id(), "minutes": pick(WEIRD_NUM)}], [{"id": any_id(), "hal": name()}],
                           [{}], [{"id": None}], []])
        log.append(f"apply_solution junk {junk!r}")
        A.apply_solution(plan, junk)
    elif choice == "reset":
        log.append("reset")
        A.reset_rows(plan)
    elif choice == "warm_create":
        n = name()
        log.append(f"warm_create {n!r}")
        A.create_warmup_hall(plan, n)
    elif choice == "warm_rename":
        o, n = pick(warm, "Findes ikke"), name()
        log.append(f"warm_rename {o!r} -> {n!r}")
        A.rename_warmup_hall(plan, o, n)
    elif choice == "warm_delete":
        n = pick(warm, "Findes ikke")
        log.append(f"warm_delete {n!r}")
        A.delete_warmup_hall(plan, n)
    elif choice == "prio":
        n = pick(warm, "Findes ikke", "")
        log.append(f"prio {n!r}")
        A.set_priority_hall(plan, n)
    elif choice == "show_create":
        n = name()
        log.append(f"show_create {n!r}")
        A.create_show_hall(plan, n)
    elif choice == "show_rename":
        o, n = pick(show, "Findes ikke"), name()
        log.append(f"show_rename {o!r} -> {n!r}")
        A.rename_show_hall(plan, o, n)
    elif choice == "show_time":
        n, t = pick(show, "Findes ikke"), pick(WEIRD_TIMES)
        log.append(f"show_time {n!r} {t!r}")
        A.set_show_hall_start_time(plan, n, t)
    elif choice == "show_delete":
        n = pick(show, "Findes ikke")
        log.append(f"show_delete {n!r}")
        A.delete_show_hall(plan, n)
    elif choice == "export":
        log.append("export")
        data = A.export_xlsx(plan)
        pd.read_excel(BytesIO(data), sheet_name=None)
        out = Path(tempfile.gettempdir()) / "chaos_export.xlsx"
        res = json.loads(browser.export_to(json.dumps(plan), str(out), rng.choice(WEIRD_TEXT)))
        if not res["ok"] or not res["filename"].endswith(".xlsx"):
            raise AssertionError(f"eksport via broen fejlede: {res}")
    elif choice == "reopen":
        log.append("gem og åbn")
        plan.clear()
        plan.update(A.import_plan(json.dumps(copy.deepcopy(plan) or A.start_plan())))


def run(seeds=3, steps=80, start=0):
    problems = {}
    for seed in range(seeds):
        rng = random.Random(seed + start)
        plan = A.start_plan()
        log = []
        for step in range(steps):
            snapshot = copy.deepcopy(plan)
            try:
                random_step(rng, plan, log)
            except A.ActionError as e:
                if plan != snapshot:
                    key = f"ActionError ændrede planen: {log[-1].split(' ')[0]}"
                    problems.setdefault(key, (seed, step, log[-6:], e.message))
                continue
            except Exception as e:
                key = f"{type(e).__name__}: {str(e)[:120]} (ved {log[-1].split(' ')[0] if log else '?'})"
                problems.setdefault(key, (seed, step, log[-6:], traceback.format_exc(limit=4)))
                plan = snapshot
                continue
            errs = check_plan(plan, log[-1])
            for err in errs:
                key = err.split(":")[0][:80] + f" (efter {log[-1].split(' ')[0]})"
                problems.setdefault(key, (seed, step, log[-6:], err))
            if errs:
                plan = snapshot   # fortsæt fra en sund plan, så én fejl ikke skjuler de næste
    return problems


if __name__ == "__main__":
    seeds, steps = int(sys.argv[1]), int(sys.argv[2])
    probs = run(seeds, steps)
    print(f"{seeds} brugere x {steps} skridt: {len(probs)} slags fejl")
    for key, (seed, step, log, detail) in probs.items():
        print(f"\n### {key}\n  seed={seed} skridt={step}\n  " + "\n  ".join(log) + f"\n  -> {str(detail)[:600]}")
