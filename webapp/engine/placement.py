"""Placeringsalgoritmen: fordeler holdenes opvarmning i opvarmningshallerne."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd

from .config import FLEX_BARN, MAX_EARLY_MIN, SKIFTE_I_SLOTTET_MIN, SKIFTE_MIN, STEP_MIN
from .rules import gang_tid, opvarmning_minutter, priority_rank
from .values import override_int, override_str, parse_clock


@dataclass
class Booking:
    start: datetime
    end: datetime
    hold: str


def overlaps(a_start, a_end, b_start, b_end, gap: timedelta) -> bool:
    return a_start < (b_end + gap) and b_start < (a_end + gap)


def _first_free_hall(
    bookings: Dict[str, List[Booking]],
    halls: List[str],
    start: datetime,
    end: datetime,
    gap: timedelta,
) -> Optional[str]:
    """Første hal i listen hvor [start, end) er fri for overlap — bruges af
    både try_place (søger et vindue) og try_place_fixed (ét fast tidspunkt)."""
    for h in halls:
        bookings.setdefault(h, [])
        if all(not overlaps(start, end, b.start, b.end, gap) for b in bookings[h]):
            return h
    return None


def _book(
    bookings: Dict[str, List[Booking]],
    hold_name: str,
    placed: Optional[Tuple[str, datetime, datetime]],
) -> Optional[Tuple[str, datetime, datetime]]:
    """Registrerer en vellykket placering i bookings og returnerer den
    uændret (eller None hvis der ikke blev fundet en plads) — bruges til at
    undgå at gentage 'if placed: h,s,e=placed; bookings[...].append(...)'
    ved hvert placeringsforsøg i compute_plan."""
    if not placed:
        return None
    h, s, e = placed
    bookings.setdefault(h, []).append(Booking(s, e, hold_name))
    return placed


def try_place(
    bookings: Dict[str, List[Booking]],
    halls: List[str],
    warm_min: int,
    show_start: datetime,
    buffer_min: int,
    skifte_i_slot: int = SKIFTE_I_SLOTTET_MIN,
    max_early: int = MAX_EARLY_MIN,
) -> Optional[Tuple[str, datetime, datetime]]:
    gap = timedelta(minutes=SKIFTE_MIN)
    latest_end = show_start - timedelta(minutes=buffer_min)
    dur = timedelta(minutes=warm_min + skifte_i_slot)

    for offset in range(0, max_early + 1, STEP_MIN):
        warm_end = latest_end - timedelta(minutes=offset)
        warm_start = warm_end - dur
        h = _first_free_hall(bookings, halls, warm_start, warm_end, gap)
        if h:
            return h, warm_start, warm_end

    return None


def try_place_fixed(
    bookings: Dict[str, List[Booking]],
    halls: List[str],
    warm_min: int,
    fixed_start: datetime,
    skifte_i_slot: int = SKIFTE_I_SLOTTET_MIN,
) -> Optional[Tuple[str, datetime, datetime]]:
    """Som try_place, men prøver KUN præcis dette starttidspunkt (bruges når
    en bruger manuelt har trukket et hold til et bestemt klokkeslæt) — ingen
    søgning i et vindue."""
    gap = timedelta(minutes=SKIFTE_MIN)
    warm_end = fixed_start + timedelta(minutes=warm_min + skifte_i_slot)
    h = _first_free_hall(bookings, halls, fixed_start, warm_end, gap)
    return (h, fixed_start, warm_end) if h else None


def compute_plan(
    df_all: pd.DataFrame,
    warmup_halls: List[str],
    priority_hall: Optional[str],
) -> pd.DataFrame:
    df_all = df_all.copy()
    df_all["OpvarmningHal"] = ""
    df_all["OpvarmningStart"] = pd.NaT
    df_all["OpvarmningSlut"] = pd.NaT
    df_all["Status"] = df_all["_ignored"].apply(lambda x: "IGNORERET" if x else "MANGLER")

    if not warmup_halls or df_all.empty:
        return df_all

    if priority_hall not in warmup_halls:
        priority_hall = warmup_halls[0]

    df_plan = df_all[~df_all["_ignored"]].copy()
    if df_plan.empty:
        return df_all

    df_plan["_prio"] = df_plan.apply(
        lambda r: priority_rank(r["Holdtype"], r["AntalPersoner"], r["ErBarn"]),
        axis=1
    )
    df_plan = df_plan.sort_values(["_prio", "OpvisningStart"])

    bookings: Dict[str, List[Booking]] = {}
    results: Dict[str, Optional[Tuple[str, datetime, datetime]]] = {}

    halls_uden_prio = [h for h in warmup_halls if h != priority_hall]
    halls_prio_first = [priority_hall] + halls_uden_prio

    def warm_min_for(row) -> int:
        override = override_int(row["OpvarmningMinOverride"])
        if override is not None:
            return override
        return opvarmning_minutter(row["Holdtype"], row["ErBarn"])

    def hal_override_for(row) -> Optional[str]:
        """Manuel hal-tildeling sat af brugeren — hvis den peger på en
        eksisterende opvarmningshal, bruges KUN den hal (ingen automatisk
        fallback til andre haller)."""
        hal = override_str(row["OpvarmningHalOverride"])
        return hal if hal in warmup_halls else None

    def start_override_for(row) -> Optional[datetime]:
        """Manuelt fastsat opvarmnings-starttidspunkt (fra træk-og-slip) —
        hvis sat, placeres holdet PRÆCIS der i stedet for at blive søgt frem."""
        raw = override_str(row["OpvarmningStartOverride"])
        if raw is None:
            return None
        try:
            return parse_clock(raw)
        except Exception:
            return None

    # PASS 0: hold med et manuelt fastsat opvarmnings-tidspunkt (fx fra
    # træk-og-slip i en opvarmningshal) placeres først, præcis på det ønskede
    # tidspunkt — evt. begrænset til en samtidig låst hal.
    has_start_override = df_plan["OpvarmningStartOverride"].apply(lambda v: override_str(v) is not None)
    start_pinned_rows = df_plan[has_start_override].sort_values("OpvisningStart")
    for _, r in start_pinned_rows.iterrows():
        rid = r["id"]
        warm_min = warm_min_for(r)
        fixed_start = start_override_for(r)
        pinned_hal = hal_override_for(r)
        if pinned_hal:
            halls_to_try = [pinned_hal]
        elif r["Holdtype"] == "efterskole":
            halls_to_try = halls_prio_first
        else:
            halls_to_try = warmup_halls
        skifte = 0 if r["ErBarn"] else SKIFTE_I_SLOTTET_MIN
        placed = try_place_fixed(bookings, halls_to_try, warm_min, fixed_start, skifte)
        # Et fast tidspunkt der slutter efter holdet skal gå til opvisning
        # (fx efter en senere omrokering af programmet) er ugyldigt — vis det
        # som et problem i stedet for stille at melde "OK".
        latest_end = r["OpvisningStart"] - timedelta(minutes=gang_tid(r["Holdtype"], r["ErBarn"]))
        if placed and placed[2] > latest_end:
            placed = None
        results[rid] = _book(bookings, r["Hold"], placed)

    # PASS 1: efterskole (uden manuelt tidspunkt) i prioritetshallen
    eft_rows = df_plan[(df_plan["Holdtype"] == "efterskole") & ~has_start_override].sort_values("OpvisningStart")
    for _, r in eft_rows.iterrows():
        rid = r["id"]
        warm_min = warm_min_for(r)
        walk_min = gang_tid("efterskole", False)
        pinned_hal = hal_override_for(r)
        if pinned_hal:
            placed = try_place(bookings, [pinned_hal], warm_min, r["OpvisningStart"], walk_min, 0, 30)
        else:
            placed = try_place(bookings, halls_prio_first, warm_min, r["OpvisningStart"], walk_min, 0, 15)
        results[rid] = _book(bookings, r["Hold"], placed)

    # PASS 2: alle andre hold (aldrig efterskole — de er filtreret fra
    # non_eft_plan ovenfor, så der er ingen efterskole-gren her)
    non_eft_plan = df_plan[(df_plan["Holdtype"] != "efterskole") & ~has_start_override]
    for _, r in non_eft_plan.iterrows():
        rid = r["id"]
        holdtype = r["Holdtype"]
        er_barn = r["ErBarn"]

        warm_min = warm_min_for(r)
        walk_min = gang_tid(holdtype, er_barn)
        skifte = 0 if er_barn else SKIFTE_I_SLOTTET_MIN
        max_early = FLEX_BARN if er_barn else MAX_EARLY_MIN

        pinned_hal = hal_override_for(r)
        halls_to_try = [pinned_hal] if pinned_hal else warmup_halls
        placed = try_place(bookings, halls_to_try, warm_min, r["OpvisningStart"], walk_min, skifte, max_early)

        if not placed:
            fallback_extra = FLEX_BARN if er_barn else 20
            placed = try_place(bookings, halls_to_try, warm_min, r["OpvisningStart"], walk_min, skifte, max_early + fallback_extra)

        results[rid] = _book(bookings, r["Hold"], placed)

    # Skriv alle resultater i ét hug (i stedet for én maske pr. hold).
    placed = {rid: res for rid, res in results.items() if res}
    ids = df_all["id"]
    ok = ids.isin(placed.keys())
    for col, i in (("OpvarmningHal", 0), ("OpvarmningStart", 1), ("OpvarmningSlut", 2)):
        df_all.loc[ok, col] = ids[ok].map(lambda rid: placed[rid][i])
    df_all.loc[ok, "Status"] = "OK"
    failed = [rid for rid, res in results.items() if not res]
    df_all.loc[ids.isin(failed), "Status"] = "KAN IKKE PLANLÆGGES"

    return df_all
