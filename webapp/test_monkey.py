"""
Robot-bruger: klikker, skriver, vælger og trækker tilfældigt rundt på siden
som en helt ny bruger og holder øje med JavaScript-fejl, og med en skærm der
ikke passer med den gemte plan.

Kør: python test_monkey.py [BRUGERE] [SKRIDT]     (standard 2 x 60)
Kræver playwright og Microsoft Edge (som test_e2e.py). Bruger rigtige
Excel-filer fra projektmappen, hvis de findes (*_færdig.xlsx).
"""
import base64
import random
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

from testkit import excel_bytes, start_server

HERE = Path(__file__).parent
FILES = sorted(HERE.parent.glob("*_færdig.xlsx"))[:3]
if len(FILES) < 3:   # uden de rigtige filer: lav tre store programmer
    FILES = []
    for hal in ("Arena", "Hal2", "Arena2"):
        f = Path(tempfile.gettempdir()) / f"monkey_{hal}.xlsx"
        f.write_bytes(excel_bytes([(f"{hal} hold {i}", 8 + i % 7) for i in range(30)], start="08:30"))
        FILES.append(f)
TEXTS = ["", " ", "Hal 3 A", "Hal 4", "Arena", "Hal2", "9.30", "930", "25:00", "abc", "-5", "0", "40", "41", "999",
         "æøå", "<img src=x onerror=alert(1)>", "x" * 120, "12", "15", "08:00", "23:55"]

SANITY = """() => {
  const errs = [];
  const unplaced = STATE.rows.filter(r => r.needsWarmup && r.problemMessage).length;
  const badge = document.getElementById('problem-count');
  if (unplaced && badge.textContent !== String(unplaced)) errs.push(`tal i menuen ${badge.textContent} != ${unplaced}`);
  if (!unplaced && !badge.classList.contains('hidden')) errs.push('rødt tal vises uden hold uden plads');
  const view = currentView;
  if (view === 'program' && STATE.showHalls.some(h => h.name === activeHal)) {
    const n = STATE.rows.filter(r => r.opvisningHal === activeHal).length;
    const shown = document.querySelectorAll('#table-body tr').length;
    if (n && shown !== n) errs.push(`Program viser ${shown} rækker, men hallen har ${n}`);
  }
  if (view === 'opvarmning' && activeWarmupHal) {
    const n = STATE.rows.filter(r => r.needsWarmup && r.status === 'OK' && r.opvarmningHalBeregnet === activeWarmupHal).length;
    const shown = document.querySelectorAll('#warmup-table-body tr').length;
    if (n && shown !== n) errs.push(`Opvarmning viser ${shown} rækker, men hallen har ${n}`);
  }
  if (activeHal && !STATE.showHalls.some(h => h.name === activeHal) && STATE.showHalls.length)
    errs.push(`aktiv opvisningshal ${activeHal} findes ikke`);
  if (document.querySelector('script[src*="onerror"], img[src="x"]')) errs.push('HTML fra et holdnavn blev til rigtig HTML');
  const teams = STATE.rows.filter(r => r.needsWarmup).length;
  const onb = !document.getElementById('onboarding').classList.contains('hidden');
  if (view === 'oversigt' && teams && onb) errs.push('Kom i gang vises, selv om der er hold');
  return errs;
}"""


def drop(page, selector, files):
    page.evaluate("""([sel, files]) => {
      const el = document.querySelector(sel); if (!el) return;
      const dt = new DataTransfer();
      for (const [name, b64] of files) dt.items.add(new File([Uint8Array.from(atob(b64), c => c.charCodeAt(0))], name));
      for (const t of ["dragenter", "dragover", "drop"]) el.dispatchEvent(new DragEvent(t, {bubbles: true, cancelable: true, dataTransfer: dt}));
    }""", [selector, [(n, base64.b64encode(d).decode()) for n, d in files]])


def step(page, rng, log):
    kind = rng.choices(["click", "fill", "select", "drag", "dropfile", "key", "view", "upload"],
                       weights=[10, 6, 3, 4, 2, 1, 2, 1])[0]
    if kind == "view":
        v = rng.choice(["oversigt", "program", "opvarmning"])
        log.append(f"menu {v}")
        page.click(f".rail-link[data-view={v}]")
    elif kind == "click":
        btns = page.locator("button:visible, .hall-row:visible, .tl-block:visible, input[type=checkbox]:visible")
        n = btns.count()
        if not n:
            return
        i = rng.randrange(n)
        el = btns.nth(i)
        label = (el.get_attribute("id") or el.get_attribute("aria-label") or el.inner_text() or "?")[:40].replace("\n", " ")
        if label in ("btn-clear-data",):
            return
        log.append(f"klik {label!r}")
        el.click(timeout=3000, modifiers=["Shift"] if rng.random() < 0.1 else None)
    elif kind == "fill":
        fields = page.locator("input[type=text]:visible, input[type=number]:visible")
        n = fields.count()
        if not n:
            return
        el = fields.nth(rng.randrange(n))
        text = rng.choice(TEXTS)
        if el.get_attribute("type") == "number" and not text.lstrip("-").isdigit():
            text = rng.choice(["0", "5", "12", "40", "41", "-3", "200"])
        log.append(f"skriv {text[:30]!r} i {el.get_attribute('aria-label') or el.get_attribute('data-focus-key') or el.get_attribute('id')}")
        el.fill(text)
        el.press(rng.choice(["Tab", "Enter"]))
    elif kind == "select":
        sels = page.locator("select:visible:enabled")
        n = sels.count()
        if not n:
            return
        el = sels.nth(rng.randrange(n))
        opts = el.locator("option").all_inner_texts()
        if not opts:
            return
        o = rng.choice(opts)
        log.append(f"vælg {o!r}")
        el.select_option(label=o)
    elif kind == "drag":
        src = page.locator("[draggable=true]:visible")
        dst = page.locator("tr:visible, .tab:visible, .tl-track:visible")
        if not src.count() or not dst.count():
            return
        a, b = src.nth(rng.randrange(src.count())), dst.nth(rng.randrange(dst.count()))
        log.append("træk et hold")
        a.drag_to(b, timeout=4000, target_position={"x": rng.randint(2, 300), "y": 8})
    elif kind == "dropfile":
        targets = ["#onb-show-list li:nth-child(1) .hall-drop", "#onb-show-list li:nth-child(2) .hall-drop",
                   "#show-hall-summary li:nth-child(1) .hall-row", "#hal-tabs .tab:nth-child(1)",
                   "#hal-tabs .tab:nth-child(2)", "main"]
        files = rng.choice([[(FILES[0].name, FILES[0].read_bytes())], [("x.xlsx", excel_bytes(["N1", "N2"]))],
                            [("skrald.xlsx", b"nej")], [("noter.pdf", b"%PDF")],
                            [(FILES[1].name, FILES[1].read_bytes()), (FILES[2].name, FILES[2].read_bytes())]])
        t = rng.choice(targets)
        log.append(f"slip {[f for f, _ in files]} på {t}")
        drop(page, t, files)
    elif kind == "upload":
        log.append("Indlæs program-knap")
        with page.expect_file_chooser(timeout=3000) as fc:
            page.click("#btn-upload")
        fc.value.set_files(str(rng.choice(FILES)))
    elif kind == "key":
        k = rng.choice(["Escape", "Tab", "Enter", "ArrowUp", "ArrowDown"])
        log.append(f"tast {k}")
        page.keyboard.press(k)
    page.wait_for_timeout(rng.choice([0, 30, 120]))


def run(seeds=2, steps=60):
    problems = {}
    tmp = tempfile.mkdtemp()
    proc, url = start_server(tmp)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            for seed in range(seeds):
                rng = random.Random(1000 + seed)
                ctx = browser.new_context(viewport=rng.choice([{"width": 1440, "height": 900}, {"width": 1000, "height": 760}]),
                                          accept_downloads=True)
                page = ctx.new_page()
                errors, log = [], []
                page.on("pageerror", lambda e: errors.append(f"JS-fejl: {e}"))
                page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}")
                        if m.type == "error" and "status of 40" not in m.text else None)   # 400/404 = pæn dansk besked
                page.on("dialog", lambda d: (log.append(f"  besked: {d.message[:90]}"),
                                             d.accept(rng.choice(TEXTS)) if d.type == "prompt"
                                             else (d.accept() if rng.random() < 0.8 else d.dismiss())))
                # hver bruger starter med en helt tom plan
                page.request.post(url + "api/reset")
                for h in page.request.get(url + "api/state").json()["showHalls"]:
                    page.request.delete(url + "api/halls/show", data={"name": h["name"]})
                for h in page.request.get(url + "api/state").json()["warmupHalls"]:
                    page.request.delete(url + "api/halls/warmup", data={"name": h})
                page.request.post(url + "api/halls/show", data={"name": "Hal 1"})
                page.goto(url)
                page.wait_for_selector("#onboarding:not(.hidden)")
                for i in range(steps):
                    try:
                        step(page, rng, log)
                    except Exception as e:
                        msg = str(e).split("\n")[0]
                        if "Timeout" not in msg and "not attached" not in msg and "intercepts pointer" not in msg:
                            problems.setdefault(f"robot-fejl: {msg[:100]}", (seed, i, log[-8:]))
                        page.keyboard.press("Escape")
                        continue
                    try:
                        page.wait_for_timeout(60)
                        found = page.evaluate(SANITY)
                        if found:   # måske midt i at tegne forfra — tjek igen lidt senere
                            page.wait_for_timeout(700)
                            found = page.evaluate(SANITY)
                        found += errors
                    except Exception as e:
                        found = [f"siden svarer ikke: {str(e)[:100]}"]
                    errors.clear()
                    for f in found:
                        key = f.split(":")[0][:60] if f.startswith("console") else f[:70]
                        problems.setdefault(key, (seed, i, log[-8:] + [f]))
                    # tjek at siden viser det samme som serveren har gemt
                    try:
                        same = page.evaluate("async () => JSON.stringify((await Api.request('GET','/api/state')).rows) === JSON.stringify(STATE.rows)")
                        if not same:
                            page.wait_for_timeout(800)
                            same = page.evaluate("async () => JSON.stringify((await Api.request('GET','/api/state')).rows) === JSON.stringify(STATE.rows)")
                        if not same:
                            problems.setdefault("siden viser noget andet end den gemte plan", (seed, i, log[-8:]))
                    except Exception:
                        pass
                ctx.close()
            browser.close()
    finally:
        proc.terminate()
    return problems


if __name__ == "__main__":
    args = [int(a) for a in sys.argv[1:3]]
    seeds, steps = (args + [2, 60][len(args):])[:2]
    probs = run(seeds, steps)
    for k, (seed, i, log) in probs.items():
        print(f"\n### {k}\n  seed={seed} skridt={i}\n  " + "\n  ".join(log))
    print(f"\n{seeds} robot-brugere x {steps} skridt: {len(probs)} slags fejl")
    sys.exit(1 if probs else 0)
