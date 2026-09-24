# Opvarmningsplanlægger v2.0

Lokal hjemmeside-version af `lav_opvarmning_final.py`.

## Kør

```bash
pip install -r requirements.txt
python app.py
```

Åbn derefter http://localhost:8877 i browseren.

## Brug

1. Opret dine opvarmningshaller og opvisningshaller på startsiden (eller
   under **Haller**). Den første opvarmningshal bliver prioritetshal.
2. Upload en eller flere Excel-filer med hold (kolonnerne `Tid`, `Varighed`,
   `Holdnavn`/`Forening`, `Antal deltagere`, evt. `Holdtype` og `Alder`).
   Hver fil bliver sin egen opvisningshal (fane øverst i listen), med et
   startklokkeslæt der foreslås ud fra filens første `Tid`-værdi — ret det
   under **Haller** eller direkte i værktøjslinjen over listen.
3. **Opvisningstiden beregnes automatisk**: for hver opvisningshal lægges
   varighederne sammen i rækkefølge, startende fra hallens startklokkeslæt
   (fx start kl. 9:00, første punkt tager 30 min → næste punkt er kl. 9:30).
   Træk i ⠿ for at ændre rækkefølgen på et hold/punkt — alle tider efter det
   genberegnes automatisk.
4. Brug **+ Pause**, **+ Faneindmarch** og **+ Faneudmarch** i værktøjslinjen
   til at indsætte programpunkter der optager tid i planen, men ikke skal
   varme op.
5. Ret holdnavn, varighed og opvarmningstid direkte i listen — resten af
   Excel-informationen (forening, antal, holdtype, alder) bruges stadig i
   baggrunden til opvarmningsberegningen, men vises ikke i listen.
6. Klik **Hent Excel-plan** for at downloade den beregnede opvarmningsplan som
   Excel-dokument (samme opbygning som generation 1.0: Output, OpvarmningPlan,
   ét ark pr. opvarmningshal, m.m.).

Data gemmes løbende i `state.json` i denne mappe, så du ikke mister noget ved
at genstarte serveren.

## Kodestruktur

```
app.py              webserver (FastAPI) og API
engine/             beregningsmotoren — bruges af både hjemmesiden og scriptet
  config.py         faste standardværdier og nøgleordslister
  rules.py          holdtype, alder, opvarmnings-/gangtid og prioritet
  values.py         robuste konverteringer (NaN, klokkeslæt, id'er)
  importer.py       Excel -> rækker -> DataFrame med opvisningstider
  placement.py      placeringsalgoritmen for opvarmning
  serialize.py      plan -> JSON til frontenden
  export.py         plan -> Excel-fil
static/             frontend (HTML, CSS, JS)
```

Kommandolinje-versionen (`../lav_opvarmning_final.py fil1.xlsx ...`) bruger
den samme `engine`. Kør én dag ad gangen — filer fra forskellige dage i samme
kørsel deler opvarmningshallerne på samme klokkeslæt.
