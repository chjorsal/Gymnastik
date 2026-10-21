"""
Browsertest med Playwright og Microsoft Edge.

  python test_e2e.py server    tester python app.py (egen server, midlertidig state)
  python test_e2e.py browser   tester den byggede browserudgave (Task 6)

Kræver: pip install playwright   (bruger den installerede Edge; ingen download)
"""
import subprocess
import sys
import tempfile
from io import BytesIO
from pathlib import Path

import pandas as pd
from playwright.sync_api import sync_playwright

import testkit
from testkit import check, excel_bytes, free_port, start_server, summary, wait_for

HERE = Path(__file__).parent
testkit.VERBOSE = True


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
          and "Efterskoler først" in page.locator("#onb-warmup-list li").first.inner_text())
    page.locator("#onb-warmup-list li").nth(1).locator(".star").click()
    page.wait_for_function("() => STATE.priorityHall === 'Varm 2'")
    check("stjernen gør en anden hal til prioritetshal", "Efterskoler først" in page.locator("#onb-warmup-list li").nth(1).inner_text())
    page.locator("#onb-warmup-list li").first.locator(".star").click()
    page.wait_for_function("() => STATE.priorityHall === 'Varm 1'")
    first = page.locator("#onb-show-list li").first
    check("ny plan starter med opvisningshallen Hal 1, og trin 2 er det næste",
          page.locator("#onb-show-list li").count() == 1 and first.locator(".hall-name-input").input_value() == "Hal 1"
          and "current" in page.get_attribute("#step-show", "class"))
    old_time = first.locator(".hall-time-input").element_handle()
    first.locator(".hall-name-input").fill("Sal A")
    first.locator(".hall-name-input").press("Tab")
    page.wait_for_function("() => STATE.showHalls[0].name === 'Sal A'")
    # vent til listen er tegnet forfra (det gamle felt er væk)
    page.wait_for_function("(old) => !old.isConnected", arg=old_time)
    check("Tab efter omdøbning flytter fokus til starttiden",
          page.evaluate("() => document.activeElement.classList.contains('hall-time-input')"))
    page.keyboard.press("Control+A")
    page.keyboard.type("9.15")
    page.keyboard.press("Tab")
    page.wait_for_function("() => STATE.showHalls[0].startTime === '09:15'")
    page.fill("#onb-show-form input >> nth=0", "Sal B")
    page.fill("#onb-show-form input >> nth=1", "10:00")
    page.click("#onb-show-form button")
    page.wait_for_function("document.querySelectorAll('#onb-show-list li').length === 2")
    values = [page.locator("#onb-show-list .hall-name-input").nth(i).input_value() for i in range(2)]
    times = [page.locator("#onb-show-list .hall-time-input").nth(i).input_value() for i in range(2)]
    check("navn og starttid rettes direkte i listen", (values, times) == (["Sal A", "Sal B"], ["09:15", "10:00"]),
          (values, times))
    check("hver opvisningshal har sit eget felt til Excel-filen", page.locator("#onb-show-list .hall-drop").count() == 2)

    n = len(dialogs)
    second = page.locator("#onb-show-list .hall-name-input").nth(1)
    second.fill("Sal A")
    second.press("Tab")
    page.wait_for_timeout(400)
    check("to haller kan ikke hedde det samme",
          len(dialogs) > n and "findes allerede" in dialogs[-1]
          and page.evaluate("() => STATE.showHalls.map(h => h.name)") == ["Sal A", "Sal B"]
          and page.locator("#onb-show-list .hall-name-input").nth(1).input_value() == "Sal B", dialogs[-1:])
    second = page.locator("#onb-show-list .hall-name-input").nth(1)
    second.fill("   ")
    second.press("Tab")
    page.wait_for_timeout(200)
    check("et tomt navn fortrydes", page.locator("#onb-show-list .hall-name-input").nth(1).input_value() == "Sal B"
          and page.evaluate("() => STATE.showHalls[1].name") == "Sal B")

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
    add_from_menu(page, "#btn-add-team")
    page.wait_for_function("() => STATE.rows.some(r => r.hold === 'Sent hold')")
    sent = page.evaluate("() => STATE.rows.find(r => r.hold === 'Sent hold')")
    # (om der er plads til opvarmningen afhænger af hallerne; det testes i test_actions)
    check("Hold-knappen tilføjer et 15/15-hold, der skal varme op",
          sent["varighed"] == 15 and sent["opvarmningMinOverride"] == 15 and sent["needsWarmup"], sent)
    check("navnet på et tilføjet hold kan rettes", page.locator("#table-body input.team-name").count() == 1)

    import datetime
    today = datetime.date.today().strftime("%d-%m-%Y")
    page.click("#btn-export")
    page.wait_for_selector("#export-dialog.show")
    page.wait_for_function("() => document.activeElement.id === 'export-name'")
    check("Hent Excel-plan åbner en boks med et forslag til filnavn",
          page.input_value("#export-name") == f"Opvarmningsplan Sal A og Sal B {today}", page.input_value("#export-name"))
    page.click("#export-dialog >> text=Annullér")
    page.wait_for_selector("#export-dialog", state="hidden")
    check("Annullér lukker boksen uden at hente noget", True)

    page.click("#btn-export")
    page.wait_for_selector("#export-dialog.show")
    page.fill("#export-name", "Lørdag: Arena/Hal2.xlsx")
    with page.expect_download() as dl:
        page.press("#export-name", "Enter")
    check("filen hentes med brugerens navn, gjort sikkert",
          dl.value.suggested_filename == "Lørdag Arena Hal2.xlsx", dl.value.suggested_filename)
    page.wait_for_selector("#export-dialog", state="hidden")
    page.click("#btn-export")
    page.wait_for_selector("#export-dialog.show")
    check("det sidst brugte navn huskes", page.input_value("#export-name") == "Lørdag: Arena/Hal2",
          page.input_value("#export-name"))
    page.fill("#export-name", "   ")
    with page.expect_download() as dl:
        page.click("#export-dialog button[type=submit]")
    check("et tomt navn giver forslaget som filnavn",
          dl.value.suggested_filename == f"Opvarmningsplan Sal A og Sal B {today}.xlsx", dl.value.suggested_filename)
    page.wait_for_selector("#export-dialog", state="hidden")
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
    add_from_menu(page, ".add-special[data-type=pause]")
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
    check("Slet alle data fjerner alt og viser 'Kom i gang' med Hal 1",
          left == [] and page.evaluate("() => STATE.warmupHalls.length") == 0
          and page.evaluate("() => STATE.showHalls.map(h => h.name)") == ["Hal 1"], left)

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
    add_from_menu(page, ".add-special[data-type=pause]")
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
    path = Path(tmp) / "tolv.xlsx"
    path.write_bytes(excel_bytes([(c, 12) for c in "ABCDEF"]))
    page.set_input_files("#file-input", str(path))
    page.wait_for_function("() => STATE.rows.length === 6")
    page.click(".rail-link[data-view=oversigt]")
    unplaced = page.evaluate("() => STATE.rows.filter(r => r.status !== 'OK').map(r => r.hold)")
    check("scenarie: B, D og F mangler plads", unplaced == ["B", "D", "F"], unplaced)

    check("den røde linje har én knap: Find løsning",
          "Find løsning" in page.inner_text("#problem-banner .banner-action")
          and page.locator("text=Brug forslag").count() == 0 and page.locator("text=Løs det").count() == 0)
    f_id = page.evaluate("() => STATE.rows.find(r => r.hold === 'F').id")
    api(page, "PATCH", f"/api/rows/{f_id}", {"field": "opvarmningMin", "value": 12})
    refresh(page)
    f = page.evaluate("() => STATE.rows.find(r => r.hold === 'F')")
    check("F får plads med 12 min opvarmning", (f["status"], f["opvarmningStart"]) == ("OK", "09:43"), f)

    # 3: træk D ind i et hul på tidslinjen
    tl = page.evaluate("() => { const d = document.getElementById('timeline').dataset;"
                       " return {from: +d.from, span: +d.span, w: +d.trackW}; }")
    x_at = lambda hhmm: (int(hhmm[:2]) * 60 + int(hhmm[3:]) - tl["from"]) / tl["span"] * tl["w"] + 2
    red = page.locator(".tl-lane-problem .tl-block").nth(1)   # D (B er nr. 0)
    lane = page.locator(".tl-lane", has=page.locator(".tl-lane-name", has_text="Varm 1")).locator(".tl-track")
    before = len(dialogs)
    red.drag_to(lane, target_position={"x": x_at("08:30"), "y": 20})
    page.wait_for_timeout(800)
    d = page.evaluate("() => STATE.rows.find(r => r.hold === 'D')")
    check("træk til en optaget tid afvises med besked, D uændret",
          len(dialogs) > before and "ikke plads" in dialogs[-1] and d["status"] != "OK", dialogs[-1:])
    red = page.locator(".tl-lane-problem .tl-block").nth(1)
    red.drag_to(lane, target_position={"x": x_at("08:05"), "y": 20})
    page.wait_for_timeout(800)
    check("træk til mere end 45 min før opvisningen afvises med besked",
          "45 min" in dialogs[-1] and page.evaluate("() => STATE.rows.find(r => r.hold === 'D').status") != "OK", dialogs[-1:])

    # Varm 1 er fuld. En ekstra hal Varm 2, og alle hold låses til Varm 1, så
    # B og D stadig står uden plads — så kan de trækkes over i Varm 2.
    api(page, "POST", "/api/halls/warmup", {"name": "Varm 2"})
    for team in "ABCDEF":
        tid = page.evaluate(f"() => STATE.rows.find(r => r.hold === '{team}').id")
        api(page, "PATCH", f"/api/rows/{tid}", {"field": "opvarmningHal", "value": "Varm 1"})
    refresh(page)
    tl = page.evaluate("() => { const d = document.getElementById('timeline').dataset;"
                       " return {from: +d.from, span: +d.span, w: +d.trackW}; }")
    lane2 = page.locator(".tl-lane", has=page.locator(".tl-lane-name", has_text="Varm 2")).locator(".tl-track")
    page.locator(".tl-lane-problem .tl-block").nth(1).drag_to(lane2, target_position={"x": x_at("09:10"), "y": 20})
    page.wait_for_function("() => STATE.rows.find(r => r.hold === 'D').status === 'OK'")
    d = page.evaluate("() => STATE.rows.find(r => r.hold === 'D')")
    check("træk D til en ledig tid giver opvarmning der (Varm 2 09:10)",
          (d["opvarmningHalBeregnet"], d["opvarmningStart"]) == ("Varm 2", "09:10"), d)
    tl = page.evaluate("() => { const d = document.getElementById('timeline').dataset;"
                       " return {from: +d.from, span: +d.span, w: +d.trackW}; }")
    page.locator(".tl-lane-problem .tl-block").first.drag_to(lane2, target_position={"x": x_at("08:50"), "y": 20})
    page.wait_for_function("() => STATE.rows.find(r => r.hold === 'B').status === 'OK'")
    check("ingen hold uden plads -> ingen rød linje og ingen rød række",
          page.is_hidden("#problem-banner") and page.locator(".tl-lane-problem").count() == 0)


def add_from_menu(page, item):
    """Åbner "+ Tilføj"-menuen under Program og vælger et punkt i den."""
    page.click("#btn-add-menu")
    page.click(item)


def solve_hall_tests(page, tmp):
    """Find løsning flytter frie hold til en anden hal og giver tip om låste hold."""
    api(page, "POST", "/api/reset")
    for hal in ("Varm 1", "Varm 2"):
        api(page, "POST", "/api/halls/warmup", {"name": hal})
    for sal, start in (("Sal A", "10:00"), ("Sal B", "10:10"), ("Sal C", "10:15")):
        api(page, "POST", "/api/halls/show", {"name": sal})
        api(page, "POST", "/api/halls/show/starttime", {"name": sal, "startTime": start})
    refresh(page)
    for sal, team in (("Sal A", "A"), ("Sal B", "L"), ("Sal C", "P")):
        path = Path(tmp) / f"{team}.xlsx"
        path.write_bytes(excel_bytes([team]))
        page.evaluate("(h) => { uploadTarget = h; fileHandler = null; }", sal)
        page.set_input_files("#file-input", str(path))
        page.wait_for_function(f"() => STATE.rows.some(r => r.hold === '{team}')")
    rid = lambda team: page.evaluate(f"() => STATE.rows.find(r => r.hold === '{team}').id")
    # P får fast tid først (mens der er plads), og bliver så længere
    api(page, "POST", f"/api/rows/{rid('P')}/place", {"hal": "Varm 2", "start": "09:30"})
    for team, minutes in (("A", 15), ("L", 30), ("P", 40)):
        api(page, "PATCH", f"/api/rows/{rid(team)}", {"field": "opvarmningMin", "value": minutes})
    refresh(page)
    page.click(".rail-link[data-view=oversigt]")
    page.click("#problem-banner")
    page.wait_for_selector("#solve-result .solve-actions", timeout=120_000)
    text = page.inner_text("#solve-result")
    check("Find løsning foreslår en anden hal i stedet for kortere opvarmning",
          "L (går på 10:10 i Sal B): varmer op i Varm 1" in text and "→" not in text, text)
    page.click("#solve-result >> text=Brug løsningen")
    page.wait_for_function("() => STATE.rows.every(r => r.status === 'OK')")
    check("Brug løsningen lægger holdet i den foreslåede hal",
          page.evaluate("() => STATE.rows.find(r => r.hold === 'L').opvarmningHalOverride") == "Varm 1")

    # Låst hold uden plads: tip og knap, men ingen automatisk flytning
    api(page, "PATCH", f"/api/rows/{rid('L')}", {"field": "opvarmningHal", "value": "Varm 2"})
    refresh(page)
    page.click("#problem-banner")
    page.wait_for_selector("#solve-result .solve-actions", timeout=120_000)
    text = page.inner_text("#solve-result")
    check("et låst hold flyttes ikke, men der står hvor der er plads",
          "L er låst til Varm 2. Der er plads i Varm 1" in text and "Brug løsningen" not in text, text)
    page.click("#solve-result >> text=Flyt til Varm 1")
    page.wait_for_function("() => STATE.rows.find(r => r.hold === 'L').status === 'OK'")
    check("knappen i tippet flytter holdet", page.evaluate(
        "() => STATE.rows.find(r => r.hold === 'L').opvarmningHalOverride") == "Varm 1")
    # ryd op: de næste tests opretter selv Sal B og Sal C uden fast starttid
    for sal in ("Sal B", "Sal C"):
        api(page, "DELETE", "/api/halls/show", {"name": sal})
    api(page, "DELETE", "/api/halls/warmup", {"name": "Varm 2"})
    refresh(page)


def drop_files(page, selector, files):
    """Slipper filer fra 'computeren' på elementet. files: [(navn, bytes)]."""
    import base64
    page.evaluate("""([sel, files]) => {
      const dt = new DataTransfer();
      for (const [name, b64] of files) {
        dt.items.add(new File([Uint8Array.from(atob(b64), (c) => c.charCodeAt(0))], name));
      }
      const el = document.querySelector(sel);
      for (const type of ["dragenter", "dragover", "drop"]) {
        el.dispatchEvent(new DragEvent(type, { bubbles: true, cancelable: true, dataTransfer: dt }));
      }
    }""", [selector, [(name, base64.b64encode(data).decode()) for name, data in files]])


def drop_tests(page, tmp, dialogs):
    """Træk Excel-filer ind på den hal, de hører til."""
    api(page, "POST", "/api/reset")
    for hal in ("Sal B", "Sal C"):
        api(page, "POST", "/api/halls/show", {"name": hal})
    refresh(page)
    page.click(".rail-link[data-view=oversigt]")
    page.wait_for_selector("#onboarding:not(.hidden)")
    rows_in = lambda hal: page.evaluate(f"() => STATE.rows.filter(r => r.opvisningHal === '{hal}')"
                                        ".sort((a, b) => a.order - b.order).map(r => r.hold)")

    check("Lav opvarmningsplan kan ikke trykkes, før der ligger en fil klar", page.is_disabled("#btn-make-plan"))
    drop_files(page, "#onb-show-list li:nth-child(2) .hall-drop",
               [("fredag.xlsx", excel_bytes(["B1", "B2"], "13:00")), ("lørdag.xlsx", excel_bytes(["B3"]))])
    page.wait_for_timeout(300)
    check("filer sluppet på en hal lægges klar og indlæses ikke endnu",
          page.evaluate("() => STATE.rows.length") == 0 and page.is_visible("#onboarding")
          and page.locator("#onb-show-list li:nth-child(2) .staged-file").all_inner_texts() == ["fredag.xlsx", "lørdag.xlsx"])
    drop_files(page, "#onb-show-list li:nth-child(1) .hall-drop", [("a.xlsx", excel_bytes(["A0"]))])
    page.wait_for_timeout(200)
    check("man kan nå at lægge en fil i den anden hal også",
          page.locator("#onb-show-list li:nth-child(1) .staged-file").count() == 1 and not page.is_disabled("#btn-make-plan"))
    page.locator("#onb-show-list li:nth-child(1) .staged-file button").click()
    check("✕ fjerner en fil, der ligger klar", page.locator("#onb-show-list li:nth-child(1) .staged-file").count() == 0)

    page.click("#btn-make-plan")
    page.wait_for_function("() => STATE.rows.length === 3")
    check("Lav opvarmningsplan indlæser filerne i deres hal, i rækkefølge", rows_in("Sal B") == ["B1", "B2", "B3"]
          and rows_in("Sal A") == [], rows_in("Sal B"))
    check("en tom hal får starttiden fra filens første Tid",
          page.evaluate("() => STATE.showHalls.find(h => h.name === 'Sal B').startTime") == "13:00")

    page.wait_for_selector("#overview-data:not(.hidden)")
    drop_files(page, "#show-hall-summary li:nth-child(3) .hall-row", [("c.xlsx", excel_bytes(["C1"]))])
    page.wait_for_function("() => STATE.rows.length === 4")
    check("en fil sluppet på en hal i oversigten lander i den hal", rows_in("Sal C") == ["C1"])

    page.click(".rail-link[data-view=program]")
    drop_files(page, "#hal-tabs .tab:nth-child(1)", [("a.xlsx", excel_bytes(["A1"]))])
    page.wait_for_function("() => STATE.rows.length === 5")
    check("en fil sluppet på en fane under Program lander i den hal, og fanen åbnes",
          rows_in("Sal A") == ["A1"] and page.evaluate("() => activeHal") == "Sal A")

    n = len(dialogs)
    drop_files(page, "#hal-tabs .tab:nth-child(2)", [("noter.pdf", b"%PDF")])
    page.wait_for_timeout(300)
    check("andre filer end .xlsx afvises med besked",
          len(dialogs) > n and "Kun Excel-filer" in dialogs[-1] and page.evaluate("() => STATE.rows.length") == 5)

    url = page.url
    drop_files(page, "main", [("x.xlsx", excel_bytes(["X"]))])
    page.wait_for_timeout(300)
    check("en fil sluppet uden for en hal gør ingenting", page.url == url and page.evaluate("() => STATE.rows.length") == 5)

    page.locator("#hal-tabs .tab", has_text="Sal C").click()
    late = Path(tmp) / "sen.xlsx"
    late.write_bytes(excel_bytes(["C2"]))
    with page.expect_file_chooser() as fc:
        page.click("#btn-upload")
    fc.value.set_files(str(late))
    page.wait_for_function("() => STATE.rows.length === 6")
    check("Indlæs Excel under Program lægger filen i den åbne hal", rows_in("Sal C") == ["C1", "C2"])

    # en ugyldig fil på Kom i gang: intet indlæses
    api(page, "POST", "/api/reset")
    refresh(page)
    page.click(".rail-link[data-view=oversigt]")
    page.wait_for_selector("#onboarding:not(.hidden)")
    drop_files(page, "#onb-show-list li:nth-child(1) .hall-drop", [("god.xlsx", excel_bytes(["G1"]))])
    drop_files(page, "#onb-show-list li:nth-child(2) .hall-drop", [("skrald.xlsx", b"ikke excel")])
    n = len(dialogs)
    page.click("#btn-make-plan")
    page.wait_for_timeout(600)
    check("én ugyldig fil giver besked, og ingen af filerne indlæses",
          len(dialogs) > n and "skrald.xlsx" in dialogs[-1] and page.evaluate("() => STATE.rows.length") == 0
          and page.locator("#onb-show-list .staged-file").count() == 2, dialogs[-1:])

    for hal in ("Sal A", "Sal B", "Sal C"):
        api(page, "DELETE", "/api/halls/show", {"name": hal})
    refresh(page)
    with page.expect_file_chooser() as fc:
        page.click("#btn-upload")
    fc.value.set_files(str(late))
    page.wait_for_function("() => STATE.rows.length === 1")
    check("uden haller opretter Indlæs Excel hallen Hal 1",
          page.evaluate("() => STATE.showHalls.map(h => h.name)") == ["Hal 1"] and rows_in("Hal 1") == ["C2"])


def ux_tests(page):
    """Det nye udseende: faner med antal og "fast tid · slip"."""
    page.click(".rail-link[data-view=program]")
    count = page.locator("#hal-tabs .tab", has_text="Sal A").locator(".tab-count").inner_text()
    check("fanen viser antal hold i hallen", count == "6", count)
    page.click(".rail-link[data-view=opvarmning]")
    page.locator("#warmup-hal-tabs .tab", has_text="Varm 2").click()
    pinned = lambda: page.evaluate("() => STATE.rows.filter(r => r.opvarmningStartOverride).length")
    n = pinned()
    note = page.locator("#warmup-table-body .pin-note").first
    check("et hold med fast tid viser 'fast tid · slip'", n > 0 and "fast tid" in note.inner_text(), (n, note.inner_text()))
    note.locator(".pin-release").click()
    page.wait_for_function(f"() => STATE.rows.filter(r => r.opvarmningStartOverride).length === {n - 1}")
    check("slip gør holdets tid automatisk igen", True)
    check("problemrækker har ingen lyserød Bootstrap-flade",
          page.locator("tr.table-danger").count() == 0)
    api(page, "DELETE", "/api/halls/warmup", {"name": "Varm 2"})
    refresh(page)


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


def solve_tests(page, tmp):
    """Find løsning: forkort holdet og holdene omkring det, vis først, brug bagefter."""
    api(page, "POST", "/api/reset")
    refresh(page)
    path = Path(tmp) / "tolv2.xlsx"
    path.write_bytes(excel_bytes([(c, 12) for c in "ABCDEF"]))
    page.set_input_files("#file-input", str(path))
    page.wait_for_function("() => STATE.rows.length === 6")
    page.click(".rail-link[data-view=oversigt]")
    missing = lambda: page.evaluate("() => STATE.rows.filter(r => r.status !== 'OK').map(r => r.hold)")
    before = missing()
    check("scenarie til Find løsning: B, D og F mangler plads", before == ["B", "D", "F"], before)

    page.click(".rail-link[data-view=opvarmning]")
    check("Opvarmning viser antallet af hold uden plads øverst",
          page.inner_text("#unplaced-title").strip() == "3 hold mangler plads til opvarmning", page.inner_text("#unplaced-title"))
    page.click("#btn-solve-warmup")
    page.wait_for_selector("#solve-result .solve-actions", timeout=120_000)
    check("Find løsning på Opvarmning viser løsningen på oversigten",
          page.evaluate("() => currentView") == "oversigt" and missing() == before)
    page.click("#solve-result >> text=Annullér")

    page.click("#problem-banner")
    page.wait_for_selector("#solve-result .solve-actions", timeout=120_000)
    text = page.inner_text("#solve-result")
    check("Find løsning viser hvilke hold der får plads og hvad der forkortes", "får plads" in text and "→" in text, text)
    mins = [int(m) for m in __import__("re").findall(r"→ (\d+) min", text)]
    check("løsningen går aldrig under 10 min", mins and min(mins) >= 10, mins)
    page.click("#solve-result >> text=Annullér")
    check("Annullér skjuler løsningen og ændrer intet", page.is_hidden("#solve-result") and missing() == before)

    page.click("#problem-banner")
    page.wait_for_selector("#solve-result .solve-actions", timeout=120_000)
    api(page, "POST", "/api/rows/special", {"hal": "Sal A", "type": "pause"})
    refresh(page)
    check("et gammelt resultat forsvinder, når planen ændres", page.is_hidden("#solve-result"))
    api(page, "DELETE", "/api/rows/" + page.evaluate("() => STATE.rows.find(r => r.type === 'pause').id"))
    refresh(page)

    page.click("#problem-banner")
    page.wait_for_selector("#solve-result .solve-actions", timeout=120_000)
    page.click("#solve-result >> text=Brug løsningen")
    page.wait_for_function(f"() => STATE.rows.filter(r => r.status !== 'OK').length < {len(before)}")
    after = missing()
    check("Brug løsningen giver flere hold plads", len(after) < len(before), after)
    check("ingen hold har fået under 10 min",
          page.evaluate("() => STATE.rows.every(r => r.opvarmningMinOverride === null || r.opvarmningMinOverride >= 10)"))


def run(mode):
    tmp = tempfile.mkdtemp()
    xlsx = Path(tmp) / "program.xlsx"
    xlsx.write_bytes(excel_bytes([f"Hold {i}" for i in range(1, 7)]))
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
            ux_tests(page)
            bulk_tests(page, dialogs)
            solve_tests(page, tmp)
            solve_hall_tests(page, tmp)
            drop_tests(page, tmp, dialogs)
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

    return summary()


if __name__ == "__main__":
    sys.exit(0 if run(sys.argv[1] if len(sys.argv) > 1 else "server") else 1)
