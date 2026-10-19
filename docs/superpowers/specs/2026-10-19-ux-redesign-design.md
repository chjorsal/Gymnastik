# Nyt udseende og brugervenlighed — design

**Dato:** 2026-10-19
**Status:** Retning godkendt i dialog med skitser. Brugeren vil se hele siden bygget, før der kommer flere ændringer.
**Læsere:** projektejeren og den, der senere overtager koden.

## Formål

Siden skal se flot og indbydende ud og kunne bruges af frivillige, der ikke
bruger IT til daglig. Knapperne skal selv fortælle, hvad man kan, så de grå
hjælpetekster kan fjernes. Alle funktioner og alle beregninger er uændrede.

**Uden for denne runde:** print og Instagram (det klarer DGI's STAP), samt mobil.
Ideer til foreninger uden STAP står i `docs/til-andre-foreninger.md`.

## Stil

| Rolle | Farve | Brug |
|---|---|---|
| Menu (venstre) | marineblå `#1b2a4a` | sidebjælke, logo-baggrund |
| Handling | orange `#ff7a1a` | hovedknapper, valgt menupunkt, valgt fane, træk-markør |
| Tekst på orange | marineblå `#1b2a4a` | tydelig kontrast (hvid på orange er for svag) |
| Side | varm lysegrå `#f3f0eb` | baggrund bag alt |
| Kort | lun hvid `#fcfaf6` + kant `#e7e1d8` | diagram, lister, tabeller |
| Skrivefelter | hvid `#ffffff` | kun der, hvor man kan skrive |
| Tekst | `#1f2430`, sekundær `#6b6f7a` | |
| Fejl | rød kant `#f2c4c6`, rød tekst `#b4232a` | ingen rød baggrund |

Diagrammets fem hal-farver (`--hal-0` til `--hal-4`) er uændrede. Farven viser,
hvilken opvisningshal holdet skal optræde i.

Knapper er runde ("piller") med ikon og tekst og mindst 44 px høje, så de kan
rammes med en finger. Ikoner er tegnede SVG-streger, ikke emojis.

## Skærme

Computer og tablet. Under 1024 px bliver menuen smal (ikon over kort tekst), og
store tabeller kan scrolles sidelæns i deres kort. Mobil er ikke et mål.

## Sider

**Overalt**
- Menu: Oversigt, Program, Opvarmning (med rødt tal for hold uden plads), Haller.
- "Indlæs program" (Excel) og "Hent plan" er pille-knapper øverst; "Hent plan" er orange.
- Fejlbeskeden øverst på oversigten har kun en rød kant.

**Kom i gang** (tom plan) — tre trin stillet som spørgsmål:
1. *Hvor varmer holdene op?* Stjernen hedder "Efterskoler først".
2. *Hvor optræder holdene — og hvornår starter programmet?* Navn og starttid
   rettes i listen; under hver hal et felt: "Træk Excel-filen hertil eller vælg fil".
3. *Tjek planen og hent den.*
Det trin, man er på, er orange; færdige trin får et grønt flueben.

**Program**
- Faner pr. opvisningshal med antal hold (fx "Arena 38").
- "Programmet starter [08:30]".
- Én orange knap "+ Tilføj ▾" med en menu: Hold, Pause | Dørene åbner,
  Faneindmarch, Faneudmarch (åben dør, fane med pil ind, fane med pil ud).
- Kolonner: Hold · På gulvet (min) · Varmer op (min) · Går på · Varmer op i · Opvisningshal.
- Håndtag ⋮⋮: hånd-markør, "Træk for at flytte holdet", rækken løfter sig, en
  orange streg viser, hvor den lander. Den grå hjælpesætning øverst fjernes.

**Opvarmning**
- Hold uden plads øverst i en boks med rød kant og knappen "Find løsning".
- Faner pr. opvarmningshal med antal hold.
- Kolonner: Varmer op (tid) · Hold · Går på ("Arena 10:24") · Min · Hal.
- Et hold med fast tid viser "fast tid · slip" i stedet for et ✕.

**Haller (sidepanel) og "Hent Excel-plan"-boksen** får samme stil.

## Test

Alle eksisterende tests skal bestå. Browsertesten opdateres, hvor knapper er
flyttet (fx Tilføj-menuen) eller trin har skiftet navn. Skærmbilleder af alle
sider i 1440 px og 1024 px (tablet) gennemses.
