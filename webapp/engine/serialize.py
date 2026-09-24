"""Beregnet plan -> JSON-venlige dicts til frontenden."""

from datetime import datetime
from typing import List

import pandas as pd

from .rules import opvarmning_minutter
from .values import fmt_time, override_int, override_str


def problem_message(status: str, warmup_halls: List[str]) -> str:
    if not warmup_halls and status == "MANGLER":
        return "Ingen opvarmningshaller oprettet — opret mindst én under \"Haller\"."
    if status != "KAN IKKE PLANLÆGGES":
        return ""
    return "Mangler plads til opvarmning."


def minutes_from_day_start(value):
    """Minutter fra dagens start (2000-01-01 00:00). Tider efter midnat giver
    mere end 1440, så de aldrig forveksles med tidlig morgen. None hvis tom."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return int((value - datetime(2000, 1, 1)).total_seconds() // 60)


def to_row_dicts(df: pd.DataFrame, warmup_halls: List[str]) -> List[dict]:
    out = []
    for _, r in df.iterrows():
        out.append({
            "id": r["id"],
            "hold": r["Hold"],
            "type": r["Type"],
            "needsWarmup": r["Type"] == "hold",
            "opvisningHal": r["OpvisningHal"],
            "varighed": int(r["Varighed"]),
            "order": int(r["Order"]),
            "opvisningTid": fmt_time(r["OpvisningStart"]),
            "opvisningMin": minutes_from_day_start(r["OpvisningStart"]),
            "opvarmningStartMin": minutes_from_day_start(r["OpvarmningStart"]),
            "opvarmningSlutMin": minutes_from_day_start(r["OpvarmningSlut"]),
            "opvarmningMinOverride": override_int(r["OpvarmningMinOverride"]),
            "opvarmningMinDefault": opvarmning_minutter(r["Holdtype"], r["ErBarn"]),
            "opvarmningHalOverride": override_str(r["OpvarmningHalOverride"]),
            "opvarmningStartOverride": override_str(r["OpvarmningStartOverride"]),
            "opvarmningHalBeregnet": r["OpvarmningHal"],
            "opvarmningStart": fmt_time(r["OpvarmningStart"]),
            "opvarmningSlut": fmt_time(r["OpvarmningSlut"]),
            "status": r["Status"],
            "problemMessage": problem_message(r["Status"], warmup_halls),
        })
    return out


def to_schedule(df: pd.DataFrame) -> List[dict]:
    if df.empty:
        return []
    rows = df.dropna(subset=["OpvisningStart"]).sort_values("OpvisningStart")
    return [
        {
            "tid": fmt_time(r["OpvisningStart"]),
            "hold": r["Hold"],
            "type": r["Type"],
            "needsWarmup": r["Type"] == "hold",
            "opvisningHal": r["OpvisningHal"],
        }
        for _, r in rows.iterrows()
    ]
