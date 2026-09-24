"""Regler for hold: type, alder, opvarmningstid, gangtid og prioritet."""

import re
from typing import Optional

import pandas as pd

from .config import (
    BARN_TOKENS,
    GANG_BARN,
    GANG_EFTERSKOLE,
    GANG_VOKSEN,
    GYLDIGE_HOLDTYPER,
    OPVARMNING_TIDER,
    TYPE_KEYWORDS,
    VOKSEN_TOKENS,
)


def classify_type(hold_text: str) -> str:
    s = (hold_text or "").strip().lower()
    if not s or s in ("nan", "none"):
        return "andet"
    for pattern, t in TYPE_KEYWORDS:
        if re.search(pattern, s):
            return t
    return "hold"


def read_holdtype(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "ukendt"
    val = str(value).strip().lower()
    if val == "":
        return "ukendt"
    if val == "dans":
        val = "rytme"
    if val == "akademiet":
        val = "efterskole"
    return val if val in GYLDIGE_HOLDTYPER else "ukendt"


def read_er_barn(value) -> Optional[bool]:
    """None betyder 'ikke eksplicit sat' -> auto-detect fra holdnavn."""
    if value is None or (isinstance(value, float) and pd.isna(value)) or str(value).strip() == "":
        return None
    val = str(value).strip().lower()
    if val in ("false", "0", "voksen", "senior", "adult"):
        return False
    if val in ("true", "1", "barn", "børn", "child", "junior"):
        return True
    return None


def auto_er_barn(holdnavn: str) -> bool:
    name = (holdnavn or "").lower()

    if any(tok in name for tok in VOKSEN_TOKENS):
        return False

    if re.search(r'\d+\s*[.\-/]?\s*\d*\s*(kl|klasse)', name):
        return True
    if re.search(r'kl\.', name):
        return True

    age_range = re.search(r'(\d+)\s*[-–]\s*(\d+)\s*år', name)
    if age_range and int(age_range.group(2)) <= 16:
        return True

    age_single = re.search(r'(\d+)\s*år(?!\+)', name)
    if age_single and int(age_single.group(1)) <= 16:
        return True

    if any(tok in name for tok in BARN_TOKENS):
        return True

    return False


def opvarmning_minutter(holdtype: str, er_barn: bool) -> int:
    if holdtype == "efterskole":
        return 30
    tider = OPVARMNING_TIDER.get(holdtype, OPVARMNING_TIDER["ukendt"])
    return tider[0] if er_barn else tider[1]


def gang_tid(holdtype: str, er_barn: bool) -> int:
    if holdtype == "efterskole":
        return GANG_EFTERSKOLE
    return GANG_BARN if er_barn else GANG_VOKSEN


def priority_rank(holdtype: str, antal: int, er_barn: bool) -> int:
    if holdtype == "efterskole":
        return 0
    if er_barn:
        return 10
    if antal > 40:
        return 1
    return 5
