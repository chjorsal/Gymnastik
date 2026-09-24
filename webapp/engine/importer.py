"""Excel-filer og nye programpunkter -> rå rækker -> DataFrame til planlægning."""

import re
from datetime import datetime, timedelta
from io import BytesIO
from typing import List, Optional, Tuple

import pandas as pd

from .config import DEFAULT_VARIGHED, TYPE_LABELS
from .rules import auto_er_barn, classify_type, read_er_barn, read_holdtype
from .values import _clean_str, _none_if_nan, new_id, parse_clock


_DAY_NAMES = {"mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag"}
_JUNK_WORDS = {"færdig", "endelig", "final"}


def clean_hal_name(raw: str) -> str:
    """Rydder et filnavn som '202609554901_Fredag_Arena_færdig' op til bare
    'Arena' — fjerner lange numeriske booking-id'er, ugedage og ord som
    'færdig'. Falder tilbage til det oprindelige navn hvis der intet er
    tilbage bagefter (fx hvis hele navnet er sådan et ord)."""
    raw = (raw or "").strip()
    if not raw:
        return raw
    parts = re.split(r'[_\-]+', raw)
    kept = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        low = part.lower()
        if part.isdigit() and len(part) >= 6:
            continue
        if low in _DAY_NAMES or low in _JUNK_WORDS:
            continue
        kept.append(part)
    cleaned = " ".join(kept).strip()
    return cleaned or raw


def load_excel_bytes(filename: str, content: bytes, show_hal: str, start_order: int) -> Tuple[List[dict], Optional[str]]:
    """Læser en uploadet Excel-fil og returnerer (rå rækker, forslag til
    hallens startklokkeslæt ud fra første rækkes 'Tid'-kolonne, hvis den
    findes)."""
    df = pd.read_excel(BytesIO(content))
    df.columns = [str(c).strip() for c in df.columns]

    rows = []
    suggested_start = None
    order = start_order
    for _, r in df.iterrows():
        holdnavn = _clean_str(r.get("Holdnavn"))
        forening = _clean_str(r.get("Forening"))
        hold = holdnavn if holdnavn else forening

        antal = pd.to_numeric(r.get("Antal deltagere"), errors="coerce")
        antal = 0 if pd.isna(antal) else int(antal)

        varighed = pd.to_numeric(r.get("Varighed"), errors="coerce")
        varighed = DEFAULT_VARIGHED["hold"] if pd.isna(varighed) else max(0, int(varighed))

        holdtype_raw = _none_if_nan(r.get("Holdtype"))
        alder_raw = _none_if_nan(r.get("Alder"))

        row_type = classify_type(hold)
        if row_type in TYPE_LABELS and not hold:
            # Kun de kendte, navngivne typer (pause/fane osv.) får en
            # synlig standard-label. "andet" er den tvetydige gruppe (tom
            # eller ugenkendt tekst) og skal forblive tomt — ellers vil en
            # senere genklassificering ud fra label-teksten "Andet" fejlagtigt
            # tolke den som et rigtigt holdnavn og gøre den til et "hold".
            hold = TYPE_LABELS[row_type]

        if suggested_start is None:
            tid = _clean_str(r.get("Tid"))
            if tid:
                try:
                    t = pd.to_datetime(tid, errors="coerce")
                    if not pd.isna(t):
                        suggested_start = f"{t.hour:02d}:{t.minute:02d}"
                except Exception:
                    pass

        rows.append({
            "id": new_id(),
            "Hold": hold,
            "Type": row_type,
            "AntalPersoner": antal,
            "HoldtypeRaw": None if holdtype_raw is None else str(holdtype_raw),
            "AlderRaw": None if alder_raw is None else str(alder_raw),
            "OpvisningHal": show_hal,
            "Varighed": varighed,
            "OpvarmningMinOverride": None,
            "OpvarmningHalOverride": None,
            "OpvarmningStartOverride": None,
            "Order": order,
        })
        order += 1
    return rows, suggested_start


def new_special_row(show_hal: str, row_type: str, order: int, varighed: Optional[int] = None) -> dict:
    return {
        "id": new_id(),
        "Hold": TYPE_LABELS.get(row_type, "Andet"),
        "Type": row_type,
        "AntalPersoner": 0,
        "HoldtypeRaw": None,
        "AlderRaw": None,
        "OpvisningHal": show_hal,
        "Varighed": varighed if varighed is not None else DEFAULT_VARIGHED.get(row_type, 10),
        "OpvarmningMinOverride": None,
        "OpvarmningHalOverride": None,
        "OpvarmningStartOverride": None,
        "Order": order,
    }


def build_dataframe(raw_rows: List[dict], show_halls: List[dict]) -> pd.DataFrame:
    columns = [
        "id", "Hold", "Type", "AntalPersoner", "Holdtype", "ErBarn",
        "OpvisningHal", "Varighed", "OpvisningStart", "OpvarmningMinOverride",
        "OpvarmningHalOverride", "OpvarmningStartOverride", "Order", "_ignored",
    ]
    if not raw_rows:
        return pd.DataFrame(columns=columns)

    df = pd.DataFrame(raw_rows)
    if "OpvarmningHalOverride" not in df.columns:
        df["OpvarmningHalOverride"] = None
    if "OpvarmningStartOverride" not in df.columns:
        df["OpvarmningStartOverride"] = None

    df["Holdtype"] = df["HoldtypeRaw"].apply(read_holdtype)

    eft_mask = (
        (df["Holdtype"] == "ukendt") & (df["Type"] == "hold") &
        df["Hold"].fillna("").str.contains("efterskole|akademiet", case=False, na=False)
    )
    df.loc[eft_mask, "Holdtype"] = "efterskole"

    dgi_mask = (
        (df["Holdtype"] == "ukendt") & (df["Type"] == "hold") &
        df["Hold"].fillna("").str.contains("DGI", na=False)
    )
    df.loc[dgi_mask, "Holdtype"] = "dgi"

    def resolve_er_barn(row) -> bool:
        explicit = read_er_barn(row["AlderRaw"])
        if explicit is not None:
            return explicit
        return auto_er_barn(row["Hold"])

    df["ErBarn"] = df.apply(resolve_er_barn, axis=1)
    df.loc[df["Holdtype"] == "efterskole", "ErBarn"] = False

    df["Varighed"] = pd.to_numeric(df["Varighed"], errors="coerce").fillna(10).astype(int).clip(lower=0)
    df["Order"] = pd.to_numeric(df["Order"], errors="coerce").fillna(0).astype(int)

    # Opvisningstid beregnes ved at kaskadere varigheder pr. opvisningshal,
    # startende fra hallens startklokkeslæt, i den rækkefølge (Order)
    # brugeren har sat.
    start_map = {h["name"]: parse_clock(h.get("startTime"), (9, 0)) for h in show_halls}
    df["OpvisningStart"] = pd.NaT
    df["OpvisningStart"] = df["OpvisningStart"].astype(object)
    for hal_name, group in df.groupby("OpvisningHal", sort=False):
        t = start_map.get(hal_name, datetime(2000, 1, 1, 9, 0))
        for idx in group.sort_values("Order").index:
            df.at[idx, "OpvisningStart"] = t
            t = t + timedelta(minutes=int(df.at[idx, "Varighed"]))

    # Kun hold der kommer fra Excel-import kan have opvarmning. Pause,
    # faneindmarch, faneudmarch og dørene åbner oprettes manuelt af
    # brugeren og har aldrig opvarmning — ingen undtagelser.
    df["_ignored"] = df["Type"] != "hold"

    return df[columns]
