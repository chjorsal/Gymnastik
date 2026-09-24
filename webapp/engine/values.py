"""Små, robuste konverteringer af værdier (NaN/None/tekst/klokkeslæt)."""

import uuid
from datetime import datetime
from typing import Optional

import pandas as pd


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def override_int(value) -> Optional[int]:
    """Robust konvertering: None/""/NaN -> None. (En kolonne der mest
    indeholder None kan blive float64 med NaN i stedet for None, når en
    DataFrame bygges fra en liste af dicts.)"""
    if value is None or value == "":
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def override_str(value) -> Optional[str]:
    """Robust konvertering af en tekst-override: None/""/NaN -> None."""
    if value is None or value == "":
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    return str(value)


def parse_clock(value, fallback_hm=(9, 0)) -> datetime:
    """Parser et 'HH:MM'-klokkeslæt til en datetime samme dag (2000-01-01)."""
    if value:
        try:
            t = pd.to_datetime(str(value), errors="coerce")
            if not pd.isna(t):
                return datetime(2000, 1, 1, t.hour, t.minute)
        except Exception:
            pass
    return datetime(2000, 1, 1, fallback_hm[0], fallback_hm[1])


def _none_if_nan(value):
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    return value


def _clean_str(value) -> str:
    value = _none_if_nan(value)
    return "" if value is None else str(value).strip()


def fmt_time(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return value.strftime("%H:%M")
