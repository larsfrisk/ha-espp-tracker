#!/usr/bin/env python3
"""Portföljtracker: följ dina aktier (t.ex. Hitachi ESPP och Stockholmsbörsen) dagligen i SEK.

Kör:        python3 app.py                -> dashboard på http://127.0.0.1:8765
Rapport:    python3 app.py --report       -> text-sammanfattning (för cron / Home Assistant)
Demo:       python3 app.py --demo         -> syntetiska kurser, ingen internetåtkomst behövs

Endast Python 3.9+ standardbibliotek. Innehav och transaktioner sparas i data/holdings.json och data/lots.json.
Kurser: Yahoo Finance (inofficiellt chart-API). Valuta: Frankfurter (ECB-kurser).
"""
import argparse
import datetime as dt
import json
import math
import os
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python -I lägger inte till skriptets mapp
import signals  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("ESPP_DATA_DIR") or os.path.join(BASE, "data")
INGRESS = os.environ.get("ESPP_INGRESS") == "1"        # körs som Home Assistant-tillägg
INGRESS_PEER = "172.30.32.2"                           # Supervisorns ingress-gateway
LOTS_FILE = os.path.join(DATA_DIR, "lots.json")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
HOLDINGS_FILE = os.path.join(DATA_DIR, "holdings.json")
INDEX_FILE = os.path.join(BASE, "index.html")

DEFAULT_CONFIG = {
    # name/symbol/price_ccy används bara för att flytta över ett gammalt (v1) Hitachi-innehav till holdings.json
    "name": "Hitachi, Ltd.",
    "symbol": "6501.T",
    "price_ccy": "JPY",
    "home_ccy": "SEK",       # valutan du vill se värdet i
    "intraday_interval": "15m",   # upplösning i dagsdiagrammet: 1m, 5m eller 15m
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


def save_setting(key, value):
    """Sparar en inställning från gränssnittet i config.json (övriga nycklar lämnas orörda)."""
    if key == "intraday_interval":
        if value not in INTERVALS:
            raise ValueError("Ogiltig upplösning (välj 1m, 5m eller 15m)")
    else:
        raise ValueError("Okänd inställning")
    conf = _read_json(CONFIG_FILE, {})
    conf[key] = value
    _write_json(CONFIG_FILE, conf)


def _slug(text):
    t = text.lower().replace("å", "a").replace("ä", "a").replace("ö", "o")
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:24].strip("-") or "aktie"


def load_holdings():
    hs = _read_json(HOLDINGS_FILE, None)
    if hs is None:
        # Flytta över ett gammalt (v1) Hitachi-innehav om transaktioner redan finns
        hs = []
        if _read_json(LOTS_FILE, []):
            cfg = load_config()
            hs = [{"id": "hitachi", "name": cfg["name"], "symbol": cfg["symbol"],
                   "price_ccy": cfg["price_ccy"], "sensor_prefix": "espp"}]
            _write_json(HOLDINGS_FILE, hs)
    return hs


def save_holdings(hs):
    _write_json(HOLDINGS_FILE, hs)


def find_holding(hid):
    return next((h for h in load_holdings() if h["id"] == hid), None)


def holding_cfg(h):
    cfg = load_config()
    cfg.update(id=h["id"], name=h["name"], symbol=h["symbol"], price_ccy=h["price_ccy"],
               kind=h.get("kind", "stock"), source=h.get("source", "yahoo"))
    return cfg


def nav_path(hid):
    return os.path.join(DATA_DIR, "nav_%s.json" % hid)


def cache_path(h, kind="cache"):
    return os.path.join(DATA_DIR, "%s_%s.json" % (kind, h["id"]))


def load_lots():
    """Alla transaktioner; äldre utan 'holding' hör till första innehavet."""
    hs = load_holdings()
    default = hs[0]["id"] if hs else "hitachi"
    lots = _read_json(LOTS_FILE, [])
    for l in lots:
        l.setdefault("holding", default)
    return lots


def lots_for(hid, lots):
    return [l for l in lots if l.get("holding") == hid]


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


def demo_data(start, cfg):
    seed = zlib.crc32(cfg["symbol"].encode())
    rnd = random.Random(seed)
    jpy = cfg["price_ccy"] == "JPY"
    prices, fx = {}, {}
    d, p = start, 4200.0 if jpy else 80.0 + seed % 300
    r = {"JPY": 0.0680, "USD": 10.5, "EUR": 11.2}.get(cfg["price_ccy"], 1.0)
    while d <= dt.date.today():
        if d.weekday() < 5:
            p *= math.exp(rnd.gauss(0.0004, 0.014 if jpy else 0.012))
            r *= math.exp(rnd.gauss(0.0, 0.003))
            prices[d.isoformat()] = round(p, 1)
            if cfg["price_ccy"] != cfg["home_ccy"]:
                fx[d.isoformat()] = round(r, 5)
        d += dt.timedelta(days=1)
    return prices, fx, {"currency": cfg["price_ccy"], "exchange": "DEMO"}


DEMO_SEARCH = [("VOLV-B.ST", "Volvo AB ser. B", "Stockholm", "SEK", "stock"), ("ERIC-B.ST", "Telefonaktiebolaget LM Ericsson ser. B", "Stockholm", "SEK", "stock"),
               ("INVE-B.ST", "Investor AB ser. B", "Stockholm", "SEK", "stock"), ("HM-B.ST", "H & M Hennes & Mauritz AB ser. B", "Stockholm", "SEK", "stock"),
               ("SEB-A.ST", "Skandinaviska Enskilda Banken ser. A", "Stockholm", "SEK", "stock"), ("ABB.ST", "ABB Ltd", "Stockholm", "SEK", "stock"),
               ("AAPL", "Apple Inc.", "NASDAQ", "USD", "stock"),
               ("0P00005U1J.ST", "Avanza Zero (demo)", "Stockholm", "SEK", "fund"), ("0P00000LSN.ST", "Skandia Realräntefond (demo)", "Stockholm", "SEK", "fund"),
               ("0P00000IAJ.ST", "Skandia Time Global (demo)", "Stockholm", "SEK", "fund")]
KINDS = {"MUTUALFUND": "fund", "ETF": "etf", "EQUITY": "stock"}
ISIN_RE = re.compile(r"[A-Z]{2}[A-Z0-9]{9}[0-9]")


def lookup_symbol(sym):
    """Kontrollerar symbolen hos Yahoo Finance. Returnerar namn och valuta."""
    if DEMO:
        for s_, n, _e, c, k in DEMO_SEARCH:
            if s_ == sym:
                return {"name": n, "currency": c, "kind": k}
        raise ValueError("Hittar ingen aktie med symbolen %s (demo)" % sym)
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%s?interval=1d&range=5d" % urllib.parse.quote(sym)
    try:
        meta = _http_json(url)["chart"]["result"][0]["meta"]
    except urllib.error.HTTPError:
        raise ValueError("Hittar ingen aktie med symbolen %s hos Yahoo Finance" % sym)
    except Exception as e:
        raise ValueError("Kunde inte kontrollera symbolen just nu (%s)" % e)
    ccy = meta.get("currency")
    if not ccy:
        raise ValueError("Yahoo Finance gav ingen valuta för %s" % sym)
    if ccy in ("GBp", "GBX", "ZAc", "ILA"):
        raise ValueError("Aktier som noteras i %s (delenhet) stöds inte än" % ccy)
    return {"name": meta.get("longName") or meta.get("shortName") or sym, "currency": ccy.upper(),
            "kind": KINDS.get(meta.get("instrumentType"), "stock")}


def search_symbols(q):
    """Sök aktier, ETF:er och fonder (namn eller ISIN) hos Yahoo Finance. Svenska (.ST) sorteras först."""
    q = q.strip()[:40]
    if DEMO:
        out = [{"symbol": s_, "name": n, "exchange": e, "kind": k} for s_, n, e, _c, k in DEMO_SEARCH
               if q.lower() in n.lower() or q.lower() in s_.lower()]
    else:
        url = "https://query1.finance.yahoo.com/v1/finance/search?q=%s&quotesCount=10&newsCount=0&listsCount=0" % urllib.parse.quote(q)
        out = [{"symbol": x["symbol"], "name": x.get("shortname") or x.get("longname") or x["symbol"],
                "exchange": x.get("exchDisp") or x.get("exchange") or "", "kind": KINDS[x["quoteType"]]}
               for x in _http_json(url).get("quotes", []) if x.get("quoteType") in KINDS and x.get("symbol")]
    return sorted(out, key=lambda r: not r["symbol"].endswith(".ST"))


def add_holding(body):
    if body.get("manual"):
        return add_manual_fund(body)
    sym = str(body.get("symbol", "")).strip().upper()
    if ISIN_RE.fullmatch(sym):                       # ISIN: slå upp symbolen hos Yahoo
        try:
            hits = search_symbols(sym)
        except Exception as e:
            raise ValueError("Kunde inte slå upp ISIN just nu (%s)" % e)
        if not hits:
            raise ValueError("Hittar ingen aktie eller fond med ISIN %s hos Yahoo Finance. Lägg till fonden manuellt i stället." % sym)
        sym = hits[0]["symbol"].upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-=^]{0,19}", sym):
        raise ValueError("Ogiltig symbol. Stockholmsbörsen slutar på .ST, till exempel VOLV-B.ST")
    hs = load_holdings()
    if any(h["symbol"].upper() == sym for h in hs):
        raise ValueError("Du har redan lagt till %s" % sym)
    info = lookup_symbol(sym)
    home = load_config()["home_ccy"]
    if info["currency"] != home and not DEMO:
        try:
            fetch_fx(info["currency"], home, dt.date.today() - dt.timedelta(days=7))
        except Exception:
            raise ValueError("Valutan %s kan inte räknas om till %s (ECB-kurser saknas)" % (info["currency"], home))
    name = (str(body.get("name") or "").strip() or info["name"])[:60]
    return _store_holding(hs, name, sym, info["currency"], info.get("kind", "stock"))


def _store_holding(hs, name, symbol, ccy, kind, source=None):
    base = _slug(name)
    hid, n = base, 2
    while any(h["id"] == hid for h in hs):
        hid, n = "%s-%d" % (base, n), n + 1
    h = {"id": hid, "name": name, "symbol": symbol, "price_ccy": ccy, "kind": kind,
         "sensor_prefix": "holding_" + hid.replace("-", "_")}
    if source:
        h["source"] = source
    hs.append(h)
    save_holdings(hs)
    return h


def add_manual_fund(body):
    """Fond som inte finns hos Yahoo: du skriver in NAV själv (alltid i hemvalutan)."""
    name = str(body.get("name") or "").strip()[:60]
    if not name:
        raise ValueError("Fonden behöver ett namn")
    isin = str(body.get("isin") or "").strip().upper()
    if isin and not ISIN_RE.fullmatch(isin):
        raise ValueError("Ogiltigt ISIN (12 tecken, t.ex. SE0000000000)")
    hs = load_holdings()
    sym = isin or "MANUELL-" + _slug(name).upper()
    if any(h["symbol"].upper() == sym for h in hs):
        raise ValueError("Du har redan lagt till %s" % sym)
    return _store_holding(hs, name, sym, load_config()["home_ccy"], "fund", source="manual")


def set_nav(h, body):
    if h.get("source") != "manual":
        raise ValueError("NAV läggs bara in för manuella fonder")
    try:
        d = dt.date.fromisoformat(str(body.get("date", "")))
    except ValueError:
        raise ValueError("Ogiltigt datum (använd ÅÅÅÅ-MM-DD)")
    if d > dt.date.today():
        raise ValueError("Datumet ligger i framtiden")
    try:
        p = float(str(body.get("price", "")).replace(",", ".").replace(" ", ""))
    except ValueError:
        raise ValueError("Ogiltigt NAV")
    if not math.isfinite(p) or p <= 0:
        raise ValueError("NAV måste vara större än 0")
    navs = _read_json(nav_path(h["id"]), {})
    navs[d.isoformat()] = p
    _write_json(nav_path(h["id"]), navs)


def del_nav(h, date_s):
    navs = _read_json(nav_path(h["id"]), {})
    if date_s not in navs:
        raise ValueError("Det NAV:et finns inte")
    del navs[date_s]
    _write_json(nav_path(h["id"]), navs)


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


def get_market(cfg, start, cache_file):
    """Hämtar (med cache) kurser och valuta. Returnerar (prices, fx, meta, fetched_at, error)."""
    if cfg.get("source") == "manual":
        return (_read_json(nav_path(cfg["id"]), {}), {}, {"currency": cfg["price_ccy"], "exchange": "manuell"},
                time.time(), None)
    cache = _read_json(cache_file, {})
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
        p, f, m = demo_data(start, cfg)
        return p, f, m, now, None
    try:
        prices, meta = fetch_prices(cfg["symbol"], start)
        fx = fetch_fx(cfg["price_ccy"], cfg["home_ccy"], start - dt.timedelta(days=7))
        _write_json(cache_file, {"v": CACHE_VERSION, "key": list(key), "start": start.isoformat(), "fetched_at": now,
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
    """Kontrollerar varje innehav för sig."""
    by = {}
    for l in lots:
        by.setdefault(l.get("holding"), []).append(l)
    for group in by.values():
        _check_one(group)


def _check_one(lots):
    """Kastar ValueError om du någon gång skulle sälja fler aktier än du äger."""
    held = 0.0
    for l in sorted(lots, key=lambda x: (x["date"], 0 if x.get("type", "buy") == "buy" else 1)):
        held += float(l["shares"]) if l.get("type", "buy") == "buy" else -float(l["shares"])
        if held < -1e-9:
            raise ValueError("Det skulle innebära att du säljer fler aktier än du äger per %s" % l["date"])


def _start(lots):
    """Hämta historik från första köpet (med marginal)."""
    first = min([dt.date.fromisoformat(l["date"]) for l in lots]) if lots else dt.date.today() - dt.timedelta(days=90)
    return first - dt.timedelta(days=10)


def build_summary(h, refresh=False):
    cfg = holding_cfg(h)
    lots = lots_for(h["id"], load_lots())
    if refresh and not DEMO:
        try:
            os.remove(cache_path(h))
        except FileNotFoundError:
            pass
    prices, fx, meta, fetched_at, err = get_market(cfg, _start(lots), cache_path(h))
    summ = compute(lots, cfg, prices, fx)
    return {
        "holding": h, "config": cfg, "meta": meta, "demo": DEMO, "error": err,
        "fetched_at": dt.datetime.fromtimestamp(fetched_at).isoformat(timespec="seconds"), "fetched_ts": fetched_at,
        "summary": summ, "has_lots": bool(lots),
        "next_update": next_due(time.time(), cfg).isoformat(timespec="minutes"), "next_ts": next_due(time.time(), cfg).timestamp(),
        "price_history": [{"d": d, "price": prices[d]} for d in sorted(prices)[-800:]],
        "navs": [{"date": d, "price": p} for d, p in sorted(prices.items(), reverse=True)] if cfg["source"] == "manual" else None,
    }


def _merge_histories(hists):
    """Summerar värde och anskaffningsvärde per dag; saknad dag fylls med senaste kända värde."""
    hs = [h for h in hists if h]
    if not hs:
        return []
    ptr, cur, out = [0] * len(hs), [(0.0, 0.0)] * len(hs), []
    for d in sorted({p["d"] for h in hs for p in h}):
        for k, h in enumerate(hs):
            while ptr[k] < len(h) and h[ptr[k]]["d"] <= d:
                cur[k] = (h[ptr[k]]["value"], h[ptr[k]]["invested"])
                ptr[k] += 1
        out.append({"d": d, "value": sum(c[0] for c in cur), "invested": sum(c[1] for c in cur)})
    return out


def _apply_today(row, h, refresh):
    """Byter dagskursens förändring mot förändringen hittills idag (intradagsdata mot föregående stängning)."""
    if row["kind"] == "fund" or not row["has_prices"]:
        return
    try:
        t = build_intraday(h, refresh)
    except Exception:
        return
    pts = t.get("points") or []
    if not pts or not (t.get("base_price") or 0) > 0:
        return
    last = pts[-1]
    row["price"] = last["price"]
    row["price_pct"] = (last["price"] / t["base_price"] - 1) * 100
    row["today_date"] = t["date"]
    row["today_live"] = bool(t.get("live"))
    if row["has_lots"] and t.get("base_value"):
        delta = last["value"] - row["value"]
        row["value"] += delta; row["gain"] += delta; row["total"] += delta
        row["gain_pct"] = row["gain"] / row["cost"] * 100 if row["cost"] else None
        row["day_change"] = last["value"] - t["base_value"]
        row["day_pct"] = row["day_change"] / t["base_value"] * 100
        row["price_effect"] = row["day_change"]; row["fx_effect"] = 0.0


def build_portfolio(refresh=False, today=False):
    cfg = load_config()
    rows, errors, hists, fetched, fetched_ts = [], [], [], [], []
    for h in load_holdings():
        d = build_summary(h, refresh)
        s = d["summary"]
        fetched.append(d["fetched_at"]); fetched_ts.append(d["fetched_ts"])
        if d["error"]:
            errors.append("%s: %s" % (h["name"], d["error"]))
        row = {"id": h["id"], "name": h["name"], "symbol": h["symbol"], "price_ccy": h["price_ccy"],
               "kind": h.get("kind", "stock"), "sensor_prefix": h.get("sensor_prefix"), "has_lots": d["has_lots"], "has_prices": bool(s),
               "shares": 0.0, "value": 0.0, "cost": 0.0, "gain": 0.0, "gain_pct": None, "realized": 0.0,
               "total": 0.0, "day_change": 0.0, "day_pct": None, "price_pct": None, "price": None,
               "fx": None, "as_of": None, "price_effect": 0.0, "fx_effect": 0.0}
        if s:
            row.update(shares=s["shares"], value=s["value"], cost=s["cost"], gain=s["gain"], gain_pct=s["gain_pct"],
                       realized=s["realized"], total=s["total"], day_change=s["day"]["change"], day_pct=s["day"]["pct"],
                       price_pct=s["day"]["price_pct"], price=s["price"], fx=s["fx"], as_of=s["as_of"],
                       price_effect=s["day"]["price_effect"], fx_effect=s["day"]["fx_effect"])
            hists.append(s["history"])
            if today:
                _apply_today(row, h, refresh)
        rows.append(row)
    rows.sort(key=lambda r: -r["value"])
    tv = sum(r["value"] for r in rows)
    tc = sum(r["cost"] for r in rows)
    dc = sum(r["day_change"] for r in rows)
    gain = sum(r["gain"] for r in rows)
    realized = sum(r["realized"] for r in rows)
    for r in rows:
        r["weight"] = r["value"] / tv * 100 if tv else 0.0
    prev = tv - dc
    return {
        "config": cfg, "demo": DEMO, "errors": errors, "holdings": rows, "history": _merge_histories(hists),
        "fetched_at": max(fetched) if fetched else None, "fetched_ts": max(fetched_ts) if fetched_ts else None,
        "next_update": next_due(time.time(), cfg).isoformat(timespec="minutes"), "next_ts": next_due(time.time(), cfg).timestamp(),
        "totals": {"value": tv, "cost": tc, "gain": gain, "gain_pct": gain / tc * 100 if tc else None,
                   "realized": realized, "total": gain + realized,
                   "day": {"change": dc, "pct": dc / prev * 100 if prev else None,
                           "price_effect": sum(r["price_effect"] for r in rows),
                           "fx_effect": sum(r["fx_effect"] for r in rows)}},
    }


# ---------------------------------------------------------------- intradag (15 minuter)

INTERVALS = {"1m": 60, "5m": 300, "15m": 900}


def intraday_interval(cfg):
    v = str(cfg.get("intraday_interval", "15m"))
    return v if v in INTERVALS else "15m"


def fetch_intraday(symbol, interval="15m"):
    """Senaste handelsdagens staplar (1, 5 eller 15 minuter) från Yahoo Finance, med volym för VWAP
    och tidigare dagars sista staplar som uppvärmning för indikatorerna."""
    rng = "2d" if interval == "1m" else "5d"
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%s?interval=%s&range=%s" % (urllib.parse.quote(symbol), interval, rng)
    res = _http_json(url)["chart"]["result"][0]
    off = res["meta"].get("gmtoffset", 0)
    reg = res["meta"].get("currentTradingPeriod", {}).get("regular", {})
    q = res["indicators"]["quote"][0]
    vols, opens = q.get("volume") or [], q.get("open") or []
    days = {}
    for i, (ts, c) in enumerate(zip(res["timestamp"], q["close"])):
        if c is None:
            continue
        d = dt.datetime.fromtimestamp(ts + off, dt.timezone.utc).date().isoformat()
        v = vols[i] if i < len(vols) and vols[i] else 0
        o = opens[i] if i < len(opens) and opens[i] else None
        days.setdefault(d, []).append([ts, float(c), v, o])
    if not days:
        raise ValueError("inga intradagsdata")
    last = max(days)
    live = bool(reg.get("start") and reg.get("end") and reg["start"] <= time.time() < reg["end"])
    today = sorted(days[last])
    prior = [r[1] for d in sorted(days) if d < last for r in sorted(days[d])][-150:]
    vw, cv, cpv = [], 0.0, 0.0
    for _ts, c, v, _o in today:
        cv, cpv = cv + v, cpv + c * v
        vw.append(cpv / cv if cv else None)
    older = [d for d in days if d < last]
    pdate = max(older) if older else None
    return {"date": last, "live": live, "points": [[r[0], r[1]] for r in today], "interval": interval,
            "prev_date": pdate, "prev_close": sorted(days[pdate])[-1][1] if pdate else None,
            "prior": prior, "vwaps": vw, "day_open": today[0][3] or today[0][1]}


def demo_intraday(base_price, symbol=""):
    rnd = random.Random(zlib.crc32(symbol.encode()) + 7)
    start = dt.datetime.combine(dt.date.today(), dt.time(0, 0), dt.timezone.utc)   # 09:00 JST
    p, pts = base_price * 0.99, []
    for i in range(27):                                                            # till 15:30 JST
        p *= math.exp(rnd.gauss(0.0003, 0.002))
        pts.append([int(start.timestamp()) + i * 900, round(p, 1)])
    prior = [round(base_price * math.exp(rnd.gauss(0, 0.01)), 1) for _ in range(60)]
    vw = [round(sum(x[1] for x in pts[:i + 1]) / (i + 1), 1) for i in range(len(pts))]
    return {"date": dt.date.today().isoformat(), "live": False, "points": pts, "fetched_at": time.time(),
            "prior": prior, "vwaps": vw, "day_open": pts[0][1]}


def get_intraday(cfg, last_close, refresh, cache_file):
    """(data, fel). Cache lika lång som stapeln under pågående handel, 60 min annars."""
    if DEMO:
        return demo_intraday(last_close, cfg["symbol"]), None
    cache = _read_json(cache_file, {})
    now = time.time()
    iv = intraday_interval(cfg)
    same = cache.get("symbol") == cfg["symbol"] and cache.get("interval", "15m") == iv and bool(cache.get("points"))
    if same and not refresh and now - cache.get("fetched_at", 0) < (INTERVALS[iv] if cache.get("live") else 3600):
        return cache, None
    try:
        data = fetch_intraday(cfg["symbol"], iv)
        data.update({"symbol": cfg["symbol"], "fetched_at": now})
        _write_json(cache_file, data)
        return data, None
    except Exception as e:
        if same:
            return cache, "Kunde inte hämta nya intradagskurser (%s). Visar senast sparade." % e
        return None, "Kunde inte hämta intradagskurser: %s" % e


def demo_history(cfg, days=900):
    rnd = random.Random(zlib.crc32(cfg["symbol"].encode()) + 99)
    d, p, out = dt.date.today() - dt.timedelta(days=days), 100.0 + zlib.crc32(cfg["symbol"].encode()) % 200, {}
    while d <= dt.date.today():
        if d.weekday() < 5:
            p *= math.exp(rnd.gauss(0.0003, 0.013))
            out[d.isoformat()] = round(p, 2)
        d += dt.timedelta(days=1)
    return out


def get_tech_history(cfg, refresh, cache_file):
    """Cirka tre års dagskurser för signalberäkning. En hämtning per dag (som övriga kurser)."""
    if DEMO:
        return demo_history(cfg), None
    cache = _read_json(cache_file, {})
    now = time.time()
    same = cache.get("symbol") == cfg["symbol"] and bool(cache.get("prices"))
    if same and not refresh and cache.get("fetched_at", 0) >= last_due(now, cfg):
        return cache["prices"], None
    try:
        prices, _meta = fetch_prices(cfg["symbol"], dt.date.today() - dt.timedelta(days=1100))
        _write_json(cache_file, {"symbol": cfg["symbol"], "fetched_at": now, "prices": prices})
        return prices, None
    except Exception as e:
        if same:
            return cache["prices"], "Kunde inte hämta ny kurshistorik (%s). Visar senast sparade." % e
        return None, "Kunde inte hämta kurshistorik: %s" % e


def build_signals(h, refresh=False):
    cfg = holding_cfg(h)
    if cfg["source"] == "manual":
        return {"error": "Signaler beräknas inte för manuella fonder (för få kurser)."}
    prices, err = get_tech_history(cfg, refresh, cache_path(h, "tech"))
    if not prices:
        return {"error": err or "Ingen kurshistorik tillgänglig"}
    keys = sorted(prices)
    res = signals.analyse(keys, [prices[k] for k in keys])
    res.update(price_ccy=cfg["price_ccy"], warning=err)
    return res


BT_RUNS = (("1m", "7d"), ("5m", "1mo"), ("15m", "1mo"))   # Yahoo: 1m max 7 dagar, 5m/15m max 60 dagar


def fetch_bars(symbol, interval, rng):
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%s?interval=%s&range=%s" % (urllib.parse.quote(symbol), interval, rng)
    res = _http_json(url)["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    vols, opens = q.get("volume") or [], q.get("open") or []
    bars = []
    for i, (ts, c) in enumerate(zip(res["timestamp"], q["close"])):
        if c is None:
            continue
        bars.append([ts, float(c), (vols[i] if i < len(vols) and vols[i] else 0), (opens[i] if i < len(opens) else None)])
    return bars, res["meta"].get("gmtoffset", 0)


def demo_bars(symbol, interval, days):
    per = {"1m": 510, "5m": 102, "15m": 34}[interval]
    step = {"1m": 60, "5m": 300, "15m": 900}[interval]
    rnd = random.Random(zlib.crc32((symbol + interval).encode()))
    p, bars = 100.0 + zlib.crc32(symbol.encode()) % 200, []
    d0 = dt.datetime.combine(dt.date.today() - dt.timedelta(days=days), dt.time(8, 0), tzinfo=dt.timezone.utc)
    for d in range(days):
        day = d0 + dt.timedelta(days=d)
        if day.weekday() >= 5:
            continue
        for j in range(per):
            p *= math.exp(rnd.gauss(0, 0.0012 * math.sqrt(step / 60.0)))
            bars.append([int(day.timestamp()) + j * step, round(p, 2), rnd.randint(100, 5000), None])
    return bars, 0


def build_intraday_backtest(h, cost, refresh=False):
    cfg = holding_cfg(h)
    if cfg["source"] == "manual" or cfg["kind"] == "fund":
        return {"error": "Intradagsbacktest finns bara för aktier och ETF:er."}
    cache_file = cache_path(h, "ibt")
    cache = _read_json(cache_file, {}) if not DEMO else {}
    now, rows, errs = time.time(), [], []
    for iv, rng in BT_RUNS:
        c = cache.get(iv)
        if not (c and not refresh and c.get("symbol") == cfg["symbol"] and now - c.get("fetched_at", 0) < 3600):
            try:
                bars, off = demo_bars(cfg["symbol"], iv, 10 if iv == "1m" else 42) if DEMO else fetch_bars(cfg["symbol"], iv, rng)
                c = {"symbol": cfg["symbol"], "fetched_at": now, "bars": bars, "off": off}
                cache[iv] = c
            except Exception as e:
                errs.append("%s: %s" % (iv, e))
                if not c:
                    continue
        r = signals.backtest_bars(c["bars"], c["off"], cost)
        if r:
            r["interval"] = iv
            rows.append(r)
    if not DEMO and cache:
        _write_json(cache_file, cache)
    return {"cost": cost, "rows": rows, "errors": errs, "price_ccy": cfg["price_ccy"]}


def build_intraday(h, refresh=False):
    cfg = holding_cfg(h)
    base = {"points": [], "price_ccy": cfg["price_ccy"], "home_ccy": cfg["home_ccy"]}
    if cfg["kind"] == "fund":
        return dict(base, error="Fonder har bara en kurs per dag (NAV), så det finns ingen intradagsvy.")
    lots = lots_for(h["id"], load_lots())
    prices, fx, _meta, _t, err = get_market(cfg, _start(lots), cache_path(h))
    if not prices:
        return dict(base, error=err or "Inga kurser tillgängliga")
    summ = compute(lots, cfg, prices, fx)
    P = Series(prices)
    rate = Series(fx).at(P.keys[-1]) if cfg["price_ccy"] != cfg["home_ccy"] else 1.0
    shares = summ["shares"] if summ else 0.0
    data, ierr = get_intraday(cfg, P.at(P.keys[-1]), refresh, cache_path(h, "intraday"))
    if not data:
        return dict(base, error=ierr)
    before = (dt.date.fromisoformat(data["date"]) - dt.timedelta(days=1)).isoformat()
    pd_ = data.get("prev_date")
    if pd_ and pd_ in prices:                 # föregående handelsdag finns i dagskurserna: officiell stängning
        base_price = prices[pd_]
    elif data.get("prev_close"):              # dagskurserna saknar dagen: ta sista stapeln från intradagsdatan
        base_price = data["prev_close"]
    else:
        base_price = P.at(before)
    pts = [{"ts": ts, "t": dt.datetime.fromtimestamp(ts).strftime("%H:%M"), "price": p,
            "value": shares * p * rate} for ts, p in data["points"]]
    sig = signals.intraday(list(data.get("prior") or []) + [p for _ts, p in data["points"]], len(data["points"]),
                           data.get("vwaps"), data.get("day_open"))
    if "flips" in sig:
        for f in sig["flips"]:
            f["t"] = pts[f["idx"]]["t"]
            f["ts"] = pts[f["idx"]]["ts"]
    return dict(base, signals=sig, date=data["date"], live=data["live"], points=pts, shares=shares, fx=rate,
                interval=data.get("interval", "15m"), base_price=base_price, base_value=shares * base_price * rate,
                error=ierr, fetched_at=dt.datetime.fromtimestamp(data["fetched_at"]).isoformat(timespec="seconds"))


# ---------------------------------------------------------------- lot-validering

def validate_lot(body, holdings):
    hid = body.get("holding") or (holdings[0]["id"] if len(holdings) == 1 else None)
    if hid not in [h["id"] for h in holdings]:
        raise ValueError("Okänt innehav")
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
    lot = {"id": uuid.uuid4().hex[:8], "holding": hid, "type": typ, "date": date.isoformat(), "shares": shares,
           "price": price, "note": str(body.get("note", ""))[:80]}
    lot["paid" if typ == "buy" else "received"] = num("paid" if typ == "buy" else "received", positive=False)
    return lot


# ---------------------------------------------------------------- HTTP

RE_HOLDING_API = re.compile(r"^/api/holdings/([a-z0-9_-]+)/(summary|intraday|signals|intraday-backtest)$")


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
        qs = urllib.parse.parse_qs(path.query)
        refresh = bool(qs.get("refresh"))
        if path.path == "/":
            with open(INDEX_FILE, "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")
        if path.path == "/api/portfolio":
            with LOCK:
                return self._send(200, build_portfolio(refresh, today=True))
        if path.path == "/api/search":
            q = (qs.get("q") or [""])[0]
            if len(q.strip()) < 2:
                return self._send(400, {"error": "Skriv minst två tecken"})
            try:
                return self._send(200, {"results": search_symbols(q)})
            except Exception as e:
                return self._send(502, {"error": "Sökningen misslyckades (%s). Skriv symbolen direkt i stället." % e})
        m = RE_HOLDING_API.match(path.path)
        if m:
            h = find_holding(m.group(1))
            if not h:
                return self._send(404, {"error": "Innehavet finns inte"})
            with LOCK:
                if m.group(2) == "signals":
                    return self._send(200, build_signals(h, refresh))
                if m.group(2) == "intraday-backtest":
                    try:
                        cost = min(2.0, max(0.0, float(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("cost", ["0.1"])[0])))
                    except ValueError:
                        cost = 0.1
                    return self._send(200, build_intraday_backtest(h, cost, refresh))
                return self._send(200, build_summary(h, refresh) if m.group(2) == "summary" else build_intraday(h, refresh))
        self._send(404, {"error": "Hittades inte"})

    def do_POST(self):
        if not self._allowed(write=True):
            return self._send(403, {"error": "Otillåten förfrågan"})
        try:
            body = self._body()
        except (ValueError, json.JSONDecodeError) as e:
            return self._send(400, {"error": str(e)})
        if self.path == "/api/lots":
            with LOCK:
                try:
                    lot = validate_lot(body, load_holdings())
                    lots = load_lots()
                    lots.append(lot)
                    check_sequence(lots)
                except ValueError as e:
                    return self._send(400, {"error": str(e)})
                save_lots(lots)
            return self._send(201, lot)
        if self.path == "/api/holdings":
            with LOCK:
                try:
                    h = add_holding(body)
                except ValueError as e:
                    return self._send(400, {"error": str(e)})
            return self._send(201, h)
        m = re.match(r"^/api/holdings/([a-z0-9_-]+)/prices$", self.path)
        if m:
            with LOCK:
                h = find_holding(m.group(1))
                if not h:
                    return self._send(404, {"error": "Innehavet finns inte"})
                try:
                    set_nav(h, body)
                except ValueError as e:
                    return self._send(400, {"error": str(e)})
            return self._send(201, {"ok": True})
        if self.path == "/api/settings":
            with LOCK:
                try:
                    for k, v in body.items():
                        save_setting(k, v)
                except ValueError as e:
                    return self._send(400, {"error": str(e)})
            return self._send(200, {"intraday_interval": intraday_interval(load_config())})
        m = re.match(r"^/api/holdings/([a-z0-9_-]+)/name$", self.path)
        if m:
            name = str(body.get("name") or "").strip()[:60]
            if not name:
                return self._send(400, {"error": "Namnet får inte vara tomt"})
            with LOCK:
                hs = load_holdings()
                h = next((x for x in hs if x["id"] == m.group(1)), None)
                if not h:
                    return self._send(404, {"error": "Innehavet finns inte"})
                h["name"] = name
                save_holdings(hs)
            return self._send(200, h)
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
        m = re.match(r"^/api/holdings/([a-z0-9_-]+)/prices/(\d{4}-\d{2}-\d{2})$", self.path)
        if m:
            with LOCK:
                h = find_holding(m.group(1))
                if not h or h.get("source") != "manual":
                    return self._send(404, {"error": "Innehavet finns inte"})
                try:
                    del_nav(h, m.group(2))
                except ValueError as e:
                    return self._send(404, {"error": str(e)})
            return self._send(200, {"ok": True})
        m = re.match(r"^/api/holdings/([a-z0-9_-]+)$", self.path)
        if m:
            with LOCK:
                hs, lots = load_holdings(), load_lots()
                if not any(h["id"] == m.group(1) for h in hs):
                    return self._send(404, {"error": "Innehavet finns inte"})
                save_lots([l for l in lots if l["holding"] != m.group(1)])
                save_holdings([h for h in hs if h["id"] != m.group(1)])
                try:
                    os.remove(nav_path(m.group(1)))
                except FileNotFoundError:
                    pass
            return self._send(200, {"ok": True})
        self._send(404, {"error": "Hittades inte"})


# ---------------------------------------------------------------- Home Assistant-sensorer

def _post_state(token, key, name, val, unit, nd, icon, as_of=None):
    if val is None:
        return
    attrs = {"friendly_name": name, "icon": icon, "state_class": "measurement"}
    if as_of:
        attrs["as_of"] = as_of
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


def publish_to_ha():
    """Skickar sensorer till HA via Supervisorns proxy (kräver homeassistant_api: true)."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return
    p = build_portfolio()
    home = p["config"]["home_ccy"]
    t = p["totals"]
    for key, name, val, unit, nd, icon in [
        ("portfolio_value", "Portfölj värde", t["value"], home, 0, "mdi:wallet"),
        ("portfolio_day_change", "Portfölj förändring idag", t["day"]["change"], home, 0, "mdi:trending-up"),
        ("portfolio_day_change_pct", "Portfölj förändring idag %", t["day"]["pct"], "%", 2, "mdi:percent"),
        ("portfolio_unrealized_gain", "Portfölj orealiserad vinst", t["gain"], home, 0, "mdi:cash-plus"),
        ("portfolio_realized_gain", "Portfölj realiserad vinst", t["realized"], home, 0, "mdi:cash-check"),
        ("portfolio_total_gain", "Portfölj total vinst", t["total"], home, 0, "mdi:cash-multiple"),
        ("portfolio_cost", "Portfölj anskaffningsvärde", t["cost"], home, 0, "mdi:cash"),
    ]:
        _post_state(token, key, name, val, unit, nd, icon)
    for r in p["holdings"]:
        if not r["has_prices"] or not r["sensor_prefix"]:
            continue
        k, n, ccy, asof = r["sensor_prefix"], r["name"], r["price_ccy"], r["as_of"]
        for suffix, label, val, unit, nd, icon in [
            ("value", "värde", r["value"], home, 0, "mdi:chart-line"),
            ("day_change", "förändring idag", r["day_change"], home, 0, "mdi:trending-up"),
            ("day_change_pct", "förändring idag %", r["day_pct"], "%", 2, "mdi:percent"),
            ("unrealized_gain", "orealiserad vinst", r["gain"], home, 0, "mdi:cash-plus"),
            ("unrealized_gain_pct", "orealiserad vinst %", r["gain_pct"], "%", 2, "mdi:percent"),
            ("realized_gain", "realiserad vinst", r["realized"], home, 0, "mdi:cash-check"),
            ("total_gain", "total vinst", r["total"], home, 0, "mdi:cash-multiple"),
            ("cost", "anskaffningsvärde", r["cost"], home, 0, "mdi:cash"),
            ("shares", "antal aktier", r["shares"], "st", 3, "mdi:numeric"),
            ("price", "aktiekurs", r["price"], ccy, 2, "mdi:currency-usd"),
            ("fx", "%s/%s" % (ccy, home), r["fx"] if ccy != home else None, None, 5, "mdi:swap-horizontal"),
        ]:
            _post_state(token, "%s_%s" % (k, suffix), "%s %s" % (n, label), val, unit, nd, icon, asof)


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
    p = build_portfolio()
    home = p["config"]["home_ccy"]
    pct = lambda v: "–" if v is None else f"{v:+.2f} %"
    if not p["holdings"]:
        print("Inga innehav registrerade.")
        return 1
    for r in p["holdings"]:
        if not r["has_prices"]:
            print(f"{r['name']} ({r['symbol']}): inga kurser tillgängliga")
            continue
        print(f"{r['name']} ({r['symbol']}) {r['as_of']}: kurs {r['price']:,.2f} {r['price_ccy']} ({pct(r['price_pct'])}), "
              f"{r['shares']:g} st = {sek(r['value'])} {home}, idag {sek(r['day_change'], True)} ({pct(r['day_pct'])}), "
              f"orealiserat {sek(r['gain'], True)} ({pct(r['gain_pct'])}), realiserat {sek(r['realized'], True)}")
    t = p["totals"]
    print(f"PORTFÖLJ: {sek(t['value'])} {home}, idag {sek(t['day']['change'], True)} ({pct(t['day']['pct'])}) "
          f"[kurs {sek(t['day']['price_effect'], True)}, valuta {sek(t['day']['fx_effect'], True)}], "
          f"orealiserat {sek(t['gain'], True)} ({pct(t['gain_pct'])}), realiserat {sek(t['realized'], True)}, "
          f"totalt {sek(t['total'], True)} {home}")
    for e in p["errors"]:
        print("OBS: " + e)
    return 0


def _demo_setup():
    t = dt.date.today()
    day = lambda n: (t - dt.timedelta(days=n)).isoformat()
    if not os.path.exists(HOLDINGS_FILE):
        save_holdings([
            {"id": "hitachi", "name": "Hitachi, Ltd.", "symbol": "6501.T", "price_ccy": "JPY", "sensor_prefix": "espp"},
            {"id": "volvo-ab-ser-b", "name": "Volvo AB ser. B", "symbol": "VOLV-B.ST", "price_ccy": "SEK", "sensor_prefix": "holding_volvo_ab_ser_b"},
            {"id": "investor-ab-ser-b", "name": "Investor AB ser. B", "symbol": "INVE-B.ST", "price_ccy": "SEK", "sensor_prefix": "holding_investor_ab_ser_b"},
            {"id": "avanza-zero", "name": "Avanza Zero (demo)", "symbol": "0P00005U1J.ST", "price_ccy": "SEK", "kind": "fund", "sensor_prefix": "holding_avanza_zero"},
            {"id": "skandia-sverige-exponering", "name": "Skandia Sverige Exponering", "symbol": "MANUELL-SKANDIA-SVERIGE-EXPONERING",
             "price_ccy": "SEK", "kind": "fund", "source": "manual", "sensor_prefix": "holding_skandia_sverige_exponering"},
        ])
        _write_json(nav_path("skandia-sverige-exponering"), {day(100): 340.0, day(70): 352.5, day(40): 347.2, day(10): 361.8})
    if not os.path.exists(LOTS_FILE):
        b = lambda i, hid, n, sh, paid=None, note="": {"id": "demo%04d" % i, "holding": hid, "date": day(n), "shares": sh,
                                                       "price": None, "paid": paid, "note": note}
        save_lots([
            b(1, "hitachi", 150, 12, 3400, "Demo ESPP 1"), b(2, "hitachi", 90, 12, 3400, "Demo ESPP 2"),
            b(3, "hitachi", 30, 12, 3400, "Demo ESPP 3"),
            {"id": "demo0004", "holding": "hitachi", "type": "sell", "date": day(10), "shares": 8,
             "price": None, "received": None, "note": "Demo – försäljning"},
            b(5, "volvo-ab-ser-b", 120, 40), b(6, "volvo-ab-ser-b", 45, 25),
            b(7, "investor-ab-ser-b", 100, 30), b(8, "avanza-zero", 130, 15, 6000, "Månadssparande"),
            b(9, "avanza-zero", 60, 10, 4300, "Månadssparande"), b(10, "skandia-sverige-exponering", 100, 20, 6800),
        ])


def main():
    global DEMO, LOTS_FILE, HOLDINGS_FILE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1", help="standard 127.0.0.1 (endast denna dator)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--report", action="store_true", help="skriv ut daglig sammanfattning och avsluta")
    ap.add_argument("--demo", action="store_true", help="använd syntetiska kurser (sparar inga riktiga köp)")
    args = ap.parse_args()

    if args.demo:
        DEMO = True
        LOTS_FILE = os.path.join(DATA_DIR, "demo_lots.json")
        HOLDINGS_FILE = os.path.join(DATA_DIR, "demo_holdings.json")
        _demo_setup()

    if args.report:
        sys.exit(report())

    if os.environ.get("SUPERVISOR_TOKEN"):
        threading.Thread(target=publisher_loop, daemon=True).start()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Portföljtracker kör på http://{args.host}:{args.port}  (Ctrl+C för att avsluta)"
          + ("  [DEMO]" if DEMO else ""))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
