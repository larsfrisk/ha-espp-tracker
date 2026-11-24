# ESPP-tracker

Följ ditt Hitachi-innehav (ESPP) i SEK. Öppna **ESPP** i sidopanelen och lägg in dina köp och försäljningar
(datum, antal, belopp) från JP Morgans transaktionshistorik.

Kurser hämtas från Yahoo Finance (6501.T, JPY) och ECB-kurser (JPY/SEK) en gång per dag (kl 16:30, efter Tokyo-stängning och ECB:s dagskurser).
Köpen sparas i appens egen datamapp och följer med i Home Assistants säkerhetskopior.

## Sensorer i Home Assistant

`sensor.espp_value`, `sensor.espp_day_change`, `sensor.espp_day_change_pct`,
`sensor.espp_unrealized_gain`, `sensor.espp_unrealized_gain_pct`, `sensor.espp_realized_gain`, `sensor.espp_total_gain`, `sensor.espp_cost`,
`sensor.espp_shares`, `sensor.espp_price` och `sensor.espp_fx`.

Sensorerna skapas när appen startar och uppdateras en gång per dag (kl 16:30, efter Tokyo-stängning och ECB:s dagskurser). De saknas tills
du lagt in minst ett köp (utom kurs och växelkurs).

Diagrammet har en punkt per handelsdag (avslutad stängningskurs). Tiden kan ändras med `update_time` i `/data/config.json`. Knappen "Hämta kurser nu" tvingar en hämtning.

Vyn **Idag** visar senaste handelsdag med 15 minuters upplösning (kurs från Yahoo Finance, valuta fast på senaste ECB-kurs). Historiken hämtas hela vägen från ditt första köp.
