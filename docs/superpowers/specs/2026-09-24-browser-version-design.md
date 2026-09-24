# Browserudgave på GitHub Pages — design

**Dato:** 2026-09-24
**Status:** Godkendt i dialog, afventer gennemlæsning
**Læsere:** projektejer og den udvikler eller virksomhed, der senere overtager koden

## 1. Formål

Opvarmningsplanlæggeren skal kunne bruges online uden at starte Python lokalt.
Lige nu er det til test for projektejeren og venner. På sigt skal hver forening
kunne bruge værktøjet til sine egne stævner, uden at se eller ændre andres
planer. En virksomhed forventes at overtage løsningen senere.

**Succeskriterier**

- Siden kan åbnes på `https://chjorsal.github.io/Gymnastik/` og virker som den
  lokale udgave: haller, indlæsning af Excel, program, opvarmning og eksport.
- Hver brugers plan er adskilt fra alle andres uden login.
- Planen er der stadig, når brugeren lukker og åbner siden igen i samme browser.
- Ingen hold- eller foreningsdata sendes til en server.
- Drift koster intet og kræver ikke en server.
- Den lokale serverudgave (`python app.py`) virker fortsat.

## 2. Beslutninger

| Emne | Valg | Fravalgt |
|---|---|---|
| Hosting | GitHub Pages (statisk) | Render, Railway, Fly.io (kræver server og database) |
| Kørsel af motoren | Pyodide (Python i browseren) med den eksisterende `engine/` | Omskrivning af motoren til JavaScript |
| Lagring | `localStorage` i brugerens browser | `sessionStorage` (planen forsvinder ved luk), serverdatabase |
| Adskillelse af brugere | Hver browser har sin egen plan | Login, delte links |
| Tredjeparter | Pyodide og pakker hostes på siden selv | jsDelivr eller anden CDN |

## 3. Arkitektur

```
                 ┌─────────── static/ (HTML/CSS/JS) ───────────┐
                 │        api.js  ─ vælger transport            │
                 └──────┬──────────────────────────┬───────────┘
          browser-udgave│                          │server-udgave
                        ▼                          ▼
              Pyodide (Python i browser)     app.py (FastAPI)
                        │                          │
                        └────────► planner/ ◄──────┘
                               actions.py   (alle handlinger)
                               engine/      (uændret)
                        │                          │
                 localStorage i browseren     state.json på serveren
```

### 3.1 Enheder

**`engine/`** (findes) — beregner opvisningstider, placerer opvarmning og
bygger Excel. Uændret.

**`planner/actions.py`** (ny) — alle handlinger, som i dag ligger i
`app.py`'s endpoints, som rene funktioner. Hver funktion tager planen (dict) og
input og returnerer enten den opdaterede plan eller en fejl.

- Handlinger: indlæs Excel, ret række, slet række, tilføj specialpunkt,
  omroker, byt opvarmningstid, nulstil, opret/omdøb/slet/prioritér
  opvarmningshal, opret/omdøb/slet opvisningshal, sæt starttid, eksportér,
  hent visning (`payload`).
- Migrering af gammel plan-data (i dag i `load_state`) flyttes også hertil, så
  en plan indlæst fra `localStorage` eller en `.json`-fil får samme behandling.
- Fejl returneres som en værdi med en dansk besked. De samme beskeder som i dag.
- Ingen afhængighed af FastAPI, filsystem eller browser.

**`app.py`** (ændres) — tynd HTTP-skal: læser request, kalder `actions`,
gemmer `state.json`, returnerer JSON. Endpoints og svar er uændrede, så den
nuværende frontend og `test_api.py` fortsat passer.

**`static/api.js`** (ny) — ét sted, hvor frontenden kalder handlinger. To
transporter:

- `http`: `fetch` mod `app.py`, som i dag.
- `pyodide`: kalder `planner.actions` direkte i browseren og gemmer planen i
  `localStorage` efter hver ændring.

Transporten vælges ved opstart: findes der en server (`/api/state` svarer),
bruges `http`. Ellers bruges `pyodide`. Browserudgaven kan også tvinges med en
konfigurationsværdi, som build-scriptet sætter.

**`static/app.js`** (ændres lidt) — kalder `api.js` i stedet for `fetch`
direkte. Visninger og brugerflade er uændrede.

### 3.2 Data-flow i browserudgaven

1. Siden åbnes. En indlæsningsskærm vises.
2. Pyodide, pandas, numpy og de hostede `openpyxl`/`et_xmlfile`-wheels hentes
   fra siden selv. `engine/` og `planner/` lægges ind i Pyodides filsystem.
3. Planen læses fra `localStorage` og migreres (se 3.1). Findes der ingen,
   startes med en tom plan.
4. Hver handling: `app.js` → `api.js` → `actions.<handling>(plan, input)` →
   ny plan → gemmes i `localStorage` → visning opdateres.
5. Indlæs Excel: filen læses som bytes i browseren og sendes til Python.
   Intet forlader computeren.
6. Hent Excel-plan: Python bygger filen som bytes, og browseren downloader den
   som `opvisning_med_opvarmning.xlsx`.

## 4. Lagring

- Nøgle: `opvarmning_plan_v1` i `localStorage`. Indhold: samme JSON-struktur
  som `state.json` i dag (ca. 25 KB for en fuld dag).
- Planen gemmes efter hver ændring.
- Er gemt data ulæseligt, flyttes det til nøglen
  `opvarmning_plan_broken_<tidspunkt>`, og siden starter med en tom plan.
  Det svarer til `state.broken-*.json` på serveren.
- `localStorage` forsvinder ikke, når siden lukkes. Den slettes kun, når
  brugeren trykker "Slet alle data", rydder browserdata eller bruger et privat
  vindue.

### 4.1 Gem og åbn plan

To knapper i Haller-panelet:

- **Gem plan** — downloader planen som `opvarmningsplan.json`.
- **Åbn plan** — indlæser en sådan fil og erstatter den nuværende plan efter
  bekræftelse. Filen migreres og valideres. En ugyldig fil giver en dansk
  fejlbesked og ændrer ikke den nuværende plan.

Bruges til backup, til at flytte en plan til en anden computer og til at dele
en plan med en anden arrangør.

## 5. Privatliv og GDPR

Dette er et teknisk udgangspunkt, ikke en juridisk vurdering. Det bør
vurderes, før en virksomhed overtager løsningen.

**Data i systemet:** holdnavne, foreninger, antal deltagere og aldersgruppe.
Det er oplysninger om hold. Det bliver kun personoplysninger, hvis en bruger
skriver personnavne i Excel-filen.

**Tiltag i browserudgaven:**

1. Hold-data forlader aldrig brugerens computer. Projektejeren og en senere
   virksomhed modtager eller gemmer ingen hold-data.
2. Pyodide og pakker hentes fra GitHub Pages selv, ikke fra en CDN. Kun GitHub
   ser brugerens IP-adresse, som ved enhver webside.
3. Ingen cookies, analyseværktøjer eller sporing. `localStorage` bruges kun til
   planen og er nødvendig for, at appen virker.
4. Tekst i Haller-panelet under "Om data": "Dine data gemmes kun i denne
   browser. De sendes ikke til nogen server. Skriv ikke personnavne i
   Excel-filen."
5. Knappen **Slet alle data** fjerner alt, appen har gemt i browseren, efter
   bekræftelse.

**Note til en senere virksomhed:** Tilføjes en server, hvor planer gemmes
centralt (fx delte links eller login), bliver der tale om behandling af data på
jeres side. Så skal der som minimum tages stilling til privatlivspolitik,
databehandleraftaler, hosting i EU, adgangsstyring og regler for sletning.

## 6. Udgivelse

- **`build_site.py`** (ny) samler browserudgaven i `site/`:
  `static/`, `engine/`, `planner/`, en konfigurationsfil der vælger
  `pyodide`-transporten, samt Pyodide-kernen og de nødvendige pakker (pandas,
  numpy og deres afhængigheder fra Pyodide-distributionen, `openpyxl` og
  `et_xmlfile` som wheels fra PyPI). Versionerne er låst i scriptet.
- **`.github/workflows/pages.yml`** (ny) kører `build_site.py` ved hvert push
  til `main` og udgiver `site/` på GitHub Pages.
- **Engangsopsætning:** i repoet på GitHub: Settings → Pages → Source:
  GitHub Actions.
- `site/` er genereret og kommer ikke i git (`.gitignore`).

## 7. Test

| Test | Hvad | Kører |
|---|---|---|
| `test_engine.py` | motoren (uændret) | lokalt, uden server |
| `test_actions.py` (ny) | alle handlinger i `planner/actions.py`, inkl. fejl og migrering | lokalt, uden server |
| `test_api.py` (skåret ned) | kort røgtest af serverudgaven | mod en testserver med egen `STATE_FILE` |
| Browsertest (Playwright/Edge) | hele forløbet i begge udgaver, plus: planen er der efter genindlæsning, Slet alle data, Gem/Åbn plan | mod `python app.py` og mod den byggede `site/` |

Motor- og handlingstestene køres også under pandas 3.0, samme version som i
Pyodide (se 8).

## 8. Risici

| Risiko | Håndtering |
|---|---|
| Pyodide bruger pandas 3.0; lokalt bruges 2.3. Pandas 3 ændrer bl.a. standard-strengtype og kopiering. | Første trin i planen: kør alle tests under pandas 3.0 og ret motoren, så den virker under begge versioner. |
| `openpyxl` er ikke med i Pyodide. | Hostes som wheel på siden og installeres med `micropip` fra siden selv. Testes i browsertesten via eksport. |
| Første indlæsning er ca. 15–25 MB. | Indlæsningsskærm med forventet ventetid. Browserens cache gør senere besøg hurtige. |
| En bruger mister sin plan ved at rydde browserdata. | "Gem plan" som backup. Nævnes i "Om data". |
| GitHub Pages har grænser: 1 GB pr. site og 100 MB pr. fil. | Kun de nødvendige Pyodide-pakker kopieres med. |

## 9. Uden for denne omgang

- Login og brugerkonti
- Server eller database til planer
- Flere arrangører i samme plan på samme tid
- Offline-brug i hallen uden internet
- Yderligere GDPR-tiltag ud over afsnit 5
