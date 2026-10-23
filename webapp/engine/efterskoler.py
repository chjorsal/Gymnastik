"""Efterskolelisten (fx "EFTERSKOLER pr. 23.10.26.xlsx", arket "Deltagerdata").

Én række pr. efterskole med navn, antal og et 1-tal i kolonner som
"Hammel - lørdag 6. marts 2027 Før kl. 13.00". Kun navn, antal, dag, ønske
(før/efter kl. 13) og kommentar læses. Lærere, kontaktperson, e-mail, mobil og
alt andet springes over — og arket "Brevflet" med tilmeldingsdata læses aldrig.
"""

import re
from io import BytesIO
from typing import List, Optional

import pandas as pd

from .values import clean_str

PLACEHOLDER = re.compile(r"^\s*efterskole\s*\d+\s*$", re.IGNORECASE)   # "EFTERSKOLE 3" i programmet
_SIDE = re.compile(r"\b(før|efter)\s+kl\.?", re.IGNORECASE)
_COMMENT_WORDS = ("kommentar", "bemærk", "opvisninger i andre")
SHEET = "Deltagerdata"


def is_placeholder(name) -> bool:
    return bool(PLACEHOLDER.match(clean_str(name)))


def _one_line(value) -> str:
    return " ".join(clean_str(value).split())


def _find_header(df: pd.DataFrame) -> Optional[int]:
    for i in range(min(len(df), 15)):
        if any(_one_line(v).lower() == "efterskole" for v in df.iloc[i]):
            return i
    return None


def parse_efterskole_list(content: bytes) -> Optional[dict]:
    """{"days": [...], "schools": [{"name", "antal", "comment", "slots": {dag: "før"|"efter"|"begge"}}]}
    eller None, hvis filen ikke ligner en efterskoleliste."""
    sheets = pd.read_excel(BytesIO(content), sheet_name=None, header=None)
    order = [SHEET] + [s for s in sheets if s != SHEET] if SHEET in sheets else list(sheets)
    for sheet in order:
        df = sheets[sheet]
        h = _find_header(df)
        if h is None:
            continue
        headers = [_one_line(v) for v in df.iloc[h]]
        low = [x.lower() for x in headers]
        name_col = low.index("efterskole")
        antal_col = next((i for i, x in enumerate(low) if x == "antal"), None)
        slot_cols, days = {}, []
        for i, text in enumerate(headers):
            m = _SIDE.search(text)
            if m:
                day = text[:m.start()].strip(" -–\n")
                slot_cols[i] = (day, m.group(1).lower())
                if day not in days:
                    days.append(day)
        comment_cols = [i for i, x in enumerate(low) if any(w in x for w in _COMMENT_WORDS)]
        if not slot_cols:
            continue
        schools = []
        for _, row in df.iloc[h + 1:].iterrows():
            name = _one_line(row.iloc[name_col])
            if not name:
                continue   # fx summeringsrækken nederst
            slots = {}
            for i, (day, side) in slot_cols.items():
                if clean_str(row.iloc[i]):
                    slots[day] = "begge" if slots.get(day) not in (None, side) else side
            antal = pd.to_numeric(row.iloc[antal_col], errors="coerce") if antal_col is not None else None
            comment = " ".join(_one_line(row.iloc[i]) for i in comment_cols if _one_line(row.iloc[i]))
            schools.append({"name": name, "antal": None if antal is None or pd.isna(antal) else int(antal),
                            "comment": comment or None, "slots": slots})
        return {"days": days, "schools": schools}
    return None


def schools_for_day(efterskoler: Optional[dict]) -> List[dict]:
    """Efterskolerne for den valgte dag med deres ønske: "før", "efter" eller
    None (både før og efter kl. 13 er i orden)."""
    if not efterskoler or not efterskoler.get("day"):
        return []
    day = efterskoler["day"]
    out = []
    for s in efterskoler["schools"]:
        side = s["slots"].get(day)
        if side:
            out.append({"name": s["name"], "antal": s["antal"], "comment": s["comment"],
                        "wish": None if side == "begge" else side})
    return out
