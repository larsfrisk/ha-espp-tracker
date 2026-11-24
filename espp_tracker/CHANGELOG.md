# Ändringslogg

Alla märkbara ändringar i ESPP-tracker dokumenteras här. Formatet följer
[Keep a Changelog](https://keepachangelog.com/sv/1.1.0/) och versionerna följer
[semantisk versionering](https://semver.org/lang/sv/).

## [1.1.1] - 2026-11-24

### Tillagt
- Ändringslogg som visas i Home Assistant (fliken Changelog på appen).

## [1.1.0] - 2026-11-24

### Ändrat
- Kurserna hämtas nu en gång per dag (kl 16:30 lokal tid, efter Tokyo-stängning och ECB:s dagskurser) i stället för var 15:e minut.
- Diagrammet har en punkt per handelsdag med avslutad stängningskurs. Pågående handelsdag tas bort.
- Sensorerna skickas fortfarande var 15:e minut, men från sparade kurser utan ny hämtning.

### Tillagt
- Appen visar när nästa automatiska hämtning sker.
- Hämtningstiden kan ändras med `update_time` i `/data/config.json`.
- `.gitignore` för `data/` och `__pycache__/`.

## [1.0.0] - 2026-11-24

### Tillagt
- Första versionen: värde av Hitachi-innehavet (6501.T) i SEK med förändring sedan föregående handelsdag, uppdelad i aktiekurs och valuta.
- Köp och försäljningar registreras för hand. Vinst vid försäljning räknas med genomsnittsmetoden, med orealiserad och realiserad vinst.
- Diagram över värde mot anskaffningsvärde, med val av tidsintervall och tabellvy.
- Sensorer till Home Assistant (värde, dagens förändring, vinst, kurs, växelkurs m.fl.).
- Visas i sidopanelen via ingress.
