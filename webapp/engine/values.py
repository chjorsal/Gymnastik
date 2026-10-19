"""Små, robuste konverteringer af værdier (NaN/None/tekst/klokkeslæt)."""

import uuid
from datetime import datetime
from typing import Optional, Tuple

import pandas as pd

DAY_START = datetime(2000, 1, 1)   # alle tider lægges på samme (tænkte) dag


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def is_missing(value) -> bool:
    """None, NaN eller NaT — det pandas giver for en tom celle. (En kolonne der
    mest indeholder None kan blive float64 med NaN i stedet for None, når en
    DataFrame bygges fra en liste af dicts.)"""
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):   # fx en liste — ikke en enkelt værdi
        return False


def none_if_missing(value):
    return None if is_missing(value) else value


def clean_str(value) -> str:
    return "" if is_missing(value) else str(value).strip()


def override_int(value) -> Optional[int]:
    """Robust konvertering af et tal sat af brugeren: tomt/NaN/tekst -> None."""
    if is_missing(value) or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def override_str(value) -> Optional[str]:
    """Robust konvertering af en tekst sat af brugeren: tomt/NaN -> None."""
    if is_missing(value) or value == "":
        return None
    return str(value)


def to_clock(value) -> Optional[Tuple[int, int]]:
    """(time, minut) fra fx '9:30', '09:30:00' eller et klokkeslæt fra Excel —
    None hvis værdien ikke er et klokkeslæt."""
    text = clean_str(value)
    if not text:
        return None
    try:
        t = pd.to_datetime(text, errors="coerce")
    except Exception:
        return None
    return None if pd.isna(t) else (t.hour, t.minute)


def parse_clock(value, fallback_hm=(9, 0)) -> datetime:
    """Parser et 'HH:MM'-klokkeslæt til en datetime samme dag (2000-01-01)."""
    hour, minute = to_clock(value) or fallback_hm
    return DAY_START.replace(hour=hour, minute=minute)


def fmt_time(value) -> str:
    return "" if is_missing(value) else value.strftime("%H:%M")


def minutes_from_day_start(value) -> Optional[int]:
    """Minutter fra dagens start (2000-01-01 00:00). Tider efter midnat giver
    mere end 1440, så de aldrig forveksles med tidlig morgen. None hvis tom."""
    if is_missing(value):
        return None
    return int((value - DAY_START).total_seconds() // 60)
