# Ändringslogg

Alla märkbara ändringar i ESPP-tracker dokumenteras här. Formatet följer
[Keep a Changelog](https://keepachangelog.com/sv/1.1.0/) och versionerna följer
[semantisk versionering](https://semver.org/lang/sv/).

## [2.8.2] - 2026-11-25

### Ändrat
- Rutan Aktiekurs på innehavets sida visar nu dagens förändring i både kronor och procent (t.ex. "+2,10 SEK (+1,27 %) idag · kl 17:25"), beräknad mot föregående stängning med dagens intradagsdata, alltså samma bas som diagrammet. Finns ingen intradagsdata används senaste dagskursen, och då anges datumet. Efter stängning visas "idag (stängd)".

## [2.8.1] - 2026-11-25

### Rättat
- Tiderna för "hämtad" och "nästa automatiska hämtning" visas nu i webbläsarens tidszon (tidigare serverns, som kunde vara UTC).
- "Föregående stängning" i dagsdiagrammet tas nu från föregående handelsdag i intradagsdatan när dagskurserna saknar den dagen. Tidigare kunde diagrammet jämföra med en dags gammal stängning, så att procenten i diagrammet och i rutan Aktiekurs inte stämde överens.
- Procenten i rutan Aktiekurs och valutarutan anger nu vilken dag den gäller ("idag" eller datumet) i stället för alltid "idag".

## [2.8.0] - 2026-11-25

### Tillagt
- Skalan till höger (kurs per aktie och % mot periodens start) finns nu för alla perioder: 1 mån, 3 mån, 6 mån och Allt. Kursen ritas som en egen orange linje mot högerskalan, vid sidan av värdet i kronor på vänsterskalan.
- Etiketterna ovanför diagrammet visar nu kurs och procent, och hovertexten visar kursens procentuella förändring.

## [2.7.2] - 2026-11-25

### Tillagt
- Skalan till höger i dagsdiagrammet visar nu även procent mot föregående stängning (grön över, röd under), bredvid kursen per aktie. För bevakade aktier utan innehav visas bara procent.

### Rättat
- Skalan till vänster visar decimaler när intervallet är litet, så att man inte får samma tal flera gånger (t.ex. 124, 124).

## [2.7.1] - 2026-11-25

### Tillagt
- Dagsdiagrammet (Idag) har en skala till höger med kurs per aktie (t.ex. JPY), förutom värdet i kronor till vänster. Skalorna följer varandra eftersom valutakursen är fast under dagen.
- Den streckade linjen för föregående stängning har nu en text med kursen per aktie och värdet, till exempel "Föregående stängning 4 974,00 JPY (6 721 SEK)".

## [2.7.0] - 2026-11-25

### Tillagt
- Intradagsbacktest under "Signaler under dagen": kör samma sex regler på 1, 5 och 15 minuters historik (Yahoo ger ca 7 dagar för 1 min och ca en månad för 5 och 15 min) och jämför före och efter kostnad. Du anger kostnad per affär (courtage + spread), och resultatet jämförs med att bara äga under handelstid. Köp sker en stapel efter signalen och ingen position hålls över natten.

## [2.6.1] - 2026-11-24

### Ändrat
- Sektionerna "Signaler under dagen" och "Nyckeltal och tekniska signaler" kan fällas ihop och ut med **Visa detaljer / Dölj detaljer**. I hopfällt läge visas bara rubriken och den samlade signalen. Standard är hopfälld, och valet kommer ihåg i webbläsaren.

## [2.6.0] - 2026-11-24

### Tillagt
- Signalkolumn på Översikt: för varje innehav och bevakad aktie visas en symbol med den samlade tekniska signalen (▲ Köp, ▼ Sälj eller ■ Neutral) och poängen. Det är mekaniska regler, inte personlig rådgivning.

## [2.5.1] - 2026-11-24

### Rättat
- Aktier du bevakar men inte äger (inga transaktioner) visade ett diagram med värdet 0. Nu ritas kursen i aktiens valuta, både i vyn Idag och för 1 mån till Allt.

## [2.5.0] - 2026-11-24

### Tillagt
- Signaler under dagen i vyn Idag: sex regler på dagens staplar (EMA9/EMA21, kurs mot VWAP, MACD, RSI, Bollingerband, kurs mot dagens öppning), en samlad signal och en lista över när signalen bytte under dagen. Följer vald upplösning (1, 5 eller 15 minuter).
- Dagens VWAP (volymvägd snittkurs) räknas från Yahoos volymdata.
- Varning om att Yahoo ofta fördröjer svenska kurser ca 15 minuter och att daytrading är riskfylld. Signalerna är inte personlig rådgivning.

## [2.4.0] - 2026-11-24

### Tillagt
- Nyckeltal och tekniska signaler på varje aktie- och fondsida: avkastning (1 dag till 12 månader), 52-veckors högsta/lägsta, volatilitet, största nedgång, medelvärden (SMA20/50/200) och RSI.
- Sex regelbaserade "robothandelssignaler" (trend mot SMA200, SMA50/200-korsning, MACD, RSI, Bollingerband, 6 månaders momentum) som vägs ihop till en samlad signal: köpsignal, säljsignal eller neutral.
- Backtest som visar hur tre enkla regler hade fungerat på kursens historia jämfört med att bara äga (utan courtage, skatt och utdelningar).
- Kurshistorik på cirka tre år hämtas en gång per dag för beräkningarna.
- Tydlig varning på sidan: signalerna är mekaniska regler, inte personlig investeringsrådgivning.

## [2.3.0] - 2026-11-24

### Tillagt
- Inställning på huvudsidan (Översikt): välj upplösning i dagsdiagrammet, 1, 5 eller 15 minuter. Ingen JSON-fil behöver redigeras längre.

## [2.2.0] - 2026-11-24

### Tillagt
- Högre upplösning i dagsdiagrammet: sätt `intraday_interval` i `/data/config.json` till `"1m"`, `"5m"` eller `"15m"` (standard). Vid `1m` hämtas en ny stapel varje minut under pågående handel och sidan uppdateras automatiskt lika ofta.

## [2.1.2] - 2026-11-24

### Rättat
- Klockslagen i dagsdiagrammet (Idag) visas nu i webbläsarens tidszon i stället för serverns. Tidigare kunde de vara en timme fel (UTC i stället för svensk tid) om tidszonen i Home Assistants system inte var satt till Europe/Stockholm.

## [2.1.1] - 2026-11-24

### Tillagt
- Byt namn på ett innehav: knappen **Byt namn** på aktiens/fondens sida, så att till exempel en fond visas som "Avanza Zero" i stället för symbolen `0P0001BM0Y.ST`.
- Valfritt namnfält när du lägger till en symbol direkt.

## [2.1.0] - 2026-11-24

### Tillagt
- Fonder: lägg till fonder du köper via Avanza, Skandia eller annan förvaltare. Sök på fondens namn eller ISIN (t.ex. `SE0001718388`) så slås den upp hos Yahoo Finance, som har många svenska fonder med Morningstar-symboler (`0P…​.ST`). Fonder får en egen sida och ingår i portföljöversikten och sensorerna i Home Assistant.
- Manuella fonder: finns inte fonden hos Yahoo (t.ex. vissa Skandia-fonder) lägger du till den manuellt och skriver själv in NAV (andelskurs) med datum. Värdet räknas med senast inlagda NAV. NAV kan tas bort igen.
- Sökresultaten visar om träffen är aktie, ETF eller fond.

### Ändrat
- Fondsidor visar "andelar" och "NAV" i stället för aktier och kurs, och har ingen vy Idag (fonder har bara en kurs per dag).

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
