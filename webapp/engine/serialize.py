"""Beregnet plan -> JSON-venlige dicts til frontenden."""

from typing import List

import pandas as pd

from .rules import opvarmning_minutter
from .values import fmt_time, override_int, override_str


def problem_message(status: str, warmup_halls: List[str]) -> str:
    if not warmup_halls and status == "MANGLER":
        return "Ingen opvarmningshaller oprettet — opret mindst én under \"Haller\"."
    if status != "KAN IKKE PLANLÆGGES":
        return ""
    return (
        "Dette hold kan ikke gå på opvarmning nu — prøv en kortere "
        "opvarmningstid, eller flyt holdet i programmet."
    )


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
