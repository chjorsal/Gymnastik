# Langtidsplan

Visionen for opvarmningsplanlæggeren på lang sigt. Skrevet 22. oktober 2026
efter en samtale om, hvad brugerne ønsker sig. Planen tages op igen, når den
nuværende udgave er testet grundigt.

Se også [Til andre foreninger](til-andre-foreninger.md) (print og Instagram).

## Hvor vi er nu

- En hjemmeside, der laver opvarmningsplaner til gymnastikopvisninger: haller,
  program, opvarmning, Find løsning og Excel ind og ud.
- Alt sker i brugerens egen browser. Ingen server, intet login, ingen data hos
  os. DGI's STAP-system står for det, deltagerne ser.
- Bruges indtil videre kun af os selv til test.

## Visionen

Et værktøj, hvor foreninger og DGI kan planlægge stævner sammen, ligesom man
deler mapper i Google Drev eller OneDrive. På sigt også for andre sportsgrene
med turneringer, og med en mobilvisning, hvor deltagerne kan se, hvornår og
hvor de skal på.

## Faser

Hver fase skal virke og være taget i brug, før den næste begynder.

### Fase 0 — Test af den nuværende udgave (nu)

- Test planlæggeren grundigt på rigtige stævner.
- Saml feedback fra dem, der skal bruge den.
- Mål: at planlæggeren bliver brugt til et rigtigt stævne.

### Fase 1 — Klar til flere brugere

- Små forbedringer fra testen.
- "Om data"-teksten opdateres: at kommentarerne kommer med i "Hent plan" og
  "Gem plan", og at GitHub Pages kan registrere IP-adresser.
- Deling sker som i dag: man gemmer planen og deler filen i OneDrive.

### Fase 2 — Platformen: foreninger, mapper og samarbejde

- Login med Microsoft (DGI-, forenings- og private konti).
- Foreninger med profiler og roller: ejer, redaktør, læser.
- Fælles mapper. Et stævne indeholder dagene (fx lørdag og søndag), og hver
  dag er sin egen plan.
- Flere kan arbejde i den samme plan på samme tid. Hver ændring sendes med det
  samme til de andre.
- Kræver en fælles server og database, fx en færdig tjeneste som Supabase eller
  Firebase med data i EU. Beregningen kan blive i browseren.
- Opvarmningsplanlæggeren flytter ind som det første modul.

### Fase 3 — Mobilvisning for deltagerne

- Et link eller en QR-kode, intet login.
- "Hvornår skal vi varme op og på gulvet?", "Hvilken hal?". Til opvisninger
  først, senere til kampe.
- Kun til at læse. Hold og tider, ingen personer.
- Kan laves tidligt, fordi den er enkel og meget synlig.

### Fase 4 — Turneringer for andre sportsgrene

- Puljer, slutspil, kampprogram, baner og haller, dommere og resultater.
- Genbruger haller og tidsplanlægning fra opvarmningsplanlæggeren.
- Mobilvisningen viser kampe, resultater og "gik vi videre?" live.
- Undersøg først de turneringsværktøjer, der allerede findes. Vores styrke er
  koblingen mellem hold, haller, opvarmning og program.

## GDPR undervejs

| Fase | Hvad skal på plads |
|---|---|
| 0–1 | Intet krav. Alt ligger i browseren. To små linjer i "Om data" (se fase 1). |
| 2 | Dataansvarlig udpeges. Databehandleraftale med hosting, data i EU, privatlivspolitik, adgangsstyring i selve databasen, log over ændringer, automatisk sletning af gamle stævner. Gennemgås af DGI's databeskyttelsesrådgiver eller en jurist. |
| 3 | Kun offentlige oplysninger om hold og tider. Ingen navne på personer. |
| 4 | Som fase 2. Resultater og kampprogrammer er normalt ikke personoplysninger. |

Det, der allerede er godt:

- Kontaktperson, e-mail og instruktører læses aldrig ind fra Excel.
- Ingen cookies, ingen sporing, intet hentes fra andre sider.
- Kommentarerne er det eneste følsomme. De handler næsten altid om gengangere
  og tidspunkter (én kommentar ud af 70 nævnte et fornavn). STAP kunne bede
  foreningerne om ikke at skrive navne i feltet.

## Beslutninger, der skal tages før fase 2

1. Hvem ejer systemet og betaler for drift: os, DGI eller en virksomhed?
2. Hvem er dataansvarlig? Det følger normalt ejerskabet.
3. Hvem hjælper brugerne, når noget driller, fx dagen før et stævne?
4. Skal kommentarerne med op på serveren, eller kun ligge lokalt?

## Åbne spørgsmål

- Skal flere arbejde i planen på samme tid fra start, eller er det nok, at én
  ad gangen gemmer og giver videre? (Brugerne har sagt: på samme tid.)
- Skal mange forskellige foreninger dele med hinanden, eller kun inden for et
  DGI-område?
- Hvilke sportsgrene og turneringsformer er de første, hvis fase 4 bliver
  til noget?
