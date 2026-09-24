"""
Opvarmningsplan fra kommandolinjen.

Bruger den samme beregningsmotor som hjemmesiden (webapp/engine), så
reglerne kun findes ét sted.

Brug:
    python lav_opvarmning_final.py fil1.xlsx fil2.xlsx ...

Hver Excel-fil bliver sin egen opvisningshal (fx "Arena" fra filnavnet), og
hallen starter på klokkeslættet i filens første 'Tid'-celle. Resultatet
gemmes som 'opvisning_med_opvarmning.xlsx' i den mappe, scriptet køres fra.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "webapp"))

import engine  # noqa: E402

OPVARMNINGS_HALLER = ["Hal 3 A", "Hal 3 B", "Hal 4"]
PRIORITET_HAL = "Hal 4"
OUTPUT_FILE = "opvisning_med_opvarmning.xlsx"


def build_plan(paths):
    raw_rows, show_halls = [], []
    for path in map(Path, paths):
        hal_navn = engine.clean_hal_name(path.stem)
        rows, start = engine.load_excel_bytes(path.name, path.read_bytes(), hal_navn, 0)
        show_halls.append({"name": hal_navn, "startTime": start or "09:00"})
        raw_rows.extend(rows)
    df = engine.build_dataframe(raw_rows, show_halls)
    return engine.compute_plan(df, OPVARMNINGS_HALLER, PRIORITET_HAL), [h["name"] for h in show_halls]


def main(paths):
    plan, show_hall_names = build_plan(paths)
    Path(OUTPUT_FILE).write_bytes(engine.build_workbook(plan, show_hall_names).getvalue())

    counts = plan["Status"].value_counts()
    print(f"Færdig! Filen '{OUTPUT_FILE}' er oprettet.")
    print(f"  Placeret: {counts.get('OK', 0)}   Kan ikke planlægges: {counts.get('KAN IKKE PLANLÆGGES', 0)}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Brug: python lav_opvarmning_final.py fil1.xlsx fil2.xlsx fil3.xlsx ...")
        sys.exit(1)
    main(sys.argv[1:])
