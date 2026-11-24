# ESPP-tracker

Följ ditt Hitachi-innehav (ESPP) i SEK. Öppna **ESPP** i sidopanelen och lägg in dina köp och försäljningar
(datum, antal, belopp) från JP Morgans transaktionshistorik.

Kurser hämtas från Yahoo Finance (6501.T, JPY) och ECB-kurser (JPY/SEK) var 15:e minut.
Köpen sparas i appens egen datamapp och följer med i Home Assistants säkerhetskopior.

## Sensorer i Home Assistant

`sensor.espp_value`, `sensor.espp_day_change`, `sensor.espp_day_change_pct`,
`sensor.espp_unrealized_gain`, `sensor.espp_unrealized_gain_pct`, `sensor.espp_realized_gain`, `sensor.espp_total_gain`, `sensor.espp_cost`,
`sensor.espp_shares`, `sensor.espp_price` och `sensor.espp_fx`.

Sensorerna skapas när appen startar och uppdateras var 15:e minut. De saknas tills
du lagt in minst ett köp (utom kurs och växelkurs).
