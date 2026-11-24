# Portföljtracker

Följ dina aktier i SEK: en **översikt** för hela portföljen och en **sida per aktie** med värde,
dagens utveckling, orealiserad och realiserad vinst. Öppna **Portfölj** i sidopanelen.

## Lägga till aktier

Välj **+ Lägg till aktie**, sök på bolagsnamn eller skriv symbolen direkt. Stockholmsbörsen har
suffixet `.ST`, till exempel `VOLV-B.ST`, `INVE-B.ST` eller `ERIC-B.ST`. Hitachi är `6501.T`.
Andra börser fungerar om Yahoo Finance har dem och valutan kan räknas om till kronor (ECB-kurser).
Sedan lägger du in dina köp och försäljningar (datum, antal, belopp) för hand på aktiens sida.
Vinst vid försäljning räknas med genomsnittsmetoden.

## Fonder (Avanza, Skandia m.fl.)

Välj **+ Lägg till aktie/fond** och sök på fondens namn eller **ISIN**. Yahoo Finance har många svenska
fonder (symboler som `0P00005U1J.ST`), och då hämtas NAV automatiskt en gång per dag, precis som aktier.
Avanza och Skandia har inget öppet API, så fonder som Yahoo saknar läggs till under
**Lägg till fond manuellt**: du skriver själv in NAV (andelskurs) och datum på fondens sida.
Köp och sälj läggs in som vanligt (antal andelar och belopp). Fonder har ingen vy Idag.

## Kurser

Historiken (stängningskurser från ditt första köp) hämtas en gång per dag kl 16:30, efter att Tokyo-börsen
stängt och ECB publicerat dagens valutakurser. Vyn **Idag** på en aktie visar senaste handelsdag med
15 minuters upplösning. Knappen "Hämta kurser nu" tvingar fram en hämtning.
Tiden kan ändras med `update_time` i `/data/config.json`. Upplösningen i vyn Idag styrs av `intraday_interval`
(`"1m"`, `"5m"` eller `"15m"`, standard `"15m"`). Observera att Yahoo ofta fördröjer svenska kurser ca 15 minuter.

## Sensorer i Home Assistant

Sensorerna skickas var 15:e minut från sparade kurser (inget nytt hämtas då).

- Hela portföljen: `sensor.portfolio_value`, `portfolio_day_change`, `portfolio_day_change_pct`,
  `portfolio_unrealized_gain`, `portfolio_realized_gain`, `portfolio_total_gain`, `portfolio_cost`.
- Varje aktie: `sensor.<prefix>_value`, `_day_change`, `_day_change_pct`, `_unrealized_gain`,
  `_unrealized_gain_pct`, `_realized_gain`, `_total_gain`, `_cost`, `_shares`, `_price` och `_fx`.
  Prefixet är `espp` för Hitachi (som förut) och `holding_<namn>` för aktier du lägger till,
  till exempel `sensor.holding_volvo_ab_ser_b_value`.
