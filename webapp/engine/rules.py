"""Regler for hold: type, opvarmningstid, gangtid og prioritet."""

import re

from .config import GANG_MIN, GYLDIGE_HOLDTYPER, OPVARMNING_TIDER, TYPE_KEYWORDS
from .values import clean_str


def classify_type(hold_text) -> str:
    s = clean_str(hold_text).lower()   # tåler også tomme celler (NaN) og tal
    if not s or s in ("nan", "none"):
        return "andet"
    for pattern, t in TYPE_KEYWORDS:
        if re.search(pattern, s):
            return t
    return "hold"


def is_team_by_forening(hold, forening) -> bool:
    """Et hold med en forening, der ikke bare gentager navnet, er altid et
    hold — også når navnet indeholder et ord som "Opvisning" ("Opvisning &
    TeamGym" fra HI Skanderborg). Programpunkter har ingen forening eller
    samme tekst i begge kolonner ("Pause" / "Pause")."""
    h, f = clean_str(hold).lower(), clean_str(forening).lower()
    return bool(h and f and h != f)


def read_holdtype(value) -> str:
    val = clean_str(value).lower()
    if val == "dans":
        val = "rytme"
    if val == "akademiet":
        val = "efterskole"
    return val if val in GYLDIGE_HOLDTYPER else "ukendt"


def opvarmning_minutter(holdtype: str) -> int:
    return OPVARMNING_TIDER.get(holdtype, OPVARMNING_TIDER["ukendt"])


def gang_tid() -> int:
    return GANG_MIN


def priority_rank(holdtype: str) -> int:
    """Efterskoler placeres først; derefter alle andre efter opvisningstid."""
    return 0 if holdtype == "efterskole" else 5
