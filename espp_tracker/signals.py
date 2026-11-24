"""Nyckeltal och regelbaserade tekniska signaler ("robothandelsregler") från dagliga stängningskurser.

Ren Python utan beroenden. Allt här är mekaniska regler som används i algoritmisk handel
(trendföljning, momentum, återgång till medelvärdet). De beskriver vad reglerna säger just nu
och hur de hade fungerat historiskt. Det är inte personlig rådgivning och inget löfte om framtiden.
"""
import math


def sma(v, n):
    return sum(v[-n:]) / n if len(v) >= n else None


def ema_series(v, n):
    k = 2.0 / (n + 1)
    out, e = [], None
    for x in v:
        e = x if e is None else x * k + e * (1 - k)
        out.append(e)
    return out


def rsi(v, n=14):
    """Wilders RSI."""
    if len(v) <= n:
        return None
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = v[i] - v[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    ag, al = gains / n, losses / n
    for i in range(n + 1, len(v)):
        d = v[i] - v[i - 1]
        ag = (ag * (n - 1) + max(d, 0)) / n
        al = (al * (n - 1) + max(-d, 0)) / n
    if al == 0:
        return 100.0 if ag > 0 else 50.0
    return 100.0 - 100.0 / (1 + ag / al)


def macd(v, fast=12, slow=26, sig=9):
    """(macd, signal, histogram) för sista dagen, eller None."""
    if len(v) < slow + sig:
        return None
    m = [a - b for a, b in zip(ema_series(v, fast), ema_series(v, slow))]
    s = ema_series(m, sig)
    return m[-1], s[-1], m[-1] - s[-1]


def bollinger(v, n=20, k=2.0):
    if len(v) < n:
        return None
    w = v[-n:]
    mid = sum(w) / n
    sd = math.sqrt(sum((x - mid) ** 2 for x in w) / n)
    lo, hi = mid - k * sd, mid + k * sd
    pb = (v[-1] - lo) / (hi - lo) if hi > lo else 0.5
    return {"mid": mid, "lo": lo, "hi": hi, "pctb": pb}


def ret(v, days):
    return (v[-1] / v[-1 - days] - 1) * 100 if len(v) > days and v[-1 - days] else None


def volatility(v, n=60):
    """Annualiserad volatilitet (%) av dagsavkastning de senaste n dagarna."""
    if len(v) <= n:
        return None
    r = [math.log(v[i] / v[i - 1]) for i in range(len(v) - n, len(v)) if v[i - 1] > 0 and v[i] > 0]
    if len(r) < 2:
        return None
    m = sum(r) / len(r)
    return math.sqrt(sum((x - m) ** 2 for x in r) / (len(r) - 1)) * math.sqrt(252) * 100


def max_drawdown(v):
    peak, worst = None, 0.0
    for x in v:
        peak = x if peak is None else max(peak, x)
        worst = min(worst, x / peak - 1)
    return worst * 100


def _label(sig):
    return {1: "positiv", 0: "neutral", -1: "negativ"}[sig]


def indicators(v):
    """Lista över indikatorer med värde och signal (+1 / 0 / -1)."""
    out = []
    last = v[-1]
    s50, s200 = sma(v, 50), sma(v, 200)
    if s200:
        sig = 1 if last > s200 else -1
        out.append({"id": "trend", "name": "Trend: kurs mot 200-dagars medelvärde", "signal": sig,
                    "value": "%+.1f %% mot SMA200" % ((last / s200 - 1) * 100),
                    "note": "Kursen över långa medelvärdet = upptrend (trendföljning)."})
    if s50 and s200:
        sig = 1 if s50 > s200 else -1
        out.append({"id": "cross", "name": "SMA50 mot SMA200", "signal": sig,
                    "value": "SMA50 %s SMA200" % (">" if sig > 0 else "<"),
                    "note": "Golden cross (SMA50 över SMA200) är en klassisk trendsignal, death cross är motsatsen."})
    m = macd(v)
    if m:
        sig = 1 if m[2] > 0 else -1
        out.append({"id": "macd", "name": "MACD (12, 26, 9)", "signal": sig,
                    "value": "histogram %+.2f" % m[2],
                    "note": "Positivt histogram = kort trend starkare än lång (momentum)."})
    r = rsi(v)
    if r is not None:
        sig = 1 if r < 30 else -1 if r > 70 else 0
        out.append({"id": "rsi", "name": "RSI (14 dagar)", "signal": sig, "value": "%.0f" % r,
                    "note": "Under 30 = översålt, över 70 = överköpt (återgång till medelvärdet)."})
    b = bollinger(v)
    if b:
        sig = 1 if b["pctb"] < 0 else -1 if b["pctb"] > 1 else 0
        out.append({"id": "boll", "name": "Bollingerband (20, 2)", "signal": sig,
                    "value": "%%B %.2f" % b["pctb"],
                    "note": "Under nedre bandet = ovanligt lågt, över övre bandet = ovanligt högt."})
    r6 = ret(v, 126)
    if r6 is not None:
        sig = 1 if r6 > 0 else -1
        out.append({"id": "mom", "name": "Momentum 6 månader", "signal": sig, "value": "%+.1f %%" % r6,
                    "note": "Det som stigit senaste halvåret har tenderat att fortsätta (momentumeffekten)."})
    return out


def verdict(inds):
    if not inds:
        return {"score": None, "label": "För lite data", "signal": 0}
    score = sum(i["signal"] for i in inds) / len(inds)
    if score >= 0.34:
        return {"score": score, "label": "Köpsignal", "signal": 1}
    if score <= -0.34:
        return {"score": score, "label": "Säljsignal", "signal": -1}
    return {"score": score, "label": "Neutral / blandade signaler", "signal": 0}


# ---------------------------------------------------------------- backtest

def _positions(v, rule):
    """Position (0/1) för varje dag, beslutad på dagens stängning."""
    n = len(v)
    pos = [0] * n
    if rule == "cross":
        for i in range(199, n):
            pos[i] = 1 if sum(v[i - 49:i + 1]) / 50 > sum(v[i - 199:i + 1]) / 200 else 0
    elif rule == "macd":
        e12, e26 = ema_series(v, 12), ema_series(v, 26)
        m = [a - b for a, b in zip(e12, e26)]
        s = ema_series(m, 9)
        for i in range(34, n):
            pos[i] = 1 if m[i] > s[i] else 0
    elif rule == "rsi":
        state = 0
        for i in range(15, n):
            r = rsi(v[:i + 1])
            if r is not None:
                if state == 0 and r < 30:
                    state = 1
                elif state == 1 and r > 50:
                    state = 0
            pos[i] = state
    return pos


def backtest(v):
    """Jämför enkla regler med att bara äga. Signal på dagens stängning ger position från nästa dag.
    Utan courtage, skatt och utdelningar."""
    if len(v) < 260:
        return None
    start = 200   # alla regler får samma jämförelseperiod
    out = []
    for rule, name in (("cross", "Trendföljning: SMA50 över SMA200"), ("macd", "Momentum: MACD över signallinjen"),
                       ("rsi", "Återgång: köp RSI<30, sälj RSI>50")):
        pos = _positions(v, rule)
        eq, peak, dd, trades = 1.0, 1.0, 0.0, 0
        for i in range(start + 1, len(v)):
            if pos[i - 1]:
                eq *= v[i] / v[i - 1]
            if pos[i] != pos[i - 1]:
                trades += 1
            peak = max(peak, eq)
            dd = min(dd, eq / peak - 1)
        out.append({"id": rule, "name": name, "ret": (eq - 1) * 100, "trades": trades, "maxdd": dd * 100,
                    "invested_now": bool(pos[-1])})
    bh = v[-1] / v[start] - 1
    return {"days": len(v) - start, "buyhold": bh * 100, "buyhold_dd": max_drawdown(v[start:]), "rules": out}


def analyse(dates, v):
    """dates/v: sorterade dagliga stängningar. Returnerar nyckeltal, signaler och backtest."""
    if len(v) < 30:
        return {"error": "För lite kurshistorik (%d dagar) för att beräkna signaler." % len(v)}
    last = v[-1]
    y = v[-252:] if len(v) >= 252 else v
    hi, lo = max(y), min(y)
    s = lambda n: sma(v, n)
    inds = indicators(v)
    return {
        "as_of": dates[-1], "days": len(v), "price": last,
        "metrics": {
            "ret": {k: ret(v, d) for k, d in (("1d", 1), ("1w", 5), ("1m", 21), ("3m", 63), ("6m", 126), ("12m", 252))},
            "high52": hi, "low52": lo, "from_high": (last / hi - 1) * 100, "from_low": (last / lo - 1) * 100,
            "vol60": volatility(v), "maxdd1y": max_drawdown(y),
            "sma20": s(20), "sma50": s(50), "sma200": s(200), "rsi14": rsi(v),
        },
        "indicators": inds, "verdict": verdict(inds), "backtest": backtest(v),
    }
