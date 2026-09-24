"""
Browsertest med Playwright og Microsoft Edge.

  python test_e2e.py server    tester python app.py (egen server, midlertidig state)
  python test_e2e.py browser   tester den byggede browserudgave (Task 6)

Kræver: pip install playwright   (bruger den installerede Edge; ingen download)
"""
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from io import BytesIO
from pathlib import Path

import pandas as pd
from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
PASS, FAIL = [], []


def check(name, condition, detail=""):
    (PASS.append(name) if condition else FAIL.append((name, detail)))
    print(("OK   " if condition else "FEJL ") + name + (f"  ({detail})" if detail and not condition else ""))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(url, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(url)
            return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError(f"{url} svarede ikke")


def excel_file(tmp):
    df = pd.DataFrame({
        "Tid": ["09:00"] + [""] * 5,
        "Varighed": [10] * 6,
        "Holdnavn": [f"Hold {i}" for i in range(1, 7)],
        "Antal deltagere": [20] * 6,
        "Alder": ["voksen"] * 6,
    })
    path = Path(tmp) / "program.xlsx"
    df.to_excel(path, index=False)
    return path


def start_server(tmp):
    port = free_port()
    env = dict(os.environ, STATE_FILE=str(Path(tmp) / "state.json"), PORT=str(port))
    proc = subprocess.Popen([sys.executable, "app.py"], cwd=HERE, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}/"
    wait_for(url + "api/state")
    return proc, url


def common_flow(page, url, xlsx, dialogs, errors):
    """Hele forløbet fra tom plan til eksport — ens for begge udgaver."""
    page.goto(url)
    page.wait_for_selector("#onboarding:not(.hidden)", timeout=120_000)
    check("tom plan viser 'Kom i gang'", page.inner_text("#page-title") == "Kom i gang")
    check("Hent Excel-plan er skjult uden hold", page.is_hidden("#btn-export"))

    for i, name in enumerate(["Varm 1", "Varm 2"], start=1):
        page.fill("#onb-warmup-form input", name)
        page.press("#onb-warmup-form input", "Enter")
        page.wait_for_function(f"document.querySelectorAll('#onb-warmup-list li').length === {i}")
    for i, (name, start) in enumerate([("Sal A", "9.15"), ("Sal B", "10:00")], start=1):
        page.fill("#onb-show-form input >> nth=0", name)
        page.fill("#onb-show-form input >> nth=1", start)
        page.click("#onb-show-form button")
        page.wait_for_function(f"document.querySelectorAll('#onb-show-list li').length === {i}")
    check("haller oprettet på startsiden", "start 09:15" in page.locator("#onb-show-list li").first.inner_text())

    page.set_input_files("#file-input", str(xlsx))
    page.wait_for_selector("#overview-data:not(.hidden)")
    check("Excel lægges i den første hal",
          page.locator(".hall-row-name").all_inner_texts() == ["Sal A", "Sal B"])
    check("tidslinjen har blokke", page.locator(".tl-block").count() >= 6)

    page.locator(".hall-row").first.click()
    team_row = page.locator("#table-body tr:not(.row-special)").first
    team_row.locator("select").select_option("Sal B")
    page.wait_for_timeout(500)
    moved = page.evaluate("() => STATE.rows.find(r => r.hold === 'Hold 1')")
    check("flyttet hold får ny tid og opvarmning",
          moved["opvisningHal"] == "Sal B" and moved["opvisningTid"] == "10:00" and moved["status"] == "OK", moved)

    page.fill("#hal-start-time", "abc")
    page.locator("#hal-start-time").blur()
    page.wait_for_timeout(500)
    check("ugyldig starttid giver dansk besked", any("gyldigt klokkeslæt" in d for d in dialogs), dialogs)

    with page.expect_file_chooser() as fc:
        page.click("#btn-upload")
    garbage = Path(xlsx).with_name("skrald.xlsx")
    garbage.write_bytes(b"ikke excel")
    count_before = page.evaluate("() => STATE.rows.length")
    fc.value.set_files(str(garbage))
    page.wait_for_timeout(1000)
    check("ugyldig Excel giver besked og ændrer intet",
          any("skrald.xlsx" in d for d in dialogs) and page.evaluate("() => STATE.rows.length") == count_before)

    with page.expect_download() as dl:
        page.click("#btn-export")
    check("eksport henter opvisning_med_opvarmning.xlsx",
          dl.value.suggested_filename == "opvisning_med_opvarmning.xlsx")
    data = Path(dl.value.path()).read_bytes()
    sheets = list(pd.read_excel(BytesIO(data), sheet_name=None))
    check("eksport har ét ark pr. opvisningshal først", sheets[:2] == ["Opvisning Sal A", "Opvisning Sal B"], sheets)


def run(mode):
    tmp = tempfile.mkdtemp()
    xlsx = excel_file(tmp)
    procs = []
    try:
        if mode == "server":
            proc, url = start_server(tmp)
            procs.append(proc)
        else:
            raise SystemExit("browser-udgaven testes fra Task 6")

        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            context = browser.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True)
            page = context.new_page()
            dialogs, errors = [], []
            page.on("dialog", lambda d: (dialogs.append(d.message), d.accept()))
            page.on("pageerror", lambda e: errors.append(str(e)))
            common_flow(page, url, xlsx, dialogs, errors)
            check("ingen JavaScript-fejl", not errors, errors)
            browser.close()
    finally:
        for proc in procs:
            proc.terminate()
            proc.wait(timeout=10)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return not FAIL


if __name__ == "__main__":
    sys.exit(0 if run(sys.argv[1] if len(sys.argv) > 1 else "server") else 1)
