"""Faste standardværdier og nøgleordslister for planlægningen.

Alle tal kan stadig overstyres pr. hold i brugerfladen."""

SKIFTE_MIN = 0
SKIFTE_I_SLOTTET_MIN = 0
STEP_MIN = 1
MAX_EARLY_MIN = 10
# Et hold må højst være færdigt med opvarmning 25 min før gangtiden, dvs.
# 30 min før det skal på gulvet. Først prøves 0-10 min, så op til 25.
MAX_EARLY_TOTAL_MIN = 25
# Og opvarmningen må højst STARTE 45 min før holdet skal på gulvet. Med 5 min
# gang kan en opvarmning derfor højst vare 40 min.
MAX_START_BEFORE_MIN = 45

# Standard opvarmningstider i minutter (bruges når et hold ikke har fået en
# manuel opvarmningstid sat i UI'en)
OPVARMNING_TIDER = {
    "spring": 15,
    "rytme": 15,
    "mix": 15,
    "efterskole": 30,
    "dgi": 30,
    "ukendt": 15,
}

# Gangtid fra opvarmningshal til opvisningshal — ens for alle hold, fordi
# Excel-filerne ikke siger, om et hold er børn eller voksne.
GANG_MIN = 5

GYLDIGE_HOLDTYPER = {"spring", "rytme", "dans", "mix", "efterskole", "akademiet", "dgi"}

DEFAULT_VARIGHED = {
    "hold": 10,
    "pause": 10,
    "faneindmarch": 10,
    "faneudmarch": 10,
    "dorene_aabner": 10,
    "andet": 5,
}

TYPE_LABELS = {
    "pause": "Pause",
    "faneindmarch": "Faneindmarch",
    "faneudmarch": "Faneudmarch",
    "dorene_aabner": "Dørene åbner",
}

# Ikke-hold-punkter (pause, faneindmarch, faneudmarch, dørene åbner) oprettes
# manuelt af brugeren via knapperne i værktøjslinjen — de kommer ikke fra
# Excel og skal aldrig have en opvarmningstid. Kun hold der importeres fra
# Excel kan have opvarmning. Nøgleordslisten er kun en hjælp til at undgå at
# et rent tekst-punkt i selve Excel-filen (fx en "Pause"-linje) fejlagtigt
# behandles som et hold.
TYPE_KEYWORDS = [
    ("faneindmarch", "faneindmarch"),
    ("faneudmarch", "faneudmarch"),
    ("pause", "pause"),
    ("dørene", "dorene_aabner"),
    ("døren", "dorene_aabner"),
    ("velkommen", "andet"),
    ("velkomst", "andet"),
    ("indmarch", "andet"),
    ("udmarch", "andet"),
    ("ikke hold", "andet"),
    ("tak for", "andet"),          # "Tak for i dag"
    ("afslutning", "andet"),
    ("præmie", "andet"),
    # kun det selvstændige ord — ikke holdnavne som "Opvisningspiger"
    (r"\bopvisning\b", "andet"),
]

