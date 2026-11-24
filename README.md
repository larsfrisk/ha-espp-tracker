# Portföljtracker för Home Assistant

Följ dina aktier dagligen i SEK: Hitachi ESPP, aktier på Stockholmsbörsen och andra börser som Yahoo Finance har.
En **portföljöversikt** med totalt värde, dagens förändring (uppdelad i kurs och valuta), vinst och andel per innehav,
och en **sida per aktie** med värde, orealiserad och realiserad vinst, ett diagram med vyn *Idag* (15 minuters
upplösning) och historik från ditt första köp. Köp och försäljningar läggs in för hand i efterhand.
Vinst vid försäljning räknas med genomsnittsmetoden. Det är uppföljning, inte skatteunderlag.

Kurser: Yahoo Finance (inofficiellt API) och ECB-kurser via Frankfurter, hämtade en gång per dag (16:30 lokal tid).
Appen loggar aldrig in hos din bank eller förvaltare.

## Installera i Home Assistant (HAOS/Supervised)

1. Inställningar > Appar > Installera app. Öppna menyn uppe till höger, välj repositories och lägg till
   `https://github.com/larsfrisk/ha-espp-tracker`
2. Välj **Portföljtracker** i listan, tryck **Installera** och sedan **Start**.
3. Slå på **Visa i sidopanelen** så dyker **Portfölj** upp i menyn.
4. Välj **+ Lägg till aktie**, sök (t.ex. "Volvo") eller skriv symbolen (`VOLV-B.ST`), och lägg in dina köp.

Data sparas i appens egen datamapp och följer med i Home Assistants säkerhetskopior.

## Sensorer

`sensor.portfolio_value`, `portfolio_day_change`, `portfolio_day_change_pct`, `portfolio_unrealized_gain`,
`portfolio_realized_gain`, `portfolio_total_gain`, `portfolio_cost`, samt per aktie `sensor.<prefix>_value`,
`_day_change`, `_unrealized_gain`, `_realized_gain`, `_price` m.fl. (prefix `espp` för Hitachi, `holding_<namn>` för övriga).
Skickas var 15:e minut från sparade kurser. Appen har `homeassistant_api: true`, vilket ger den
administratörsliknande åtkomst till HA:s API.

## Köra utanför Home Assistant

```
python3 espp_tracker/app.py            # http://127.0.0.1:8765
python3 espp_tracker/app.py --report   # daglig sammanfattning i terminalen
python3 espp_tracker/app.py --demo     # påhittade kurser och innehav för att prova
```

Kräver bara Python 3.9+. Data sparas i `espp_tracker/data/` (ligger i `.gitignore`).

## Känt

- Yahoo Finances API är inofficiellt och kan ändras. Misslyckas hämtningen visas senast sparade kurser.
- Aktier som noteras i delenheter (t.ex. brittiska pence) stöds inte än.
- Ändra hämtningstid i `data/config.json` (`update_time`).
