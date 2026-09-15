# Skattjaktens hamn - funktionskatalog

Senast uppdaterad: 2026-09-15

Detta dokument samlar portalens funktioner och viktiga förändringar. Portalen är en svensk, cartoonish piratportal byggd med Flask och SQLite.

## Funktioner

### Medlemskap och inloggning

- Medlemmar kan registrera konto och logga in.
- Lösenord lagras hashade med Werkzeug.
- Den första användaren blir admin.
- Om databasen saknar admin uppgraderas den första användaren automatiskt.
- Roller: `member`, `moderator` och `admin`.

### Skattjakter

- Medlemmar kan skapa skattjakter med titel, sammanfattning, berättelse, plats och svårighetsgrad.
- Skattjakter skickas först som `pending` för granskning.
- Publicerade skattjakter visas på startsidan.
- Detaljsidan visar bild, innehåll och diskussion.

### Bilduppladdning

- Medlemmar kan ladda upp JPG, JPEG, PNG eller WebP.
- Maximal filstorlek är 5 MB.
- Filnamn saneras innan filen sparas.
- Bilder kan även anges med extern bild-URL.
- Uppladdade bilder serveras via `/uploads/<filename>`.
- Lokala uppladdningar ignoreras av Git via `static/uploads/`.

### Redigering och återinsändning

- Ägare kan redigera sina egna utkast, avvisade och publicerade skattjakter.
- Redigering behåller samma jakt-ID och ägare.
- När en ändring sparas sätts status till `pending` igen.
- Medlemmar kan inte redigera andras skattjakter.
- Väntande och hittade skattjakter kan inte redigeras av medlemmen.

### Verifiering och hittade skatter

- Skaparen anger en verifieringskod när skattjakten skapas.
- Koden lagras hashad och visas aldrig publikt.
- Inloggade medlemmar kan skriva in en kod på skattjaktens detaljsida.
- Koden jämförs skiftlägesokänsligt efter att omgivande blanksteg tagits bort.
- Vid rätt kod ändras status till `found`, vilket visas som `Hittad!`.
- Skattjakten tas då bort från listan över aktiva publicerade skatter och arkiveras.
- Arkivet sparar vem som hittade skatten, när den hittades och hur många sekunder det tog från publicering.
- En skatt som redan är hittad kan inte registreras av en andra person.

### Lägerelden

- Inloggade medlemmar kan kommentera publicerade skattjakter.
- Kommentarer visas på skattjaktens detaljsida och i lägereldsflödet.

### Administration

- Admin och moderator kan öppna Skeppets kansli.
- Moderatorer och admins kan publicera eller avvisa skattjakter.
- Admin kan administrera användare och ändra roller.
- Den sista admin-användaren kan inte avsättas.
- Admin och moderator kan läsa granskningsloggen.

## Granskningsflöde

```text
Medlem skapar jakt
        |
        v
    pending
      /   \
     /     \
published  rejected
               |
               v
       medlem redigerar
               |
               v
            pending
```

## Roller

| Roll | Behörighet |
| --- | --- |
| `member` | Skapa, redigera egna utkast/avvisade jakter och kommentera |
| `moderator` | Granska, publicera och avvisa skattjakter; läsa granskningslogg |
| `admin` | Moderatorbehörighet samt administrera användarroller |

## Granskningslogg

Tabellen `moderation_logs` sparar varje publicerings- och avvisningsbeslut med:

- skattjaktens ID
- beslutande användares ID och användarnamn
- åtgärd: `published` eller `rejected`
- valfri notering
- tidsstämpel

Loggen visas på `/admin/moderation-log` och har ingen borttagningsfunktion i webbappen.

## Viktiga routes

| Route | Syfte |
| --- | --- |
| `/` | Publik startsida |
| `/login` | Inloggning |
| `/register` | Medlemsregistrering |
| `/dashboard` | Medlemmens loggbok och egna skattjakter |
| `/dashboard/create` | Skapa skattjakt |
| `/dashboard/edit/<id>` | Redigera och skicka in igen |
| `/campfire` | Publikt lägereldsflöde |
| `/treasure/<id>` | Skattjaktens detaljsida |
| `/admin` | Skeppets kansli |
| `/admin/users` | Användaradministration |
| `/admin/moderation-log` | Granskningshistorik |

## Ändringshistorik

### Issue #1 - Riktiga bilduppladdningar

- Lade till säker filuppladdning.
- Lade till filtyp- och storlekskontroll.
- Behöll stöd för bild-URL som fallback.
- Lade till tester för godkänd och avvisad filtyp.

### Issue #2 - Redigera utkast

- Lade till redigeringssida för medlemmens egna utkast och avvisade jakter.
- Lade till ägar- och statuskontroller.
- Lade till återinsändning till modereringskön.
- Lade till tester för behörighet och bibehållet jakt-ID.

### Issue #3 - Granskningslogg

- Lade till append-only-tabellen `moderation_logs`.
- Loggar publicering och avvisning med aktör och tidsstämpel.
- Lade till adminvyn för granskningshistorik.
- Lade till tester för båda modereringsbesluten.

### Verifiering av hittad skatt

- Lade till verifieringskod för nya skattjakter.
- Lade till `found`-status och fyndmetadata i databasen.
- Lade till kodkontroll och tidsmätning från publicering till fynd.
- Lade till skydd mot fel kod och dubbla fynd.

## Verifiering

Kör testsviten med projektets virtuella miljö:

```powershell
.venv\\Scripts\\python.exe -m pytest -q
```

Senast verifierat resultat: `10 passed`.