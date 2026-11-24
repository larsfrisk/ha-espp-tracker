# Ändringslogg

Alla märkbara ändringar i ESPP-tracker dokumenteras här. Formatet följer
[Keep a Changelog](https://keepachangelog.com/sv/1.1.0/) och versionerna följer
[semantisk versionering](https://semver.org/lang/sv/).

## [2.0.0] - 2026-11-24

### Tillagt
- Flera aktier: lägg till bolag från Stockholmsbörsen (t.ex. `VOLV-B.ST`) eller andra börser via sök eller symbol. Valutan hämtas från Yahoo Finance och räknas om till SEK med ECB-kurser (SEK-aktier behöver ingen omräkning).
- Sida per aktie med allt som Hitachi hade: värde, dagens utveckling, orealiserad/realiserad vinst, diagram med vyn Idag (15 minuter), transaktioner och formulär.
- Portföljöversikt: totalt värde, dagens förändring (uppdelad i kurs och valuta), vinst, tabell över innehav med andel av portföljen, och diagram över hela portföljens värde över tid.
- Möjlighet att ta bort en aktie och dess transaktioner.
- Sensorer för hela portföljen (`sensor.portfolio_*`) och för varje aktie (`sensor.holding_<namn>_*`).

### Ändrat
- Appen heter nu Portföljtracker (sidopanelen: Portfölj). Slug och data är oförändrade, så din installation uppdateras på plats.
- Ditt befintliga Hitachi-innehav och alla transaktioner flyttas automatiskt över vid första starten. Hitachis sensorer behåller namnen `sensor.espp_*`.
- `name`, `symbol` och `price_ccy` i `/data/config.json` används bara för den automatiska överflyttningen. Aktier hanteras nu i appen.
- Kurser hämtas och sparas per aktie.

## [1.2.0] - 2026-11-24

### Tillagt
- Intradagsvy "Idag" med 15 minuters upplösning: värdet av innehavet under senaste handelsdag mot föregående stängning. Under pågående handel uppdateras den automatiskt var 15:e minut medan sidan är öppen.
- Intradagskurser hämtas när du öppnar vyn och sparas i 15 minuter under handel (60 minuter när börsen är stängd).

### Ändrat
- "Idag" är förvald i diagrammet. Historiken (1 mån till Allt) hämtas som tidigare i sin helhet från första köpet och uppdateras en gång per dag.
- Intradagsdiagrammet använder senaste ECB-kurs hela dagen, eftersom valutakursen bara finns som dagskurs.

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
