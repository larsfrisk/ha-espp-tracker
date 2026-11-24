# ESPP-tracker för Home Assistant

Följ ditt Hitachi-innehav (ESPP) dagligen i SEK: värde, förändring sedan igår (uppdelat i aktiekurs och
valuta), orealiserad och realiserad vinst. Köp och försäljningar läggs in för hand i efterhand.
Vinst vid försäljning räknas med genomsnittsmetoden. Det är uppföljning, inte skatteunderlag.

Kurser: Yahoo Finance (6501.T, JPY, inofficiellt API) och ECB-kurser via Frankfurter (JPY/SEK).
Appen loggar aldrig in hos din bank eller förvaltare och har ingen kontakt med JP Morgan.

## Installera i Home Assistant (HAOS/Supervised)

1. Inställningar > Appar > Installera app. Öppna menyn uppe till höger, välj repositories och lägg till
   `https://github.com/larsfrisk/ha-espp-tracker`
2. Välj **ESPP-tracker** i listan, tryck **Installera** och sedan **Start**.
3. Slå på **Visa i sidopanelen** så dyker **ESPP** upp i menyn.

Köpen sparas i appens egen datamapp och följer med i Home Assistants säkerhetskopior.

## Sensorer

`sensor.espp_value`, `espp_day_change`, `espp_day_change_pct`, `espp_unrealized_gain`,
`espp_unrealized_gain_pct`, `espp_realized_gain`, `espp_total_gain`, `espp_cost`, `espp_shares`,
`espp_price`, `espp_fx`. Uppdateras var 15:e minut. Appen har `homeassistant_api: true`, vilket ger den
administratörsliknande åtkomst till HA:s API.

## Köra utanför Home Assistant

```
python3 espp_tracker/app.py            # http://127.0.0.1:8765
python3 espp_tracker/app.py --report   # daglig sammanfattning i terminalen
python3 espp_tracker/app.py --demo     # påhittade kurser för att prova
```

Kräver bara Python 3.9+. Data sparas i `espp_tracker/data/` (ligger i `.gitignore`).

## Känt

- Yahoo Finances chart-API är inofficiellt och kan ändras. Misslyckas hämtningen visas senast sparade kurser.
- Ändra aktie eller valuta i `data/config.json` (`symbol`, `price_ccy`, `home_ccy`).
