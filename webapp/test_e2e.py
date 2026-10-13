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
    check("første opvarmningshal er prioritetshal fra start",
          page.evaluate("() => STATE.priorityHall") == "Varm 1"
          and "Prioritetshal" in page.locator("#onb-warmup-list li").first.inner_text())
    page.locator("#onb-warmup-list li").nth(1).locator(".star").click()
    page.wait_for_function("() => STATE.priorityHall === 'Varm 2'")
    check("stjernen gør en anden hal til prioritetshal", "Prioritetshal" in page.locator("#onb-warmup-list li").nth(1).inner_text())
    page.locator("#onb-warmup-list li").first.locator(".star").click()
    page.wait_for_function("() => STATE.priorityHall === 'Varm 1'")
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

    # tilføj et hold i hånden (tilmelding på bagkant)
    page.click(".rail-link[data-view=program]")
    page.click("#btn-add-team")
    page.wait_for_function("() => STATE.rows.some(r => r.hold === 'Sent hold')")
    sent = page.evaluate("() => STATE.rows.find(r => r.hold === 'Sent hold')")
    # (om der er plads til opvarmningen afhænger af hallerne; det testes i test_actions)
    check("Hold-knappen tilføjer et 15/15-hold, der skal varme op",
          sent["varighed"] == 15 and sent["opvarmningMinOverride"] == 15 and sent["needsWarmup"], sent)
    check("navnet på et tilføjet hold kan rettes", page.locator("#table-body input.team-name").count() == 1)

    with page.expect_download() as dl:
        page.click("#btn-export")
    check("eksport henter opvisning_med_opvarmning.xlsx",
          dl.value.suggested_filename == "opvisning_med_opvarmning.xlsx")
    data = Path(dl.value.path()).read_bytes()
    sheets = list(pd.read_excel(BytesIO(data), sheet_name=None))
    check("eksport har ét ark pr. opvisningshal først", sheets[:2] == ["Opvisning Sal A", "Opvisning Sal B"], sheets)
    exported = pd.read_excel(BytesIO(data), sheet_name=None)
    check("tilføjet hold er med i Excel", "Sent hold" in set(exported["Opvisning Sal A"]["Hold"]))

    count = page.evaluate("() => STATE.rows.length")
    page.locator("#table-body tr", has=page.locator("input.team-name")).locator(".row-delete").click()
    page.wait_for_function(f"() => STATE.rows.length === {count - 1}")
    check("hold kan slettes igen", page.evaluate("() => !STATE.rows.some(r => r.hold === 'Sent hold')"))


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


def refresh(page):
    page.evaluate("async () => { STATE = await apiGet('/api/state'); render(); }")


def api(page, method, url, body=None):
    page.evaluate("([m, u, b]) => Api.request(m, u, b)", [method, url, body])


def new_features(page, tmp, dialogs):
    """Punkt 3-7: logo, piletaster, opvarmning i Program, forslag og træk-og-slip."""
    # 7: logoet går til Oversigt
    page.click(".rail-link[data-view=program]")
    page.click("#brand-home")
    check("logoet går til Oversigt", page.inner_text("#page-title") == "Oversigt")

    # 5: Program viser, hvor og hvornår holdet varmer op
    page.click(".rail-link[data-view=program]")
    cells = page.locator("#table-body tr:not(.row-special) td.warmup-col").all_inner_texts()
    import re as _re
    check("Program viser opvarmningshal og tid for hvert hold",
          cells and all(_re.match(r"^.+ \d\d:\d\d–\d\d:\d\d$", c) or c == "Mangler plads" for c in cells), cells)
    page.click(".add-special[data-type=pause]")
    page.wait_for_selector("#table-body tr.row-special")
    special = page.locator("#table-body tr.row-special td.warmup-col").first.inner_text()
    check("specialpunkter viser — i stedet for opvarmning", special == "—", special)

    # 4: opvarmningsfeltet viser tiden, og pil op tæller fra den
    warm = page.locator("#table-body tr:not(.row-special) td.narrow-col input[type=number]").nth(1)
    check("opvarmningsfeltet viser 15 og er ikke tomt", warm.input_value() == "15", warm.input_value())
    team_id = page.locator("#table-body tr:not(.row-special)").nth(1).get_attribute("data-id")
    sel = f"#table-body tr[data-id='{team_id}'] td.narrow-col input[type=number] >> nth=1"
    page.locator(sel).focus()
    page.keyboard.press("ArrowUp")
    page.keyboard.press("ArrowUp")
    check("pil op tæller fra 15 (giver 17, ikke 2)", page.locator(sel).input_value() == "17", page.locator(sel).input_value())
    page.keyboard.press("Tab")
    page.wait_for_function(f"() => STATE.rows.find(r => r.id === '{team_id}').opvarmningMinOverride === 17")
    check("værdien gemmes, når feltet forlades", True)
    page.locator(sel).focus()
    for _ in range(2):
        page.keyboard.press("ArrowDown")
    page.keyboard.press("Tab")
    page.wait_for_function(f"() => STATE.rows.find(r => r.id === '{team_id}').opvarmningMinOverride === 15")
    check("pil ned tæller ned igen", True)

    # 6 + 3: scenarie med én opvarmningshal og et hold hvert 12. minut
    api(page, "POST", "/api/reset")
    api(page, "DELETE", "/api/halls/warmup", {"name": "Varm 2"})
    api(page, "POST", "/api/halls/show/starttime", {"name": "Sal A", "startTime": "09:00"})
    refresh(page)
    df = pd.DataFrame({"Tid": ["09:00"] + [""] * 5, "Varighed": [12] * 6, "Holdnavn": list("ABCDEF"),
                       "Antal deltagere": [20] * 6})
    path = Path(tmp) / "tolv.xlsx"
    df.to_excel(path, index=False)
    page.set_input_files("#file-input", str(path))
    page.wait_for_function("() => STATE.rows.length === 6")
    page.click(".rail-link[data-view=oversigt]")
    unplaced = page.evaluate("() => STATE.rows.filter(r => r.status !== 'OK').map(r => r.hold)")
    check("scenarie: D og F mangler plads", unplaced == ["D", "F"], unplaced)

    page.wait_for_selector("#suggestion-list .btn-primary", timeout=60_000)
    lines = page.locator("#suggestion-list li").all_inner_texts()
    check("forslag: F med 12 min i Varm 1 09:43–09:55",
          any(l.startswith("F") and "12 min" in l and "Varm 1 09:43–09:55" in l for l in lines), lines)
    check("D får besked om, at der ikke er plads selv med 10 min",
          any(l.startswith("D") and "10 min" in l and "Brug forslag" not in l for l in lines), lines)
    page.locator("#suggestion-list li", has_text="F (går på").locator(".btn-primary").click()
    page.wait_for_function("() => STATE.rows.find(r => r.hold === 'F').status === 'OK'")
    f = page.evaluate("() => STATE.rows.find(r => r.hold === 'F')")
    check("Brug forslag giver F 12 min og plads", (f["opvarmningMinOverride"], f["opvarmningStart"]) == (12, "09:43"), f)
    page.wait_for_function("() => !document.querySelector('#suggestion-list').innerText.includes('Beregner')")
    lines = page.locator("#suggestion-list li").all_inner_texts()
    check("forslagene beregnes forfra efter en ændring", len(lines) == 1 and lines[0].startswith("D"), lines)

    # 3: træk D ind i et hul på tidslinjen
    tl = page.evaluate("() => { const d = document.getElementById('timeline').dataset;"
                       " return {from: +d.from, span: +d.span, w: +d.trackW}; }")
    x_at = lambda hhmm: (int(hhmm[:2]) * 60 + int(hhmm[3:]) - tl["from"]) / tl["span"] * tl["w"] + 2
    red = page.locator(".tl-lane-problem .tl-block").first
    lane = page.locator(".tl-lane", has=page.locator(".tl-lane-name", has_text="Varm 1")).locator(".tl-track")
    before = len(dialogs)
    red.drag_to(lane, target_position={"x": x_at("08:30"), "y": 20})
    page.wait_for_timeout(800)
    d = page.evaluate("() => STATE.rows.find(r => r.hold === 'D')")
    check("træk til en optaget tid afvises med besked, D uændret",
          len(dialogs) > before and "ikke plads" in dialogs[-1] and d["status"] != "OK", dialogs[-1:])
    red = page.locator(".tl-lane-problem .tl-block").first
    red.drag_to(lane, target_position={"x": x_at("08:05"), "y": 20})
    page.wait_for_function("() => STATE.rows.find(r => r.hold === 'D').status === 'OK'")
    d = page.evaluate("() => STATE.rows.find(r => r.hold === 'D')")
    check("træk D til et hul giver opvarmning der (08:05)", (d["opvarmningHalBeregnet"], d["opvarmningStart"]) == ("Varm 1", "08:05"), d)
    check("ingen hold uden plads -> ingen forslag og ingen rød række",
          page.is_hidden("#suggestions") and page.locator(".tl-lane-problem").count() == 0)


def bulk_tests(page, dialogs):
    """Vælg flere hold og flyt eller slet dem på én gang."""
    page.click(".rail-link[data-view=program]")
    page.locator("#hal-tabs .tab", has_text="Sal A").click()
    check("bjælken er skjult, når intet er valgt", page.is_hidden("#bulk-bar"))
    boxes = page.locator("#table-body td.select-col input")
    names = lambda hal: page.evaluate(f"() => STATE.rows.filter(r => r.opvisningHal === '{hal}')"
                                      ".sort((a, b) => a.order - b.order).map(r => r.hold)")
    check("scenarie: Sal A har A-F", names("Sal A") == list("ABCDEF"), names("Sal A"))

    boxes.nth(1).click()
    boxes.nth(3).click(modifiers=["Shift"])
    check("Shift-klik vælger B til D", page.inner_text("#bulk-count") == "3 valgt", page.inner_text("#bulk-count"))
    opts = page.locator("#bulk-target option").all_inner_texts()
    check("man kan vælge mellem de andre opvisningshaller", opts == ["Sal B"], opts)

    page.set_viewport_size({"width": 1440, "height": 420})
    page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(200)
    top = page.evaluate("() => document.getElementById('bulk-bar').getBoundingClientRect().top")
    check("bjælken følger med, når man scroller ned", 0 <= top <= 40, top)
    page.set_viewport_size({"width": 1440, "height": 900})

    page.click("#bulk-move")
    page.wait_for_function("() => STATE.rows.filter(r => r.opvisningHal === 'Sal B').length === 3")
    check("de valgte flyttes i samme rækkefølge", names("Sal B") == ["B", "C", "D"], names("Sal B"))
    check("resten bliver i hallen", names("Sal A") == ["A", "E", "F"], names("Sal A"))
    check("markeringen nulstilles efter flytning", page.is_hidden("#bulk-bar"))

    page.click("#select-all")
    check("Vælg alle vælger hele hallen", page.inner_text("#bulk-count") == "3 valgt")
    page.click("#bulk-clear")
    check("Fjern markering fjerner alle valg", page.is_hidden("#bulk-bar") and not page.is_checked("#select-all"))

    boxes.nth(0).click()
    boxes.nth(2).click()
    n = len(dialogs)
    page.click("#bulk-delete")
    page.wait_for_function("() => STATE.rows.filter(r => r.opvisningHal === 'Sal A').length === 1")
    check("Slet valgte beder om bekræftelse og sletter", len(dialogs) > n and "Slet 2 valgte" in dialogs[-1]
          and names("Sal A") == ["E"], (dialogs[-1:], names("Sal A")))

    api(page, "DELETE", "/api/halls/show", {"name": "Sal B"})
    refresh(page)
    page.locator("#table-body td.select-col input").first.click()
    check("med kun én opvisningshal kan der ikke flyttes", page.is_disabled("#bulk-move")
          and page.locator("#bulk-target option").all_inner_texts() == ["Ingen anden hal"])


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
            page.on("dialog", lambda d: (dialogs.append(d.message),
                                         d.accept("Sent hold") if d.type == "prompt" else d.accept()))
            page.on("pageerror", lambda e: errors.append(str(e)))
            common_flow(page, url, xlsx, dialogs, errors)
            new_features(page, tmp, dialogs)
            bulk_tests(page, dialogs)
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
