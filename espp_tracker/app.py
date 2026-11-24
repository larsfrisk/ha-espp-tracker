#!/usr/bin/env python3
"""ESPP-tracker: följ ditt Hitachi-innehav (ESPP) dagligen i SEK.

Kör:        python3 app.py                -> dashboard på http://127.0.0.1:8765
Rapport:    python3 app.py --report       -> text-sammanfattning (för cron / Home Assistant)
Demo:       python3 app.py --demo         -> syntetiska kurser, ingen internetåtkomst behövs

Endast Python 3.9+ standardbibliotek. Dina köp sparas i data/lots.json.
Kurser: Yahoo Finance (inofficiellt chart-API). Valuta: Frankfurter (ECB-kurser).
"""
import argparse
import datetime as dt
import json
import math
import os
import random
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("ESPP_DATA_DIR") or os.path.join(BASE, "data")
INGRESS = os.environ.get("ESPP_INGRESS") == "1"        # körs som Home Assistant-tillägg
INGRESS_PEER = "172.30.32.2"                           # Supervisorns ingress-gateway
LOTS_FILE = os.path.join(DATA_DIR, "lots.json")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
CACHE_FILE = os.path.join(DATA_DIR, "cache.json")
INDEX_FILE = os.path.join(BASE, "index.html")

DEFAULT_CONFIG = {
    "name": "Hitachi, Ltd.",
    "symbol": "6501.T",      # Tokyo Stock Exchange. Ändra om dina aktier är t.ex. ADR/OTC.
    "price_ccy": "JPY",      # valutan aktien handlas i
    "home_ccy": "SEK",       # valutan du vill se värdet i
    "update_time": "16:30",   # daglig kurshämtning (lokal tid), efter Tokyo-stängning och ECB-kurser
    "publish_minutes": 15,    # hur ofta sensorer skickas till HA (använder sparade kurser, hämtar inget nytt)
}

DEMO = False
LOCK = threading.Lock()


# ---------------------------------------------------------------- lagring

def _read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(_read_json(CONFIG_FILE, {}))
    return cfg


def load_lots():
    return _read_json(LOTS_FILE, [])


def save_lots(lots):
    _write_json(LOTS_FILE, lots)


# ---------------------------------------------------------------- datakällor

def _http_json(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 espp-tracker"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_prices(symbol, start):
    """Dagliga stängningskurser {YYYY-MM-DD: pris} + meta, från Yahoo Finance."""
    p1 = int(dt.datetime.combine(start, dt.time()).timestamp())
    p2 = int(time.time()) + 86400
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/%s?period1=%d&period2=%d&interval=1d"
           % (urllib.parse.quote(symbol), p1, p2))
    res = _http_json(url)["chart"]["result"][0]
    off = res["meta"].get("gmtoffset", 0)
    closes = res["indicators"]["quote"][0]["close"]
    out = {}
    for ts, c in zip(res["timestamp"], closes):
        if c is None:
            continue
        d = dt.datetime.fromtimestamp(ts + off, dt.timezone.utc).date().isoformat()
        out[d] = float(c)
    # Pågående handelsdag tas bort: diagrammet har en avslutad stängningskurs per dag
    reg = res["meta"].get("currentTradingPeriod", {}).get("regular", {})
    if reg.get("start") and reg.get("end") and time.time() < reg["end"]:
        out.pop(dt.datetime.fromtimestamp(reg["start"] + off, dt.timezone.utc).date().isoformat(), None)
    return out, {"currency": res["meta"].get("currency"), "exchange": res["meta"].get("exchangeName")}


def fetch_fx(base, quote, start):
    """Dagliga ECB-kurser {datum: kurs} för 1 base = x quote, från Frankfurter."""
    if base == quote:
        return {}
    url = "https://api.frankfurter.dev/v1/%s..?base=%s&symbols=%s" % (start.isoformat(), base, quote)
    rates = _http_json(url)["rates"]
    return {d: float(v[quote]) for d, v in rates.items()}


def demo_data(start):
    rnd = random.Random(42)
    prices, fx = {}, {}
    d, p, r = start, 4200.0, 0.0680
    while d <= dt.date.today():
        if d.weekday() < 5:
            p *= math.exp(rnd.gauss(0.0004, 0.014))
            r *= math.exp(rnd.gauss(0.0, 0.003))
            prices[d.isoformat()] = round(p, 1)
            fx[d.isoformat()] = round(r, 5)
        d += dt.timedelta(days=1)
    return prices, fx, {"currency": "JPY", "exchange": "DEMO"}


def _hhmm(cfg):
    try:
        h, m = map(int, str(cfg.get("update_time", "16:30")).split(":"))
        assert 0 <= h < 24 and 0 <= m < 60
        return h, m
    except Exception:
        return 16, 30


def last_due(now_ts, cfg):
    """Senaste planerade uppdateringstidpunkten (epoch)."""
    h, m = _hhmm(cfg)
    now = dt.datetime.fromtimestamp(now_ts)
    due = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if due > now:
        due -= dt.timedelta(days=1)
    return due.timestamp()


def next_due(now_ts, cfg):
    h, m = _hhmm(cfg)
    return (dt.datetime.fromtimestamp(last_due(now_ts, cfg)) + dt.timedelta(days=1)).replace(hour=h, minute=m)


CACHE_VERSION = 2


def get_market(cfg, start):
    """Hämtar (med cache) kurser och valuta. Returnerar (prices, fx, meta, fetched_at, error)."""
    cache = _read_json(CACHE_FILE, {})
    now = time.time()
    key = (cfg["symbol"], cfg["price_ccy"], cfg["home_ccy"])
    fresh = (
        not DEMO
        and cache.get("key") == list(key)
        and cache.get("start", "9999") <= start.isoformat()
        and cache.get("v") == CACHE_VERSION
        and cache.get("fetched_at", 0) >= last_due(now, cfg)   # en hämtning per dag
    )
    if fresh:
        return cache["prices"], cache["fx"], cache["meta"], cache["fetched_at"], None
    if DEMO:
        p, f, m = demo_data(start)
        return p, f, m, now, None
    try:
        prices, meta = fetch_prices(cfg["symbol"], start)
        fx = fetch_fx(cfg["price_ccy"], cfg["home_ccy"], start - dt.timedelta(days=7))
        _write_json(CACHE_FILE, {"v": CACHE_VERSION, "key": list(key), "start": start.isoformat(), "fetched_at": now,
                                 "prices": prices, "fx": fx, "meta": meta})
        return prices, fx, meta, now, None
    except Exception as e:  # nätverk, ändrat API, osv.
        if cache.get("key") == list(key) and cache.get("prices"):
            return cache["prices"], cache["fx"], cache["meta"], cache["fetched_at"], \
                "Kunde inte hämta nya kurser (%s). Visar senast sparade." % e
        return {}, {}, {}, now, "Kunde inte hämta kurser: %s" % e


# ---------------------------------------------------------------- beräkning

class Series:
    """Sorterad serie med 'senaste värde på eller före datum'."""

    def __init__(self, d):
        self.keys = sorted(d)
        self.d = d

    def at(self, date_s):
        lo, hi = 0, len(self.keys)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.keys[mid] <= date_s:
                lo = mid + 1
            else:
                hi = mid
        if lo == 0:
            return self.d[self.keys[0]] if self.keys else None  # före första datapunkt
        return self.d[self.keys[lo - 1]]


def compute(lots, cfg, prices, fx):
    home, pccy = cfg["home_ccy"], cfg["price_ccy"]
    if not prices:
        return None
    P = Series(prices)
    F = Series(fx) if pccy != home else None
    rate = (lambda d: F.at(d)) if F else (lambda d: 1.0)

    dates = P.keys
    last_d = dates[-1]
    prev_d = dates[-2] if len(dates) > 1 else dates[-1]
    p1, p0 = prices[last_d], prices[prev_d]
    r1, r0 = rate(last_d), rate(prev_d)

    # Genomsnittsmetoden: kostnaden per aktie är snittet av allt du köpt och inte sålt.
    events = sorted(lots, key=lambda x: (x["date"], 0 if x.get("type", "buy") == "buy" else 1))
    held = cost_held = realized = 0.0
    rows, timeline = [], []
    for l in events:
        sh, d = float(l["shares"]), l["date"]
        if l.get("type", "buy") == "buy":
            if l.get("paid") is not None:
                amt, src = float(l["paid"]), "inbetalt"
            else:
                amt, src = sh * (float(l["price"]) if l.get("price") else P.at(d)) * rate(d), "kurs"
            held += sh
            cost_held += amt
            rows.append({"id": l["id"], "date": d, "type": "buy", "shares": sh, "note": l.get("note", ""),
                         "amount": amt, "amount_src": src, "gain": None, "gain_pct": None})
        else:
            sh = min(sh, held)
            avg = cost_held / held if held else 0.0
            cost_sold = avg * sh
            if l.get("received") is not None:
                amt, src = float(l["received"]), "mottaget"
            else:
                amt, src = sh * (float(l["price"]) if l.get("price") else P.at(d)) * rate(d), "kurs"
            gain = amt - cost_sold
            held -= sh
            cost_held -= cost_sold
            realized += gain
            if held < 1e-9:
                held = cost_held = 0.0
            rows.append({"id": l["id"], "date": d, "type": "sell", "shares": sh, "note": l.get("note", ""),
                         "amount": amt, "amount_src": src, "gain": gain,
                         "gain_pct": (gain / cost_sold * 100) if cost_sold else None})
        timeline.append((d, held, cost_held))

    value = held * p1 * r1
    unrealized = value - cost_held
    price_eff = held * (p1 - p0) * r0
    fx_eff = held * p1 * (r1 - r0)
    prev_value = held * p0 * r0

    # Historik: värde och anskaffningsvärde för kvarvarande aktier per dag
    history = []
    if timeline:
        first, i = timeline[0][0], 0
        h_now, c_now = 0.0, 0.0
        for d in dates:
            if d < first:
                continue
            while i < len(timeline) and timeline[i][0] <= d:
                _, h_now, c_now = timeline[i]
                i += 1
            history.append({"d": d, "value": h_now * prices[d] * rate(d), "invested": c_now, "price": prices[d]})

    return {
        "as_of": last_d, "prev": prev_d,
        "price": p1, "prev_price": p0, "fx": r1, "prev_fx": r0,
        "shares": held, "value": value, "cost": cost_held,
        "avg_cost": cost_held / held if held else None,
        "gain": unrealized,
        "gain_pct": (unrealized / cost_held * 100) if cost_held else None,
        "realized": realized, "total": unrealized + realized,
        "buys": sum(1 for r in rows if r["type"] == "buy"),
        "day": {"change": value - prev_value,
                "pct": (value / prev_value - 1) * 100 if prev_value else None,
                "price_effect": price_eff, "fx_effect": fx_eff,
                "price_pct": (p1 / p0 - 1) * 100 if p0 else None},
        "lots": rows, "history": history,
    }


def check_sequence(lots):
    """Kastar ValueError om du någon gång skulle sälja fler aktier än du äger."""
    held = 0.0
    for l in sorted(lots, key=lambda x: (x["date"], 0 if x.get("type", "buy") == "buy" else 1)):
        held += float(l["shares"]) if l.get("type", "buy") == "buy" else -float(l["shares"])
        if held < -1e-9:
            raise ValueError("Det skulle innebära att du säljer fler aktier än du äger per %s" % l["date"])


def build_summary():
    cfg = load_config()
    lots = load_lots()
    start = (min([dt.date.fromisoformat(l["date"]) for l in lots]) if lots
             else dt.date.today() - dt.timedelta(days=90)) - dt.timedelta(days=10)
    prices, fx, meta, fetched_at, err = get_market(cfg, start)
    summ = compute(lots, cfg, prices, fx)
    return {
        "config": cfg, "meta": meta, "demo": DEMO, "error": err,
        "fetched_at": dt.datetime.fromtimestamp(fetched_at).isoformat(timespec="seconds"),
        "summary": summ, "has_lots": bool(lots),
        "next_update": next_due(time.time(), cfg).isoformat(timespec="minutes"),
    }


# ---------------------------------------------------------------- lot-validering

def validate_lot(body):
    try:
        date = dt.date.fromisoformat(str(body.get("date", "")))
    except ValueError:
        raise ValueError("Ogiltigt datum (använd ÅÅÅÅ-MM-DD)")
    if date > dt.date.today():
        raise ValueError("Datumet ligger i framtiden")

    def num(key, required=False, positive=True):
        v = body.get(key)
        if v in (None, ""):
            if required:
                raise ValueError("Fältet '%s' saknas" % key)
            return None
        try:
            f = float(str(v).replace(",", ".").replace(" ", ""))
        except ValueError:
            raise ValueError("Ogiltigt tal i '%s'" % key)
        if not math.isfinite(f) or f < 0 or (positive and f == 0):
            raise ValueError("'%s' måste vara %s" % (key, "större än 0" if positive else "0 eller större"))
        return f

    typ = body.get("type", "buy")
    if typ not in ("buy", "sell"):
        raise ValueError("Ogiltig typ")
    shares = num("shares", required=True)
    price = num("price")
    lot = {"id": uuid.uuid4().hex[:8], "type": typ, "date": date.isoformat(), "shares": shares,
           "price": price, "note": str(body.get("note", ""))[:80]}
    lot["paid" if typ == "buy" else "received"] = num("paid" if typ == "buy" else "received", positive=False)
    return lot


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "ESPPTracker/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 10_000:
            raise ValueError("För stor förfrågan")
        return json.loads(self.rfile.read(n) or b"{}")

    def _allowed(self, write=False):
        """Åtkomstkontroll. Som HA-tillägg släpps bara ingress-gatewayen in."""
        if INGRESS:
            if self.client_address[0] != INGRESS_PEER:
                return False
            # JSON-innehåll kan inte skickas från andra webbsidor utan CORS-preflight
            return not write or self.command == "DELETE" or \
                self.headers.get("Content-Type", "").startswith("application/json")
        # Fristående: skydda mot att andra webbsidor skickar förfrågningar till den lokala appen
        origin = self.headers.get("Origin")
        return origin is None or urllib.parse.urlparse(origin).netloc == self.headers.get("Host")

    def do_GET(self):
        if not self._allowed():
            return self._send(403, {"error": "Otillåten förfrågan"})
        path = urllib.parse.urlparse(self.path)
        if path.path == "/":
            with open(INDEX_FILE, "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")
        if path.path == "/api/summary":
            qs = urllib.parse.parse_qs(path.query)
            if qs.get("refresh") and not DEMO:
                try:
                    os.remove(CACHE_FILE)
                except FileNotFoundError:
                    pass
            with LOCK:
                return self._send(200, build_summary())
        self._send(404, {"error": "Hittades inte"})

    def do_POST(self):
        if not self._allowed(write=True):
            return self._send(403, {"error": "Otillåten förfrågan"})
        if self.path == "/api/lots":
            try:
                lot = validate_lot(self._body())
            except (ValueError, json.JSONDecodeError) as e:
                return self._send(400, {"error": str(e)})
            with LOCK:
                lots = load_lots()
                lots.append(lot)
                try:
                    check_sequence(lots)
                except ValueError as e:
                    return self._send(400, {"error": str(e)})
                save_lots(lots)
            return self._send(201, lot)
        self._send(404, {"error": "Hittades inte"})

    def do_DELETE(self):
        if not self._allowed(write=True):
            return self._send(403, {"error": "Otillåten förfrågan"})
        if self.path.startswith("/api/lots/"):
            lid = self.path.rsplit("/", 1)[1]
            with LOCK:
                lots = load_lots()
                keep = [l for l in lots if l["id"] != lid]
                if len(keep) == len(lots):
                    return self._send(404, {"error": "Transaktionen finns inte"})
                try:
                    check_sequence(keep)
                except ValueError as e:
                    return self._send(409, {"error": "Kan inte ta bort: " + str(e)})
                save_lots(keep)
            return self._send(200, {"ok": True})
        self._send(404, {"error": "Hittades inte"})


# ---------------------------------------------------------------- Home Assistant-sensorer

def publish_to_ha():
    """Skickar sensorer till HA via Supervisorns proxy (kräver homeassistant_api: true)."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return
    data = build_summary()
    s, cfg = data["summary"], data["config"]
    if not s:
        return
    home, pc = cfg["home_ccy"], cfg["price_ccy"]
    sensors = {
        "espp_value": ("ESPP värde", s["value"], home, 0, "mdi:chart-line"),
        "espp_day_change": ("ESPP förändring idag", s["day"]["change"], home, 0, "mdi:trending-up"),
        "espp_day_change_pct": ("ESPP förändring idag %", s["day"]["pct"], "%", 2, "mdi:percent"),
        "espp_unrealized_gain": ("ESPP orealiserad vinst", s["gain"], home, 0, "mdi:cash-plus"),
        "espp_unrealized_gain_pct": ("ESPP orealiserad vinst %", s["gain_pct"], "%", 2, "mdi:percent"),
        "espp_realized_gain": ("ESPP realiserad vinst", s["realized"], home, 0, "mdi:cash-check"),
        "espp_total_gain": ("ESPP total vinst", s["total"], home, 0, "mdi:cash-multiple"),
        "espp_cost": ("ESPP anskaffningsvärde", s["cost"], home, 0, "mdi:cash"),
        "espp_shares": ("ESPP antal aktier", s["shares"], "st", 3, "mdi:numeric"),
        "espp_price": ("ESPP aktiekurs", s["price"], pc, 1, "mdi:currency-jpy"),
        "espp_fx": ("ESPP %s/%s" % (pc, home), s["fx"], None, 5, "mdi:swap-horizontal"),
    }
    for key, (name, val, unit, nd, icon) in sensors.items():
        if val is None:
            continue
        attrs = {"friendly_name": name, "icon": icon, "as_of": s["as_of"], "state_class": "measurement"}
        if unit:
            attrs["unit_of_measurement"] = unit
        req = urllib.request.Request(
            "http://supervisor/core/api/states/sensor." + key,
            data=json.dumps({"state": str(round(val, nd)), "attributes": attrs}).encode(),
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
            method="POST")
        try:
            urllib.request.urlopen(req, timeout=10).read()
        except Exception as e:
            print("Kunde inte publicera %s: %s" % (key, e), flush=True)


def publisher_loop():
    while True:
        try:
            with LOCK:
                publish_to_ha()
        except Exception as e:
            print("Publicering misslyckades: %s" % e, flush=True)
        time.sleep(load_config()["publish_minutes"] * 60)


# ---------------------------------------------------------------- rapport

def sek(x, sign=False):
    s = f"{x:,.0f}".replace(",", " ")
    return ("+" if sign and x > 0 else "") + s


def report():
    data = build_summary()
    s = data["summary"]
    if not s:
        print("Inga kurser tillgängliga. " + (data["error"] or ""))
        return 1
    cfg = data["config"]
    home = cfg["home_ccy"]
    d = s["day"]
    pct = lambda v: "–" if v is None else f"{v:+.2f} %"
    print(f"{cfg['name']} ({cfg['symbol']}) – {s['as_of']}")
    print(f"Kurs: {s['price']:,.1f} {cfg['price_ccy']} ({pct(d['price_pct'])})   "
          f"{cfg['price_ccy']}/{home}: {s['fx']:.5f}")
    print(f"Innehav: {s['shares']:g} aktier  =  {sek(s['value'])} {home}")
    print(f"Idag: {sek(d['change'], True)} {home} ({pct(d['pct'])})  "
          f"[kurs {sek(d['price_effect'], True)}, valuta {sek(d['fx_effect'], True)}]")
    print(f"Orealiserat: {sek(s['gain'], True)} {home} ({pct(s['gain_pct'])}) mot anskaffningsvärde {sek(s['cost'])}")
    if s["realized"]:
        print(f"Realiserat (sålt): {sek(s['realized'], True)} {home}   Totalt: {sek(s['total'], True)} {home}")
    if data["error"]:
        print("OBS: " + data["error"])
    return 0


def main():
    global DEMO, LOTS_FILE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1", help="standard 127.0.0.1 (endast denna dator)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--report", action="store_true", help="skriv ut daglig sammanfattning och avsluta")
    ap.add_argument("--demo", action="store_true", help="använd syntetiska kurser (sparar inga köp)")
    args = ap.parse_args()

    if args.demo:
        DEMO = True
        LOTS_FILE = os.path.join(DATA_DIR, "demo_lots.json")
        if not os.path.exists(LOTS_FILE):
            t = dt.date.today()
            save_lots([
                {"id": "demo0001", "date": (t - dt.timedelta(days=150)).isoformat(), "shares": 12,
                 "price": None, "paid": 3400, "note": "Demo – köp 1"},
                {"id": "demo0002", "date": (t - dt.timedelta(days=90)).isoformat(), "shares": 12,
                 "price": None, "paid": 3400, "note": "Demo – köp 2"},
                {"id": "demo0003", "date": (t - dt.timedelta(days=30)).isoformat(), "shares": 12,
                 "price": None, "paid": 3400, "note": "Demo – köp 3"},
                {"id": "demo0004", "type": "sell", "date": (t - dt.timedelta(days=10)).isoformat(), "shares": 8,
                 "price": None, "received": None, "note": "Demo – försäljning"},
            ])

    if args.report:
        sys.exit(report())

    if os.environ.get("SUPERVISOR_TOKEN"):
        threading.Thread(target=publisher_loop, daemon=True).start()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"ESPP-tracker kör på http://{args.host}:{args.port}  (Ctrl+C för att avsluta)"
          + ("  [DEMO]" if DEMO else ""))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
