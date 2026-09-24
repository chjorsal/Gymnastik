"""
Unit-tests for engine.py — kører isoleret uden server, rører ikke ved
state.json. Test edge-cases og valider grundlogikken.

Kør: python test_engine.py
"""
import sys
from datetime import datetime, timedelta

import pandas as pd

import engine

PASS = []
FAIL = []


def check(name, condition, detail=""):
    if condition:
        PASS.append(name)
    else:
        FAIL.append((name, detail))
        print(f"FAIL: {name}  {detail}")


def run():
    # ============================================================
    # classify_type
    # ============================================================
    check("classify_type empty -> andet", engine.classify_type("") == "andet")
    check("classify_type None -> andet", engine.classify_type(None) == "andet")
    check("classify_type whitespace -> andet", engine.classify_type("   ") == "andet")
    check("classify_type Pause -> pause", engine.classify_type("Pause") == "pause")
    check("classify_type case-insensitive PAUSE -> pause", engine.classify_type("STOR PAUSE") == "pause")
    check("classify_type Faneindmarch -> faneindmarch", engine.classify_type("Faneindmarch") == "faneindmarch")
    check("classify_type Faneudmarch -> faneudmarch", engine.classify_type("Faneudmarch") == "faneudmarch")
    check("classify_type Dørene åbner -> dorene_aabner", engine.classify_type("Dørene åbner") == "dorene_aabner")
    check("classify_type Døren åbnes -> dorene_aabner", engine.classify_type("Døren åbnes kl 9") == "dorene_aabner")
    check("classify_type Velkommen -> andet", engine.classify_type("Velkommen") == "andet")
    check("classify_type Velkomst -> andet", engine.classify_type("Velkomst") == "andet")
    check("classify_type random team name -> hold", engine.classify_type("Lystrup Springmix") == "hold")
    check("classify_type 'Andet' literal -> hold (no keyword match)", engine.classify_type("Andet") == "hold")
    check("classify_type nan string -> andet", engine.classify_type("nan") == "andet")

    # ============================================================
    # clean_hal_name
    # ============================================================
    check(
        "clean_hal_name strips id/weekday/færdig",
        engine.clean_hal_name("202609554901_Fredag_Arena_færdig") == "Arena",
    )
    check(
        "clean_hal_name keeps short numeric segments",
        engine.clean_hal_name("Hal_3_A") == "Hal 3 A",
    )
    check("clean_hal_name preserves already-clean name", engine.clean_hal_name("Hal 3 A") == "Hal 3 A")
    check("clean_hal_name empty -> empty", engine.clean_hal_name("") == "")
    check("clean_hal_name None -> empty", engine.clean_hal_name(None) == "")
    check(
        "clean_hal_name all-junk falls back to original",
        engine.clean_hal_name("Fredag_færdig") == "Fredag_færdig",
    )

    # ============================================================
    # override_int / override_str
    # ============================================================
    check("override_int None -> None", engine.override_int(None) is None)
    check("override_int '' -> None", engine.override_int("") is None)
    check("override_int NaN -> None", engine.override_int(float("nan")) is None)
    check("override_int '15' -> 15", engine.override_int("15") == 15)
    check("override_int 15.0 -> 15", engine.override_int(15.0) == 15)
    check("override_int garbage -> None", engine.override_int("abc") is None)
    check("override_str None -> None", engine.override_str(None) is None)
    check("override_str '' -> None", engine.override_str("") is None)
    check("override_str 'Hal 4' -> 'Hal 4'", engine.override_str("Hal 4") == "Hal 4")

    # ============================================================
    # parse_clock
    # ============================================================
    t = engine.parse_clock("09:30")
    check("parse_clock valid HH:MM", t.hour == 9 and t.minute == 30)
    t2 = engine.parse_clock("garbage", (7, 15))
    check("parse_clock invalid falls back", t2.hour == 7 and t2.minute == 15)
    t3 = engine.parse_clock(None, (8, 0))
    check("parse_clock None falls back", t3.hour == 8 and t3.minute == 0)

    # ============================================================
    # build_dataframe — edge cases
    # ============================================================
    empty_df = engine.build_dataframe([], [])
    check("build_dataframe empty raw_rows -> empty df, no crash", len(empty_df) == 0)
    check(
        "build_dataframe empty df has all expected columns",
        set(["id", "Hold", "Type", "OpvisningStart", "OpvarmningHalOverride"]).issubset(set(empty_df.columns)),
    )

    show_halls = [{"name": "TestHal", "startTime": "09:00"}]

    # missing OpvarmningHalOverride key entirely (legacy row) must not crash
    legacy_row = {
        "id": "r1", "Hold": "Legacy Team", "Type": "hold", "AntalPersoner": 20,
        "HoldtypeRaw": None, "AlderRaw": None, "OpvisningHal": "TestHal",
        "Varighed": 10, "OpvarmningMinOverride": None, "Order": 0,
        # bevidst UDEN "OpvarmningHalOverride"
    }
    df_legacy = engine.build_dataframe([legacy_row], show_halls)
    check("build_dataframe tolerates missing OpvarmningHalOverride key", len(df_legacy) == 1)
    check(
        "build_dataframe defaults missing override to None",
        engine.override_str(df_legacy.iloc[0]["OpvarmningHalOverride"]) is None,
    )

    # cascading time: 3 rows, verify Order-based cascade
    rows3 = [
        {"id": "a", "Hold": "A", "Type": "hold", "AntalPersoner": 10, "HoldtypeRaw": None,
         "AlderRaw": None, "OpvisningHal": "TestHal", "Varighed": 20, "OpvarmningMinOverride": None,
         "OpvarmningHalOverride": None, "Order": 0},
        {"id": "b", "Hold": "B", "Type": "hold", "AntalPersoner": 10, "HoldtypeRaw": None,
         "AlderRaw": None, "OpvisningHal": "TestHal", "Varighed": 15, "OpvarmningMinOverride": None,
         "OpvarmningHalOverride": None, "Order": 1},
        {"id": "c", "Hold": "C", "Type": "hold", "AntalPersoner": 10, "HoldtypeRaw": None,
         "AlderRaw": None, "OpvisningHal": "TestHal", "Varighed": 5, "OpvarmningMinOverride": None,
         "OpvarmningHalOverride": None, "Order": 2},
    ]
    df3 = engine.build_dataframe(rows3, show_halls)
    times = {r["id"]: r["OpvisningStart"] for _, r in df3.iterrows()}
    check("cascade: A starts at hal start (09:00)", times["a"] == datetime(2000, 1, 1, 9, 0))
    check("cascade: B starts after A's 20min (09:20)", times["b"] == datetime(2000, 1, 1, 9, 20))
    check("cascade: C starts after B's 15min (09:35)", times["c"] == datetime(2000, 1, 1, 9, 35))

    # negative varighed — should not silently produce backwards-flowing cascade
    rows_neg = [
        {"id": "x", "Hold": "X", "Type": "hold", "AntalPersoner": 10, "HoldtypeRaw": None,
         "AlderRaw": None, "OpvisningHal": "TestHal", "Varighed": -30, "OpvarmningMinOverride": None,
         "OpvarmningHalOverride": None, "Order": 0},
        {"id": "y", "Hold": "Y", "Type": "hold", "AntalPersoner": 10, "HoldtypeRaw": None,
         "AlderRaw": None, "OpvisningHal": "TestHal", "Varighed": 10, "OpvarmningMinOverride": None,
         "OpvarmningHalOverride": None, "Order": 1},
    ]
    df_neg = engine.build_dataframe(rows_neg, show_halls)
    y_start = df_neg[df_neg["id"] == "y"].iloc[0]["OpvisningStart"]
    x_start = df_neg[df_neg["id"] == "x"].iloc[0]["OpvisningStart"]
    check(
        "NEGATIVE VARIGHED: Y should not start before X (cascade must not go backwards)",
        y_start >= x_start,
        f"x_start={x_start} y_start={y_start}",
    )

    # AntalPersoner NaN/blank -> 0, ErBarn resolution, ignored logic
    zero_antal_row = {
        "id": "z", "Hold": "Zero Antal Hold", "Type": "hold", "AntalPersoner": 0,
        "HoldtypeRaw": None, "AlderRaw": None, "OpvisningHal": "TestHal",
        "Varighed": 10, "OpvarmningMinOverride": None, "OpvarmningHalOverride": None, "Order": 0,
    }
    df_zero = engine.build_dataframe([zero_antal_row], show_halls)
    check(
        "AntalPersoner=0 hold-type row is still type=hold (not silently reclassified)",
        df_zero.iloc[0]["Type"] == "hold",
    )
    # Per eksplicit brugerbeslutning ("kun Type afgør, intet bagom") er et
    # hold ALTID berettiget til opvarmning uanset deltagerantal — der er
    # bevidst ingen skjult antal<=0-undtagelse længere.
    check("and is NOT ignored — only Type decides warmup eligibility now", bool(df_zero.iloc[0]["_ignored"]) is False)

    # unicode round-trip
    uni_row = {
        "id": "u", "Hold": "Højbjerg Øvede – Spring/Rytme 3.-5. Kl. æøå ÆØÅ", "Type": "hold",
        "AntalPersoner": 15, "HoldtypeRaw": None, "AlderRaw": None, "OpvisningHal": "TestHal",
        "Varighed": 10, "OpvarmningMinOverride": None, "OpvarmningHalOverride": None, "Order": 0,
    }
    df_uni = engine.build_dataframe([uni_row], show_halls)
    check(
        "unicode team name round-trips unchanged",
        df_uni.iloc[0]["Hold"] == "Højbjerg Øvede – Spring/Rytme 3.-5. Kl. æøå ÆØÅ",
    )

    # ============================================================
    # compute_plan — edge cases
    # ============================================================
    df3_plan = engine.compute_plan(df3, [], None)
    check(
        "compute_plan with NO warmup halls -> status MANGLER, no crash",
        all(s == "MANGLER" for s in df3_plan["Status"]),
    )

    df3_plan2 = engine.compute_plan(df3, ["Hal X"], "Hal X")
    check(
        "compute_plan single hall, 3 non-overlapping teams -> all OK",
        all(s == "OK" for s in df3_plan2["Status"]),
    )

    # two teams with identical show time both needing warmup -> only enough
    # room for one in a single hall (they will genuinely collide)
    tight_rows = [
        {"id": "p", "Hold": "P", "Type": "hold", "AntalPersoner": 10, "HoldtypeRaw": None,
         "AlderRaw": "voksen", "OpvisningHal": "TestHal", "Varighed": 5, "OpvarmningMinOverride": 60,
         "OpvarmningHalOverride": None, "Order": 0},
        {"id": "q", "Hold": "Q", "Type": "hold", "AntalPersoner": 10, "HoldtypeRaw": None,
         "AlderRaw": "voksen", "OpvisningHal": "TestHal", "Varighed": 5, "OpvarmningMinOverride": 60,
         "OpvarmningHalOverride": None, "Order": 1},
    ]
    df_tight = engine.build_dataframe(tight_rows, show_halls)
    df_tight_plan = engine.compute_plan(df_tight, ["Hal Only"], "Hal Only")
    statuses = set(df_tight_plan["Status"])
    check(
        "two heavily overlapping 60min-warmup teams in ONE hal -> at least one fails",
        "KAN IKKE PLANLÆGGES" in statuses,
        f"statuses={statuses}",
    )
    # same scenario but with 2 halls available -> both should fit
    df_tight_plan2 = engine.compute_plan(df_tight, ["Hal Only", "Hal Two"], "Hal Only")
    check(
        "same scenario with a SECOND hall available -> both placed OK",
        all(s == "OK" for s in df_tight_plan2["Status"]),
    )

    # manual override pins to a specific hal, and is respected even when a
    # different hal is objectively free
    pinned_row = {
        "id": "pin1", "Hold": "Pinned", "Type": "hold", "AntalPersoner": 10, "HoldtypeRaw": None,
        "AlderRaw": "voksen", "OpvisningHal": "TestHal", "Varighed": 10, "OpvarmningMinOverride": None,
        "OpvarmningHalOverride": "Hal B", "Order": 0,
    }
    df_pin = engine.build_dataframe([pinned_row], show_halls)
    df_pin_plan = engine.compute_plan(df_pin, ["Hal A", "Hal B"], "Hal A")
    check(
        "manual override places team in the pinned hal, not the priority hal",
        df_pin_plan.iloc[0]["OpvarmningHal"] == "Hal B",
    )

    # override pointing at a hal that no longer exists (e.g. deleted) ->
    # must gracefully fall back to automatic, not crash / not silently fail
    stale_pin_row = {
        "id": "pin2", "Hold": "StalePinned", "Type": "hold", "AntalPersoner": 10, "HoldtypeRaw": None,
        "AlderRaw": "voksen", "OpvisningHal": "TestHal", "Varighed": 10, "OpvarmningMinOverride": None,
        "OpvarmningHalOverride": "Hal That Was Deleted", "Order": 0,
    }
    df_stale = engine.build_dataframe([stale_pin_row], show_halls)
    df_stale_plan = engine.compute_plan(df_stale, ["Hal A", "Hal B"], "Hal A")
    check(
        "override to a deleted/nonexistent hal falls back to automatic placement",
        df_stale_plan.iloc[0]["Status"] == "OK",
        f"status={df_stale_plan.iloc[0]['Status']}",
    )

    # ---- manual START-time override (drag-and-drop feature) ----
    start_pin_row = {
        "id": "sp1", "Hold": "StartPinned", "Type": "hold", "AntalPersoner": 10, "HoldtypeRaw": None,
        "AlderRaw": "voksen", "OpvisningHal": "TestHal", "Varighed": 10, "OpvarmningMinOverride": 15,
        "OpvarmningHalOverride": None, "OpvarmningStartOverride": "08:05", "Order": 0,
    }
    df_sp = engine.build_dataframe([start_pin_row], show_halls)
    df_sp_plan = engine.compute_plan(df_sp, ["Hal A", "Hal B"], "Hal A")
    check(
        "manual start-time override places the team at EXACTLY that time",
        df_sp_plan.iloc[0]["OpvarmningStart"] == datetime(2000, 1, 1, 8, 5),
        f"got {df_sp_plan.iloc[0]['OpvarmningStart']}",
    )

    # start-override + hal-override together -> restricted to that one hal
    # at that exact time; if occupied, must fail rather than use another hal
    swap_rows = [
        {"id": "swA", "Hold": "SwapA", "Type": "hold", "AntalPersoner": 10, "HoldtypeRaw": None,
         "AlderRaw": "voksen", "OpvisningHal": "TestHal", "Varighed": 10, "OpvarmningMinOverride": 15,
         "OpvarmningHalOverride": "Hal A", "OpvarmningStartOverride": "08:00", "Order": 0},
        {"id": "swB", "Hold": "SwapB", "Type": "hold", "AntalPersoner": 10, "HoldtypeRaw": None,
         "AlderRaw": "voksen", "OpvisningHal": "TestHal", "Varighed": 10, "OpvarmningMinOverride": 15,
         "OpvarmningHalOverride": "Hal A", "OpvarmningStartOverride": "08:00", "Order": 1},
    ]
    df_swap = engine.build_dataframe(swap_rows, show_halls)
    df_swap_plan = engine.compute_plan(df_swap, ["Hal A", "Hal B"], "Hal A")
    statuses_swap = list(df_swap_plan["Status"])
    check(
        "two rows pinned to the SAME hal+time genuinely collide -> exactly one fails",
        statuses_swap.count("OK") == 1 and statuses_swap.count("KAN IKKE PLANLÆGGES") == 1,
        f"statuses={statuses_swap}",
    )

    # realistic swap: two teams in the same hal exchange their computed
    # start times (mirrors what the drag-and-drop UI does)
    two_rows = [
        {"id": "t1", "Hold": "Early Team", "Type": "hold", "AntalPersoner": 10, "HoldtypeRaw": None,
         "AlderRaw": "voksen", "OpvisningHal": "TestHal", "Varighed": 30, "OpvarmningMinOverride": 15,
         "OpvarmningHalOverride": None, "Order": 0},
        {"id": "t2", "Hold": "Later Team", "Type": "hold", "AntalPersoner": 10, "HoldtypeRaw": None,
         "AlderRaw": "voksen", "OpvisningHal": "TestHal", "Varighed": 30, "OpvarmningMinOverride": 15,
         "OpvarmningHalOverride": None, "Order": 1},
    ]
    df_two = engine.build_dataframe(two_rows, show_halls)
    df_two_plan = engine.compute_plan(df_two, ["Hal A"], "Hal A")
    t1_start = df_two_plan[df_two_plan["id"] == "t1"].iloc[0]["OpvarmningStart"]
    t2_start = df_two_plan[df_two_plan["id"] == "t2"].iloc[0]["OpvarmningStart"]
    # nu sæt begges start-override til den ANDENS nuværende tid (byt)
    for row in two_rows:
        row["OpvarmningStartOverride"] = t2_start.strftime("%H:%M") if row["id"] == "t1" else t1_start.strftime("%H:%M")
    df_two_swapped = engine.build_dataframe(two_rows, show_halls)
    df_two_swapped_plan = engine.compute_plan(df_two_swapped, ["Hal A"], "Hal A")
    new_t1 = df_two_swapped_plan[df_two_swapped_plan["id"] == "t1"].iloc[0]["OpvarmningStart"]
    new_t2 = df_two_swapped_plan[df_two_swapped_plan["id"] == "t2"].iloc[0]["OpvarmningStart"]
    check(
        "drag-swap: the later team gets the earlier warmup start",
        new_t2 == t1_start,
        f"expected {t1_start}, got {new_t2}",
    )
    # Det tidlige hold får det SENERE tidspunkt, som slutter efter dets egen
    # opvisning — det skal vises som et problem, ikke stille som "OK".
    t1_status = df_two_swapped_plan[df_two_swapped_plan["id"] == "t1"].iloc[0]["Status"]
    check(
        "a pinned warmup that ends after the team's own show is flagged, not OK",
        t1_status == "KAN IKKE PLANLÆGGES",
        f"status={t1_status}, start={new_t1}",
    )

    check("classify: 'Opvisningspiger' is a real team", engine.classify_type("Opvisningspiger, junior og senior") == "hold")
    check("classify: standalone 'Opvisning' is not a team", engine.classify_type("Opvisning slut") == "andet")

    # efterskole gets priority hall + 30 min default
    eft_row = {
        "id": "eft", "Hold": "Testby Efterskole", "Type": "hold", "AntalPersoner": 50,
        "HoldtypeRaw": None, "AlderRaw": None, "OpvisningHal": "TestHal",
        "Varighed": 20, "OpvarmningMinOverride": None, "OpvarmningHalOverride": None, "Order": 0,
    }
    df_eft = engine.build_dataframe([eft_row], show_halls)
    check("efterskole auto-detected from name", df_eft.iloc[0]["Holdtype"] == "efterskole")
    df_eft_plan = engine.compute_plan(df_eft, ["Hal A", "Hal B (prio)"], "Hal B (prio)")
    check(
        "efterskole team lands in priority hal",
        df_eft_plan.iloc[0]["OpvarmningHal"] == "Hal B (prio)",
    )
    check(
        "efterskole default warmup is 30 min",
        (df_eft_plan.iloc[0]["OpvarmningSlut"] - df_eft_plan.iloc[0]["OpvarmningStart"]) == timedelta(minutes=30),
    )

    # DGI gets 30 min default (regression test for the fix earlier this session)
    dgi_row = {
        "id": "dgi", "Hold": "DGI Østjyllands Testhold", "Type": "hold", "AntalPersoner": 30,
        "HoldtypeRaw": None, "AlderRaw": "voksen", "OpvisningHal": "TestHal",
        "Varighed": 20, "OpvarmningMinOverride": None, "OpvarmningHalOverride": None, "Order": 0,
    }
    df_dgi = engine.build_dataframe([dgi_row], show_halls)
    check("DGI auto-detected from name", df_dgi.iloc[0]["Holdtype"] == "dgi")
    check(
        "DGI default warmup is 30 min",
        engine.opvarmning_minutter("dgi", False) == 30,
    )

    # non-hold types (pause/faneindmarch/etc) never get warmup regardless of data
    special_row = engine.new_special_row("TestHal", "pause", 0)
    df_special = engine.build_dataframe([special_row], show_halls)
    check("special row is _ignored", bool(df_special.iloc[0]["_ignored"]) is True)
    df_special_plan = engine.compute_plan(df_special, ["Hal A"], "Hal A")
    check("special row status is IGNORERET, never OK", df_special_plan.iloc[0]["Status"] == "IGNORERET")

    # ============================================================
    # to_row_dicts / to_schedule — must not crash on empty / edge data
    # ============================================================
    rows_out = engine.to_row_dicts(empty_df, [])
    check("to_row_dicts on empty df returns []", rows_out == [])
    sched_out = engine.to_schedule(empty_df)
    check("to_schedule on empty df returns []", sched_out == [])

    rows_out2 = engine.to_row_dicts(df3_plan2, ["Hal X"])
    check("to_row_dicts includes problemMessage key", all("problemMessage" in r for r in rows_out2))
    check("to_row_dicts includes opvarmningHalOverride key", all("opvarmningHalOverride" in r for r in rows_out2))

    # problem_message correctness
    check(
        "problem_message: no halls + MANGLER -> helpful message",
        engine.problem_message("MANGLER", []) != "",
    )
    check(
        "problem_message: OK status -> empty message",
        engine.problem_message("OK", ["Hal A"]) == "",
    )
    check(
        "problem_message: KAN IKKE PLANLÆGGES -> non-empty message",
        engine.problem_message("KAN IKKE PLANLÆGGES", ["Hal A"]) != "",
    )

    # ============================================================
    # build_workbook — must not crash on edge-case data
    # ============================================================
    try:
        empty_plan = engine.compute_plan(empty_df, ["Hal A"], "Hal A")
        buf = engine.build_workbook(empty_plan)
        check("build_workbook doesn't crash on totally empty (but computed) df", buf is not None)
    except Exception as e:
        check("build_workbook doesn't crash on totally empty (but computed) df", False, str(e))

    try:
        buf2 = engine.build_workbook(df_tight_plan)  # contains an unplaced row
        check("build_workbook doesn't crash with an unplaced/problem row", buf2 is not None)
    except Exception as e:
        check("build_workbook doesn't crash with an unplaced/problem row", False, str(e))

    # two halls whose names collide in the first 31 chars (Excel sheet name limit)
    long_hal_a = "Dette er en meget lang hal navn A der er over enogtredive tegn"
    long_hal_b = "Dette er en meget lang hal navn B der er over enogtredive tegn"
    rows_long = [
        {"id": "la", "Hold": "LongA", "Type": "hold", "AntalPersoner": 10, "HoldtypeRaw": None,
         "AlderRaw": "voksen", "OpvisningHal": "TestHal", "Varighed": 10, "OpvarmningMinOverride": None,
         "OpvarmningHalOverride": long_hal_a, "Order": 0},
        {"id": "lb", "Hold": "LongB", "Type": "hold", "AntalPersoner": 10, "HoldtypeRaw": None,
         "AlderRaw": "voksen", "OpvisningHal": "TestHal", "Varighed": 10, "OpvarmningMinOverride": None,
         "OpvarmningHalOverride": long_hal_b, "Order": 1},
    ]
    df_long = engine.build_dataframe(rows_long, show_halls)
    df_long_plan = engine.compute_plan(df_long, [long_hal_a, long_hal_b], long_hal_a)
    try:
        buf3 = engine.build_workbook(df_long_plan)
        check("build_workbook survives two hal names colliding at 31-char Excel sheet limit", buf3 is not None)
    except Exception as e:
        check("build_workbook survives two hal names colliding at 31-char Excel sheet limit", False, str(e))

    # ============================================================
    # build_workbook — ét ark pr. opvisningshal, forrest i filen
    # ============================================================
    from openpyxl import load_workbook

    halls_two = [{"name": "Store sal", "startTime": "09:00"}, {"name": "Lille sal/B", "startTime": "10:00"}]

    def team(rid, hold, hal, order):
        return {"id": rid, "Hold": hold, "Type": "hold", "AntalPersoner": 10, "HoldtypeRaw": None,
                "AlderRaw": "voksen", "OpvisningHal": hal, "Varighed": 10, "OpvarmningMinOverride": None,
                "OpvarmningHalOverride": None, "Order": order}

    rows_two = [
        team("s2", "Store B", "Store sal", 2),
        team("l0", "Lille A", "Lille sal/B", 0),
        engine.new_special_row("Store sal", "pause", 1),
        team("s0", "Store A", "Store sal", 0),
    ]
    plan_two = engine.compute_plan(engine.build_dataframe(rows_two, halls_two), ["Hal A"], "Hal A")
    wb = load_workbook(engine.build_workbook(plan_two, [h["name"] for h in halls_two]))
    check(
        "export: first sheets are one per show hall, in hall order",
        wb.sheetnames[:2] == ["Opvisning Store sal", "Opvisning Lille salB"],
        f"sheets={wb.sheetnames}",
    )
    store = [r[0] for r in wb["Opvisning Store sal"].iter_rows(min_row=2, values_only=True)]
    check("export: show hall sheet lists the program in order, incl. pause",
          store == ["Store A", "Pause", "Store B"], f"got {store}")
    lille = [r[0] for r in wb["Opvisning Lille salB"].iter_rows(min_row=2, values_only=True)]
    check("export: show hall sheet only has that hall's rows", lille == ["Lille A"], f"got {lille}")
    check("export: the existing sheets are kept after the hall sheets",
          {"Output", "OpvarmningPlan", "Hal A"} <= set(wb.sheetnames[2:]), f"sheets={wb.sheetnames}")

    # arknavne skal være unikke, også når de klippes ved Excels 31 tegn
    long_show = [{"name": "En meget lang opvisningshal nummer 1", "startTime": "09:00"},
                 {"name": "En meget lang opvisningshal nummer 2", "startTime": "09:00"}]
    rows_ls = [team("x1", "X1", long_show[0]["name"], 0), team("x2", "X2", long_show[1]["name"], 0)]
    plan_ls = engine.compute_plan(engine.build_dataframe(rows_ls, long_show), ["Hal A"], "Hal A")
    wb_ls = load_workbook(engine.build_workbook(plan_ls, [h["name"] for h in long_show]))
    firsts = [[r[0] for r in wb_ls[n].iter_rows(min_row=2, values_only=True)] for n in wb_ls.sheetnames[:2]]
    check("export: two long hall names get two separate sheets with the right teams",
          firsts == [["X1"], ["X2"]] and all(len(n) <= 31 for n in wb_ls.sheetnames),
          f"sheets={wb_ls.sheetnames} content={firsts}")

    # ============================================================
    # minutter fra dagens start — så tider efter midnat ikke ligner morgen
    # ============================================================
    long_rows = [
        {"id": f"n{i}", "Hold": f"Hold {i}", "Type": "hold", "AntalPersoner": 10, "HoldtypeRaw": None,
         "AlderRaw": "voksen", "OpvisningHal": "Sal", "Varighed": 120, "OpvarmningMinOverride": None,
         "OpvarmningHalOverride": None, "Order": i}
        for i in range(9)
    ]
    long_plan = engine.compute_plan(engine.build_dataframe(long_rows, [{"name": "Sal", "startTime": "09:00"}]),
                                    ["Hal A"], "Hal A")
    dicts = {d["id"]: d for d in engine.to_row_dicts(long_plan, ["Hal A"])}
    check("row dict has show time in minutes from day start", dicts["n0"]["opvisningMin"] == 9 * 60, dicts["n0"])
    check("warm-up minutes are given too",
          dicts["n0"]["opvarmningSlutMin"] - dicts["n0"]["opvarmningStartMin"] == 15, dicts["n0"])
    check("a show after midnight is past 1440 minutes, not wrapped to morning",
          dicts["n8"]["opvisningMin"] == 9 * 60 + 8 * 120 and dicts["n8"]["opvisningTid"] == "01:00", dicts["n8"])

    # ============================================================
    # summary
    # ============================================================
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("\nFAILED:")
        for name, detail in FAIL:
            print(f"  - {name}: {detail}")
    return len(FAIL) == 0


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
