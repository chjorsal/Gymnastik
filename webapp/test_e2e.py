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


def browser_only(browser, context, page, url, dialogs):
    """Det der kun gælder browserudgaven: lagring, faner og fejl ved indlæsning."""
    rows = page.evaluate("() => STATE.rows.length")
    stored = page.evaluate("() => JSON.parse(localStorage.getItem('opvarmning_plan_v1')).raw_rows.length")
    check("planen gemmes i localStorage", stored == rows, (stored, rows))

    page.reload()
    page.wait_for_selector("#overview-data:not(.hidden)", timeout=120_000)
    check("planen er der efter genindlæsning", page.evaluate("() => STATE.rows.length") == rows)

    other = context.new_page()
    other.goto(url)
    other.wait_for_selector("#overview-data:not(.hidden)", timeout=120_000)
    page.click(".rail-link[data-view=program]")
    page.click(".add-special[data-type=pause]")
    other.wait_for_function(f"() => STATE.rows.length === {rows + 1}", timeout=10_000)
    check("ændring i én fane vises i den anden", other.evaluate("() => STATE.rows.length") == rows + 1)
    other.close()
    page.wait_for_function(f"() => STATE.rows.length === {rows + 1}")  # egen gemning færdig

    page.evaluate("() => localStorage.setItem('opvarmning_plan_v1', '{ødelagt')")
    page.reload()
    page.wait_for_selector("#onboarding:not(.hidden)", timeout=120_000)
    broken = page.evaluate("() => Object.keys(localStorage).filter(k => k.startsWith('opvarmning_plan_broken_'))")
    check("ulæselig plan giver tom plan og gemmes til side", len(broken) == 1, broken)

    blocked = browser.new_context()
    blocked.add_init_script("Storage.prototype.setItem = function () { throw new Error('QuotaExceededError'); };")
    bpage = blocked.new_page()
    bdialogs = []
    bpage.on("dialog", lambda d: (bdialogs.append(d.message), d.accept()))
    bpage.goto(url)
    bpage.wait_for_selector("#onboarding:not(.hidden)", timeout=120_000)
    bpage.fill("#onb-warmup-form input", "Varm 1")
    bpage.press("#onb-warmup-form input", "Enter")
    bpage.wait_for_function("() => document.querySelectorAll('#onb-warmup-list li').length === 1")
    bpage.fill("#onb-warmup-form input", "Varm 2")
    bpage.press("#onb-warmup-form input", "Enter")
    bpage.wait_for_function("() => document.querySelectorAll('#onb-warmup-list li').length === 2")
    check("uden localStorage virker appen og siger det én gang",
          len([d for d in bdialogs if "Gem plan" in d]) == 1, bdialogs)
    blocked.close()

    offline = browser.new_context()
    offline.route("**/pyodide.asm.wasm", lambda r: r.abort())
    opage = offline.new_page()
    opage.goto(url)
    opage.wait_for_selector("#boot-text:has-text('Kunne ikke indlæse planlæggeren')", timeout=60_000)
    check("Pyodide der ikke kan hentes giver dansk fejl", True)
    offline.close()

    # ---------- data-sektionen ----------
    page.goto(url)
    page.wait_for_selector("#boot.hidden", state="attached", timeout=120_000)
    page.click("#btn-halls")
    page.wait_for_selector("#halls-panel.show")
    check("Om data-teksten vises",
          "Dine data gemmes kun i denne browser. De sendes ikke til nogen server. Skriv ikke personnavne i Excel-filen."
          in page.inner_text("#data-section"))
    page.fill("#warmup-hall-form input", "Varm X")
    page.press("#warmup-hall-form input", "Enter")
    page.wait_for_function("() => STATE.warmupHalls.includes('Varm X')")

    with page.expect_download() as dl:
        page.click("#btn-save-plan")
    check("Gem plan henter opvarmningsplan.json", dl.value.suggested_filename == "opvarmningsplan.json")
    saved = Path(dl.value.path())

    bad = saved.with_name("forkert.json")
    bad.write_text('{"raw_rows": "nej"}', encoding="utf-8")
    before = page.evaluate("() => JSON.stringify(STATE.warmupHalls)")
    page.set_input_files("#plan-file-input", str(bad))
    page.wait_for_timeout(500)
    check("Åbn plan med ugyldig fil giver besked og ændrer intet",
          any("ikke en gyldig plan" in d for d in dialogs) and page.evaluate("() => JSON.stringify(STATE.warmupHalls)") == before)

    page.click("#btn-clear-data")   # bekræftelsen accepteres af dialog-handleren
    page.wait_for_selector("#onboarding:not(.hidden)", timeout=120_000)
    left = page.evaluate("() => Object.keys(localStorage).filter(k => k.startsWith('opvarmning_'))")
    check("Slet alle data fjerner alt og viser 'Kom i gang'", left == [] and page.evaluate("() => STATE.warmupHalls.length") == 0, left)

    page.click("#btn-halls")
    page.wait_for_selector("#halls-panel.show")
    page.set_input_files("#plan-file-input", str(saved))
    page.wait_for_function("() => STATE.warmupHalls.includes('Varm X')", timeout=10_000)
    check("Åbn plan indlæser en gemt plan", True)


def run(mode):
    tmp = tempfile.mkdtemp()
    xlsx = excel_file(tmp)
    procs = []
    try:
        if mode == "server":
            proc, url = start_server(tmp)
            procs.append(proc)
        else:
            import build_site
            root = Path(tmp) / "www"
            build_site.build(root / "Gymnastik")      # samme understi som GitHub Pages
            port = free_port()
            procs.append(subprocess.Popen(
                [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", str(root)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            url = f"http://127.0.0.1:{port}/Gymnastik/"
            wait_for(url)

        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            context = browser.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True)
            page = context.new_page()
            dialogs, errors = [], []
            page.on("dialog", lambda d: (dialogs.append(d.message), d.accept()))
            page.on("pageerror", lambda e: errors.append(str(e)))
            common_flow(page, url, xlsx, dialogs, errors)
            if mode == "server":
                check("data-sektionen er skjult i serverudgaven", page.is_hidden("#data-section"))
            check("ingen JavaScript-fejl", not errors, errors)
            if mode == "browser":
                browser_only(browser, context, page, url, dialogs)
            browser.close()
    finally:
        for proc in procs:
            proc.terminate()
            proc.wait(timeout=10)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return not FAIL


if __name__ == "__main__":
    sys.exit(0 if run(sys.argv[1] if len(sys.argv) > 1 else "server") else 1)
