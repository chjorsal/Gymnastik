"""
Opvarmningsplanlægger — beregningsmotor.

Bruges af både hjemmesiden (app.py) og kommandolinje-scriptet
(lav_opvarmning_final.py), så der kun findes én udgave af reglerne.

Moduler:
    config     faste standardværdier og nøgleordslister
    rules      holdtype, alder, opvarmnings-/gangtid og prioritet
    values     robuste konverteringer (NaN, klokkeslæt, id'er)
    importer   Excel -> rå rækker -> DataFrame med opvisningstider
    placement  placeringsalgoritmen for opvarmning
    serialize  plan -> JSON til frontenden
    export     plan -> Excel-fil

Opvisningstiden for hvert programpunkt beregnes ud fra hallens
startklokkeslæt + varigheden af alle forudgående punkter. Pause,
faneindmarch og faneudmarch er programpunkter uden opvarmning. Hold der
ikke kan placeres, flyttes manuelt af brugeren.
"""

from .config import *  # noqa: F401,F403
from .export import build_workbook
from .importer import build_dataframe, clean_hal_name, load_excel_bytes, new_special_row
from .placement import Booking, compute_plan, overlaps, try_place, try_place_fixed
from .rules import (
    auto_er_barn,
    classify_type,
    gang_tid,
    opvarmning_minutter,
    priority_rank,
    read_er_barn,
    read_holdtype,
)
from .serialize import problem_message, to_row_dicts, to_schedule
from .values import fmt_time, new_id, override_int, override_str, parse_clock
