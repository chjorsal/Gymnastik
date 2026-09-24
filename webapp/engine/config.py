"""Faste standardværdier og nøgleordslister for planlægningen.

Alle tal kan stadig overstyres pr. hold i brugerfladen."""

BUFFER_MIN = 0
SKIFTE_MIN = 0
SKIFTE_I_SLOTTET_MIN = 0
STEP_MIN = 1
MAX_EARLY_MIN = 10

# Standard opvarmningstider i minutter (bruges når et hold ikke har fået en
# manuel opvarmningstid sat i UI'en)
OPVARMNING_TIDER = {
    #              barn  voksen
    "spring":     (15,   15),
    "rytme":      (15,   15),
    "mix":        (15,   15),
    "efterskole": (30,   30),
    "dgi":        (30,   30),
    "ukendt":     (15,   15),
}

GANG_BARN = 10
GANG_VOKSEN = 5
GANG_EFTERSKOLE = 10
FLEX_BARN = 15

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
    # kun det selvstændige ord — ikke holdnavne som "Opvisningspiger"
    (r"\bopvisning\b", "andet"),
]


VOKSEN_TOKENS = [
    "damer", "kvinder", "herrer", "mænd", "30+", "senior",
    "øvede", "fusion", "impuls", "zenit", "vikuvika",
    "rephold", "afterrep", "ynglingehold", "move-mænd",
    "bydrengene", "powermix", "skødstrup mix", "r3vive",
    "rebounce", "opvisningspiger", "højbjerg øvede",
    "show-mix", "sprød", "brobyholdet",
]
BARN_TOKENS = [
    "junior", "mini", "børne", "powerkids",
    "hoptimist", "tigerspringerne", "supergirls",
    "tons og tøser", "mixspring", "springmix",
    "teamspring", "turbo", "tornado",
]
