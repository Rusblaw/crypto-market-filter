import os
import time
import json
import requests
from datetime import datetime, timezone

print("BOT FILE STARTED", flush=True)

BOT_TOKEN = os.getenv("BOT_TOKEN")
RAW_CHANNEL_ID = os.getenv("CHANNEL_ID", "1003553154123")

SCAN_INTERVAL_MINUTES = int(os.getenv("SCAN_INTERVAL_MINUTES", "30"))
TOP_N = int(os.getenv("TOP_N", "5"))
MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", "7.0"))
SIGNALS_FILE = "signals.json"
SIGNAL_EXPIRY_HOURS = 24
BINANCE = "https://fapi.binance.com"

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "XRPUSDT", "BNBUSDT", "SOLUSDT", "DOGEUSDT",
    "TRXUSDT", "ADAUSDT", "SUIUSDT", "LINKUSDT", "HYPEUSDT", "MNTUSDT",
    "XLMUSDT", "BCHUSDT", "AVAXUSDT", "HBARUSDT", "WIFUSDT", "LTCUSDT",
    "ENAUSDT", "UNIUSDT", "WLFIUSDT", "TAOUSDT", "ETCUSDT", "NEARUSDT",
    "APTUSDT", "POLUSDT", "DOTUSDT", "AAVEUSDT", "XMRUSDT", "ARBUSDT",
    "ICPUSDT", "KASUSDT", "ALGOUSDT", "VETUSDT", "ATOMUSDT", "WLDUSDT",
    "SEIUSDT", "FILUSDT", "OPUSDT", "QNTUSDT", "LDOUSDT", "CRVUSDT",
    "STXUSDT", "FLOWUSDT", "GRTUSDT", "BLURUSDT", "YGGUSDT", "CELOUSDT",
    "ZILUSDT", "ACHUSDT", "WOOUSDT", "TWTUSDT", "IMXUSDT", "CFXUSDT",
    "MINAUSDT", "SUSHIUSDT", "ENJUSDT", "1INCHUSDT", "INJUSDT",
    "SANDUSDT", "EGLDUSDT", "GALAUSDT", "ANKRUSDT", "SKLUSDT",
    "CVCUSDT", "COREUSDT", "ASTERUSDT", "XPLUSDT", "PUMPFUNUSDT"
]


def normalize_channel_id(value):
    value = str(value).strip()
    if value.startswith("-"):
        return value
    if value.startswith("100"):
        return "-" + value
    return value


CHANNEL_ID = normalize_channel_id(RAW_CHANNEL_ID)


def get_json(path, params=None, timeout=12):
    try:
        r = requests.get(BINANCE + path, params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"GET error {path} {params}: {e}", flush=True)
        return None


def send_telegram(text):
    if not BOT_TOKEN:
        print("BOT_TOKEN missing", flush=True)
        print(text, flush=True)
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHANNEL_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        r = requests.post(url, json=payload, timeout=15)
        print("Telegram:", r.status_code, r.text[:200], flush=True)
    except Exception as e:
        print("Telegram error:", e, flush=True)


def ema(values, period):
    if len(values) < period:
        return values[-1]
    k = 2 / (period + 1)
    result = sum(values[:period]) / period
    for v in values[period:]:
        result = v * k + result * (1 - k)
    return result


def get_exchange_symbols():
    data = get_json("/fapi/v1/exchangeInfo")
    valid = set()
    try:
        for item in data["symbols"]:
            if item.get("contractType") == "PERPETUAL" and item.get("quoteAsset") == "USDT":
                valid.add(item["symbol"])
    except Exception:
        pass
    return valid


def get_candles(symbol, interval, limit=180):
    data = get_json("/fapi/v1/klines", {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    })

    if not data or len(data) < 80:
        return None

    opens = [float(x[1]) for x in data]
    highs = [float(x[2]) for x in data]
    lows = [float(x[3]) for x in data]
    closes = [float(x[4]) for x in data]
    volumes_usdt = [float(x[7]) for x in data]

    price = closes[-1]

    def pct(a, b):
        return (a - b) / b * 100 if b else 0.0

    tr_list = []
    for i in range(1, len(data)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        )
        tr_list.append(tr)

    atr = sum(tr_list[-14:]) / 14 if len(tr_list) >= 14 else 0
    atr_pct = atr / price * 100 if price else 0

    avg_vol = sum(volumes_usdt[-100:-20]) / max(1, len(volumes_usdt[-100:-20]))
    recent_vol = sum(volumes_usdt[-5:]) / 5
    vol_ratio = recent_vol / avg_vol if avg_vol else 1

    return {
        "price": price,
        "open": opens[-1],
        "high": highs[-1],
        "low": lows[-1],
        "close": closes[-1],
        "change_1": pct(closes[-1], opens[-1]),
        "change_5": pct(closes[-1], closes[-6]) if len(closes) > 6 else 0,
        "change_20": pct(closes[-1], closes[-21]) if len(closes) > 21 else 0,
        "atr_pct": atr_pct,
        "vol_ratio": vol_ratio,
        "volume_20": sum(volumes_usdt[-20:]),
        "ema20": ema(closes, 20),
        "ema50": ema(closes, 50),
        "ema100": ema(closes, 100),
        "support_20": min(lows[-20:]),
        "resistance_20": max(highs[-20:]),
        "support_50": min(lows[-50:]),
        "resistance_50": max(highs[-50:]),
        "high_20": max(highs[-20:]),
        "low_20": min(lows[-20:]),
    }


def get_oi_change(symbol, period="15m"):
    data = get_json("/futures/data/openInterestHist", {
        "symbol": symbol,
        "period": period,
        "limit": 2
    })

    try:
        if not data or len(data) < 2:
            return 0.0
        prev = float(data[0]["sumOpenInterestValue"])
        latest = float(data[1]["sumOpenInterestValue"])
        return (latest - prev) / prev * 100 if prev else 0.0
    except Exception:
        return 0.0


def get_funding(symbol):
    data = get_json("/fapi/v1/fundingRate", {"symbol": symbol, "limit": 1})
    try:
        return float(data[0]["fundingRate"]) * 100
    except Exception:
        return 0.0


def get_ticker_24h(symbol):
    data = get_json("/fapi/v1/ticker/24hr", {"symbol": symbol})
    try:
        return {
            "quote_volume": float(data.get("quoteVolume", 0)),
            "price_change_pct": float(data.get("priceChangePercent", 0)),
            "count": int(data.get("count", 0)),
        }
    except Exception:
        return {"quote_volume": 0, "price_change_pct": 0, "count": 0}


def pct_distance(price, level):
    return (level - price) / price * 100 if price else 0.0


def abs_pct_distance(price, level):
    return abs(pct_distance(price, level))


def get_btc_context():
    m15 = get_candles("BTCUSDT", "15m")
    h1 = get_candles("BTCUSDT", "1h")
    h4 = get_candles("BTCUSDT", "4h")

    if not m15 or not h1 or not h4:
        return {"mode": "DIRTY", "btc_15m": 0, "btc_1h": 0, "btc_4h": 0, "risk": 0}

    btc_15m = m15["change_1"]
    btc_1h = h1["change_1"]
    btc_4h = h4["change_1"]

    if abs(btc_1h) < 0.25 and abs(btc_4h) < 0.7:
        mode = "FLAT"
    elif btc_1h > 0.35 and btc_4h > 0:
        mode = "BULL"
    elif btc_1h < -0.35 and btc_4h < 0:
        mode = "BEAR"
    else:
        mode = "DIRTY"

    risk = 0
    if abs(btc_15m) > 0.7:
        risk += 1
    if abs(btc_1h) > 1.2:
        risk += 1
    if abs(btc_4h) > 2.5:
        risk += 1

    return {"mode": mode, "btc_15m": btc_15m, "btc_1h": btc_1h, "btc_4h": btc_4h, "risk": risk}


def relative_strength_engine(m15, h1, h4, btc):
    rs15 = m15["change_1"] - btc["btc_15m"]
    rs1h = h1["change_1"] - btc["btc_1h"]
    rs4h = h4["change_1"] - btc["btc_4h"]
    weighted = rs15 * 0.25 + rs1h * 0.45 + rs4h * 0.30

    long_score = 0
    short_score = 0
    note = ""

    if btc["mode"] == "FLAT" and weighted > 0.8:
        long_score += 1.8
        note = "RS strong while BTC flat"
    elif btc["mode"] == "BEAR" and weighted > 0.5:
        long_score += 2.2
        note = "strong while BTC weak"
    elif btc["mode"] == "BULL" and weighted < -0.7:
        short_score += 1.8
        note = "weak while BTC bullish"
    elif weighted > 0.6:
        long_score += 1.2
        note = "strong vs BTC"
    elif weighted < -0.6:
        short_score += 1.2
        note = "weak vs BTC"

    return long_score, short_score, weighted, note


def oi_smart_engine(h1, oi15, oi1h):
    long_score = 0
    short_score = 0
    note = ""
    warning = ""

    price_up = h1["change_1"] > 0.15
    price_down = h1["change_1"] < -0.15
    oi_up = oi15 > 0.25 or oi1h > 0.7
    oi_down = oi15 < -0.35 or oi1h < -0.8

    if price_up and oi_up:
        long_score += 1.6
        note = "price up + OI up"
    elif price_down and oi_up:
        short_score += 1.6
        note = "price down + OI up"
    elif price_up and oi_down:
        long_score -= 0.7
        warning = "price up but OI falling"
    elif price_down and oi_down:
        short_score -= 0.7
        warning = "price down but OI falling"

    return long_score, short_score, note, warning


def funding_engine(funding):
    long_score = 0
    short_score = 0
    note = ""
    warning = ""

    if funding > 0.05:
        short_score += 1.4
        long_score -= 1.1
        warning = "funding very hot"
    elif funding > 0.03:
        short_score += 0.9
        long_score -= 0.6
        warning = "funding hot"
    elif funding < -0.025:
        long_score += 1.4
        short_score -= 1.1
        note = "funding very negative"
    elif funding < -0.01:
        long_score += 0.9
        short_score -= 0.6
        note = "funding negative"
    else:
        long_score += 0.25
        short_score += 0.25
        note = "funding neutral"

    return long_score, short_score, note, warning


def atr_filter_engine(h1):
    atr = h1["atr_pct"]
    if 0.45 <= atr <= 3.8:
        return 0.7, ""
    if atr < 0.25:
        return -0.8, "ATR too low"
    if atr > 6.0:
        return -1.2, "ATR too high"
    if atr > 4.5:
        return -0.5, "ATR elevated"
    return 0, ""


def distance_filter_engine(price, h4, d1):
    long_score = 0
    short_score = 0
    warnings = []

    dist_4h_res = pct_distance(price, h4["resistance_50"])
    dist_4h_sup = abs_pct_distance(price, h4["support_50"])
    dist_1d_res = pct_distance(price, d1["resistance_50"])
    dist_1d_sup = abs_pct_distance(price, d1["support_50"])

    if dist_4h_res < 2.5:
        long_score -= 1.6
        warnings.append(f"near 4H resistance {dist_4h_res:.2f}%")
    if dist_1d_res < 3.5:
        long_score -= 1.2
        warnings.append(f"near 1D resistance {dist_1d_res:.2f}%")
    if dist_4h_sup < 2.5:
        short_score -= 1.6
        warnings.append(f"near 4H support {dist_4h_sup:.2f}%")
    if dist_1d_sup < 3.5:
        short_score -= 1.2
        warnings.append(f"near 1D support {dist_1d_sup:.2f}%")

    return long_score, short_score, dist_4h_res, dist_4h_sup, dist_1d_res, dist_1d_sup, warnings


def liquidity_rating_engine(ticker):
    volume = ticker["quote_volume"]
    trades = ticker["count"]

    if volume >= 300_000_000 and trades >= 250_000:
        return 1.2, "HIGH"
    if volume >= 80_000_000 and trades >= 80_000:
        return 0.8, "GOOD"
    if volume >= 20_000_000 and trades >= 25_000:
        return 0.4, "OK"
    return -1.0, "LOW"


def smart_pullback_engine(h1, h4):
    long_score = 0
    short_score = 0
    note = ""
    warning = ""

    if h1["change_5"] > 6:
        long_score -= 1.4
        warning = "after pump, wait pullback"
    elif h1["change_5"] < -6:
        short_score -= 1.4
        warning = "after dump, wait pullback"

    if h4["ema20"] > h4["ema50"] and -2.5 <= h1["change_5"] <= -0.3:
        long_score += 1.0
        note = "smart pullback long"

    if h4["ema20"] < h4["ema50"] and 0.3 <= h1["change_5"] <= 2.5:
        short_score += 1.0
        note = "smart pullback short"

    return long_score, short_score, note, warning


def fake_breakout_engine(price, h1):
    long_score = 0
    short_score = 0
    warning = ""

    prev_high = h1["high_20"]
    prev_low = h1["low_20"]

    if h1["high"] > prev_high * 1.003 and price < prev_high:
        long_score -= 1.0
        short_score += 0.6
        warning = "possible fake breakout high"

    if h1["low"] < prev_low * 0.997 and price > prev_low:
        short_score -= 1.0
        long_score += 0.6
        warning = "possible fake breakdown low"

    return long_score, short_score, warning


def momentum_score_engine(m15, h1, h4):
    momentum = m15["change_1"] * 0.25 + h1["change_1"] * 0.45 + h4["change_1"] * 0.30
    long_score = 0
    short_score = 0

    if 0.3 <= momentum <= 4.5:
        long_score += min(1.4, momentum / 2.5)
    elif momentum > 6:
        long_score -= 0.8

    if -4.5 <= momentum <= -0.3:
        short_score += min(1.4, abs(momentum) / 2.5)
    elif momentum < -6:
        short_score -= 0.8

    return long_score, short_score, momentum


def structure_engine(h1, h4, d1):
    long_score = 0
    short_score = 0
    reasons_long = []
    reasons_short = []

    if h4["ema20"] > h4["ema50"]:
        long_score += 1.1
        reasons_long.append("4H trend up")
    else:
        short_score += 1.1
        reasons_short.append("4H trend down")

    if d1["ema20"] > d1["ema50"]:
        long_score += 1.2
        reasons_long.append("Daily trend up")
    else:
        short_score += 1.2
        reasons_short.append("Daily trend down")
        long_score -= 0.4

    if h1["ema20"] > h1["ema50"]:
        long_score += 0.7
        reasons_long.append("1H trend up")
    else:
        short_score += 0.7
        reasons_short.append("1H trend down")

    return long_score, short_score, reasons_long, reasons_short


def btc_filter_engine(btc):
    long_score = 0
    short_score = 0
    warning = ""

    if btc["mode"] == "BULL":
        long_score += 0.8
        short_score -= 0.3
    elif btc["mode"] == "BEAR":
        short_score += 0.8
        long_score -= 0.3
    elif btc["mode"] == "FLAT":
        long_score += 0.2
        short_score += 0.2
    else:
        long_score -= 0.3
        short_score -= 0.3
        warning = "BTC dirty"

    if btc["risk"] >= 2:
        long_score -= 0.5
        short_score -= 0.5
        warning = "BTC volatile"

    return long_score, short_score, warning


def create_watch_level(direction, price, h1):
    if direction == "LONG":
        watch = max(h1["support_20"], price * 0.985)
        return watch, "WATCH LONG"
    watch = min(h1["resistance_20"], price * 1.015)
    return watch, "WATCH SHORT"


def risk_reward_filter(direction, entry1, invalidation, tp1):
    if direction == "LONG":
        risk = abs(entry1 - invalidation)
        reward = abs(tp1 - entry1)
    else:
        risk = abs(invalidation - entry1)
        reward = abs(entry1 - tp1)

    rr = reward / risk if risk > 0 else 0

    if rr < 0.55:
        return rr, -1.2, f"poor RR {rr:.2f}"
    if rr < 0.75:
        return rr, -0.6, f"weak RR {rr:.2f}"
    return rr, 0, ""


def score_symbol(symbol, btc):
    m15 = get_candles(symbol, "15m")
    h1 = get_candles(symbol, "1h")
    h4 = get_candles(symbol, "4h")
    d1 = get_candles(symbol, "1d")

    if not m15 or not h1 or not h4 or not d1:
        return None

    price = h1["price"]
    oi15 = get_oi_change(symbol, "15m")
    oi1h = get_oi_change(symbol, "1h")
    funding = get_funding(symbol)
    ticker = get_ticker_24h(symbol)

    long_score = 0.0
    short_score = 0.0
    reasons_long = []
    reasons_short = []
    warnings = []

    s_long, s_short, r_long, r_short = structure_engine(h1, h4, d1)
    long_score += s_long
    short_score += s_short
    reasons_long += r_long
    reasons_short += r_short

    rs_long, rs_short, rs_value, rs_note = relative_strength_engine(m15, h1, h4, btc)
    long_score += rs_long
    short_score += rs_short
    if rs_note:
        (reasons_long if rs_long >= rs_short else reasons_short).append(rs_note)

    oi_long, oi_short, oi_note, oi_warning = oi_smart_engine(h1, oi15, oi1h)
    long_score += oi_long
    short_score += oi_short
    if oi_note:
        (reasons_long if oi_long >= oi_short else reasons_short).append(oi_note)
    if oi_warning:
        warnings.append(oi_warning)

    f_long, f_short, f_note, f_warning = funding_engine(funding)
    long_score += f_long
    short_score += f_short
    if f_note:
        (reasons_long if f_long >= f_short else reasons_short).append(f_note)
    if f_warning:
        warnings.append(f_warning)

    atr_score, atr_warning = atr_filter_engine(h1)
    long_score += atr_score
    short_score += atr_score
    if atr_warning:
        warnings.append(atr_warning)

    d_long, d_short, dist_4h_res, dist_4h_sup, dist_1d_res, dist_1d_sup, d_warnings = distance_filter_engine(price, h4, d1)
    long_score += d_long
    short_score += d_short
    warnings += d_warnings

    b_long, b_short, btc_warning = btc_filter_engine(btc)
    long_score += b_long
    short_score += b_short
    if btc_warning:
        warnings.append(btc_warning)

    liq_score, liquidity_rating = liquidity_rating_engine(ticker)
    long_score += liq_score
    short_score += liq_score
    if liquidity_rating == "LOW":
        warnings.append("low liquidity")

    p_long, p_short, p_note, p_warning = smart_pullback_engine(h1, h4)
    long_score += p_long
    short_score += p_short
    if p_note:
        (reasons_long if p_long >= p_short else reasons_short).append(p_note)
    if p_warning:
        warnings.append(p_warning)

    fb_long, fb_short, fb_warning = fake_breakout_engine(price, h1)
    long_score += fb_long
    short_score += fb_short
    if fb_warning:
        warnings.append(fb_warning)

    mom_long, mom_short, momentum = momentum_score_engine(m15, h1, h4)
    long_score += mom_long
    short_score += mom_short
    if mom_long > mom_short:
        reasons_long.append("momentum positive")
    elif mom_short > mom_long:
        reasons_short.append("momentum negative")

    direction = "LONG" if long_score >= short_score else "SHORT"
    raw_score = max(long_score, short_score)

    atr_pct = max(0.45, min(h1["atr_pct"], 4.0)) / 100

    if direction == "LONG":
        entry1 = price * (1 - atr_pct * 0.45)
        entry2 = price * (1 - atr_pct * 0.95)
        tp1 = price * 1.006
        tp2 = min(price * 1.014, h4["resistance_50"] * 0.995)
        invalidation = price * (1 - atr_pct * 1.9)
        reasons = reasons_long[:6]
    else:
        entry1 = price * (1 + atr_pct * 0.45)
        entry2 = price * (1 + atr_pct * 0.95)
        tp1 = price * 0.994
        tp2 = max(price * 0.986, h4["support_50"] * 1.005)
        invalidation = price * (1 + atr_pct * 1.9)
        reasons = reasons_short[:6]

    watch_level, watch_type = create_watch_level(direction, price, h1)

    rr, rr_penalty, rr_warning = risk_reward_filter(direction, entry1, invalidation, tp1)
    raw_score += rr_penalty
    if rr_warning:
        warnings.append(rr_warning)

    confidence = max(4.0, min(9.6, raw_score + 2.2))

    if direction == "LONG" and d1["ema20"] < d1["ema50"]:
        confidence -= 0.5
        warnings.append("long vs Daily trend")

    if direction == "SHORT" and d1["ema20"] > d1["ema50"]:
        confidence -= 0.5
        warnings.append("short vs Daily trend")

    if liquidity_rating == "LOW":
        confidence -= 0.7

    confidence = max(4.0, min(9.6, confidence))

    return {
        "symbol": symbol,
        "direction": direction,
        "confidence": confidence,
        "price": price,
        "ch15": m15["change_1"],
        "ch1": h1["change_1"],
        "ch4": h4["change_1"],
        "oi15": oi15,
        "oi1h": oi1h,
        "funding": funding,
        "rs": rs_value,
        "momentum": momentum,
        "atr": h1["atr_pct"],
        "volume24": ticker["quote_volume"],
        "liquidity": liquidity_rating,
        "dist_4h_res": dist_4h_res,
        "dist_4h_sup": dist_4h_sup,
        "dist_1d_res": dist_1d_res,
        "dist_1d_sup": dist_1d_sup,
        "entry1": entry1,
        "entry2": entry2,
        "tp1": tp1,
        "tp2": tp2,
        "invalidation": invalidation,
        "watch_level": watch_level,
        "watch_type": watch_type,
        "rr": rr,
        "reasons": reasons,
        "warnings": warnings[:5],
    }


def fmt(x):
    if x >= 100:
        return f"{x:.2f}"
    if x >= 1:
        return f"{x:.4f}"
    return f"{x:.6f}"


def fmt_volume(x):
    if x >= 1_000_000_000:
        return f"{x / 1_000_000_000:.2f}B"
    if x >= 1_000_000:
        return f"{x / 1_000_000:.1f}M"
    if x >= 1_000:
        return f"{x / 1_000:.1f}K"
    return f"{x:.0f}"


def stars(confidence):
    full = int(round(confidence))
    full = max(1, min(10, full))
    return "⭐" * full

def now_ms():
    return int(time.time() * 1000)


def load_state():
    try:
        with open(SIGNALS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {
            "signals": [],
            "stats": {
                "total": 0,
                "wins": 0,
                "losses": 0,
                "expired": 0
            }
        }


def save_state(state):
    try:
        with open(SIGNALS_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print("Save state error:", e, flush=True)


def age_text(created_at_ms):
    minutes = int((now_ms() - created_at_ms) / 60000)
    h = minutes // 60
    m = minutes % 60
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"


def active_signals():
    state = load_state()
    return [
        s for s in state["signals"]
        if s.get("status") in ["WAITING", "ACTIVE"]
    ]


def active_symbols_set():
    return set(s["symbol"] for s in active_signals()) 
def register_new_signals(rows):
    state = load_state()

    for r in rows:
        state["signals"].append({
            "symbol": r["symbol"],
            "direction": r["direction"],
            "entry1": r["entry1"],
            "entry2": r["entry2"],
            "tp1": r["tp1"],
            "tp2": r["tp2"],
            "invalidation": r["invalidation"],
            "created": now_ms(),
            "status": "WAITING"
        })

    save_state(state)

def probability(confidence):
    return int(min(92, max(55, confidence * 10)))


def signal_type(r):
    reasons = " ".join(r.get("reasons", [])).lower()
    warnings = " ".join(r.get("warnings", [])).lower()

    if "pullback" in reasons:
        return "🔄 PULLBACK"
    if "fake" in warnings:
        return "⚠️ REVERSAL"
    if "momentum" in reasons or r.get("momentum", 0) > 1.2:
        return "🔥 MOMENTUM"
    if r.get("rs", 0) > 1.0:
        return "💪 RS LEADER"

    return "📊 SETUP"
def current_price(symbol):
    c = get_candles(symbol, "15m", 100)
    if not c:
        return None
    return c["price"]


def check_active_signals():
    state = load_state()
    events = []

    for s in state["signals"]:
        if s.get("status") not in ["WAITING", "ACTIVE"]:
            continue

        symbol = s["symbol"]
        direction = s["direction"]
        entry = float(s["entry1"])
        tp1 = float(s["tp1"])
        invalidation = float(s["invalidation"])
        created = int(s["created"])

        price = current_price(symbol)
        if price is None:
            continue

        age_hours = (now_ms() - created) / 1000 / 60 / 60

        if s["status"] == "WAITING":
            if age_hours >= SIGNAL_EXPIRY_HOURS:
                s["status"] = "EXPIRED"
                events.append(f"⏰ EXPIRED\n{symbol} {direction}\nEntry not touched in {SIGNAL_EXPIRY_HOURS}h")
                continue

            if direction == "LONG" and price <= entry:
                s["status"] = "ACTIVE"
                events.append(f"🟢 ENTRY TRIGGERED\n{symbol} LONG\nEntry: {fmt(entry)}\nCurrent: {fmt(price)}")

            if direction == "SHORT" and price >= entry:
                s["status"] = "ACTIVE"
                events.append(f"🔴 ENTRY TRIGGERED\n{symbol} SHORT\nEntry: {fmt(entry)}\nCurrent: {fmt(price)}")

        if s["status"] == "ACTIVE":
            if direction == "LONG":
                if price >= tp1:
                    s["status"] = "WIN"
                    events.append(f"✅ TP1 HIT\n{symbol} LONG WIN\nTP1: {fmt(tp1)}\nCurrent: {fmt(price)}")

                elif price <= invalidation:
                    s["status"] = "LOSS"
                    events.append(f"❌ INVALIDATED\n{symbol} LONG LOSS\nInvalidation: {fmt(invalidation)}\nCurrent: {fmt(price)}")

    save_state(state)

    if not events:
        return ""

    return "📊 <b>SIGNAL STATUS UPDATE</b>\n\n" + "\n\n".join(events[:10]) + "\n\n"

def build_message(rows, btc):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    msg = "🔥 <b>DAILY COIN SCANNER V4.1 ELITE</b>\n"
    msg += f"⏰ {now}\n"
    msg += "Источник: Binance Futures\n"
    msg += f"BTC: <b>{btc['mode']}</b> | 15m {btc['btc_15m']:.2f}% | 1H {btc['btc_1h']:.2f}% | 4H {btc['btc_4h']:.2f}%\n\n"

    if not rows:
        msg += f"❌ Нет монет выше confidence {MIN_CONFIDENCE}.\n"
        msg += "Лучше подождать, рынок без чистого edge."
        return msg

    best = rows[0]
    msg += f"🏆 <b>BEST COIN:</b> {best['symbol']} — {best['direction']} {best['confidence']:.1f}/10\n\n"

    for i, r in enumerate(rows, 1):
        icon = "🟢" if r["direction"] == "LONG" else "🔴"

        msg += f"{i}) {icon} <b>{r['symbol']} — {r['direction']}</b>\n"
        msg += f"{stars(r['confidence'])} <b>{r['confidence']:.1f}/10</b>\n"
        msg += f"{signal_type(r)} | Probability: <b>{probability(r['confidence'])}%</b>\n\n"

        msg += f"Price: {fmt(r['price'])}\n"
        msg += f"Entry: <b>{fmt(r['entry1'])}</b> / <b>{fmt(r['entry2'])}</b>\n"
        msg += f"TP: {fmt(r['tp1'])} / {fmt(r['tp2'])}\n"
        msg += f"Invalidation: {fmt(r['invalidation'])}\n"
        msg += f"👀 {r['watch_type']}: <b>{fmt(r['watch_level'])}</b>\n\n"

        msg += f"RR: <b>{r['rr']:.2f}</b>\n"
        msg += f"ATR1H: {r['atr']:.2f}%\n"
        msg += f"Funding: {r['funding']:.4f}%\n"
        msg += f"OI15: {r['oi15']:.2f}% | OI1H: {r['oi1h']:.2f}%\n"
        msg += f"RS vs BTC: {r['rs']:.2f}%\n"
        msg += f"Liquidity: {r['liquidity']} | Vol24: {fmt_volume(r['volume24'])}\n"

        msg += "Why: " + (", ".join(r["reasons"]) if r["reasons"] else "mixed signal") + "\n"

        if r["warnings"]:
            msg += "⚠️ " + ", ".join(r["warnings"]) + "\n"

        msg += "\n"

    msg += "⚠️ Это сканер. Перед лимитками проверяй график/стакан/BTC."
    return msg


def scan_once():
    print("SCAN STARTED", flush=True) 
    status_msg = check_active_signals()
    active_symbols = active_symbols_set()
    valid_symbols = get_exchange_symbols()
    btc = get_btc_context()
    results = []

    for symbol in SYMBOLS:
        if valid_symbols and symbol not in valid_symbols:
            print("Skip invalid:", symbol, flush=True)
            continue

        if symbol in active_symbols:
            print("Skip active:", symbol, flush=True)
            continue

        print("Scanning", symbol, flush=True)
        row = score_symbol(symbol, btc)

        if row and row["confidence"] >= MIN_CONFIDENCE:
            results.append(row)

        time.sleep(0.18)

    results.sort(key=lambda x: x["confidence"], reverse=True)
    top = results[:TOP_N]

    register_new_signals(top)

    send_telegram(status_msg + build_message(top, btc))
    print("SCAN FINISHED", flush=True)


def main():
    print("MAIN STARTED", flush=True)
    send_telegram("✅ Daily Coin Scanner V4 ELITE started")

    while True:
        try:
            scan_once()
        except Exception as e:

            print("Main error:", e, flush=True)
            send_telegram(f"⚠️ Scanner error: {e}")

        time.sleep(SCAN_INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    main()
