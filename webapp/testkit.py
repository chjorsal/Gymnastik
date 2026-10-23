"""Fælles hjælpere til testene (test_*.py)."""

import os
import socket
import subprocess
import sys
import time
import urllib.request
from io import BytesIO
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
# Windows-konsollen kan ikke altid vise fx ✕ — erstat tegnet i stedet for at stoppe testen.
sys.stdout.reconfigure(errors="replace")
PASS, FAIL = [], []
VERBOSE = False   # True: skriv også de tjek, der består (bruges af browsertesten)


def check(name, condition, detail=""):
    if condition:
        PASS.append(name)
    else:
        FAIL.append((name, detail))
    if VERBOSE or not condition:
        print(("OK   " if condition else "FEJL ") + name + (f"  ({detail})" if detail and not condition else ""))


def summary() -> bool:
    """Skriver resultatet og returnerer True, hvis alt bestod."""
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return not FAIL


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(url, timeout=60):
    """Venter, til url svarer (fx en server, der lige er startet)."""
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(url)
            return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError(f"{url} svarede ikke")


def start_server(tmp):
    """Starter app.py på en ledig port med state.json i mappen tmp — rører
    aldrig den rigtige state.json. Returnerer (proces, adresse med / til sidst)."""
    port = free_port()
    env = dict(os.environ, STATE_FILE=str(Path(tmp) / "state.json"), PORT=str(port))
    proc = subprocess.Popen([sys.executable, "app.py"], cwd=HERE, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}/"
    wait_for(url + "api/state")
    return proc, url


# Personoplysninger i den falske efterskoleliste. De må aldrig nå planen.
SECRETS = ("Hemmelig Lærer", "Kontakt Person", "hemmelig@example.dk", "12345678", "Brevflet-data")


def efterskole_bytes() -> bytes:
    """En lille efterskoleliste som DGI's: arket "Deltagerdata" med to dage og
    et ark "Brevflet" med tilmeldingsdata, der aldrig må læses."""
    sat = "Hammel - lørdag 6. marts 2027 "
    sun = "Hammel - søndag 7. marts 2027 "
    header = ["Efterskole", "ANTAL", "LÆRERE", "KONTAKTPERSON", "EMAIL", "MOBIL",
              sat + "Før kl. 13.00", sat + "Efter kl. 13.00", sun + "Før kl. 13.00", sun + "Efter kl. 13.00",
              "Kommentar"]
    secret = ["Hemmelig Lærer", "Kontakt Person", "hemmelig@example.dk", "12345678"]
    rows = [
        ["DGI Efterskoler 2027", None, None, None, None, None, None, None, None, None, None],
        header,
        ["Alfa Efterskole", 40, *secret, 1, None, None, None, "Gengangere med Beta"],
        ["Beta Efterskole", 55, *secret, None, 1, None, 1, None],
        ["Gamma Efterskole", 30, *secret, 1, 1, None, None, None],
        ["Delta Efterskole", 25, *secret, None, None, 1, None, None],
        [None, 150, None, None, None, None, 2, 2, 1, 1, None],
    ]
    buf = BytesIO()
    with pd.ExcelWriter(buf) as xw:
        pd.DataFrame(rows).to_excel(xw, sheet_name="Deltagerdata", index=False, header=False)
        pd.DataFrame([["Efterskole", "Navn", "Før kl. 13"], ["Alfa Efterskole", "Brevflet-data", 1]]).to_excel(
            xw, sheet_name="Brevflet", index=False, header=False)
    return buf.getvalue()


def excel_bytes(teams, start="09:00") -> bytes:
    """En lille Excel-fil i hukommelsen. teams: holdnavne eller
    (holdnavn, varighed); varighed er 10 min, hvis den ikke er givet. Første
    række får Tid = start."""
    teams = [t if isinstance(t, tuple) else (t, 10) for t in teams]
    df = pd.DataFrame({
        "Tid": [start] + [""] * (len(teams) - 1),
        "Varighed": [v for _, v in teams],
        "Holdnavn": [n for n, _ in teams],
        "Antal deltagere": [20] * len(teams),
        "Alder": ["voksen"] * len(teams),
    })
    buf = BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()
