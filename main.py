import os
import time
import math
import requests
from datetime import datetime, timezone

BOT_TOKEN = os.getenv("BOT_TOKEN")
RAW_CHANNEL_ID = os.getenv("CHANNEL_ID", "1003553154123")

SCAN_INTERVAL_MINUTES = int(os.getenv("SCAN_INTERVAL_MINUTES", "30"))
TOP_N = int(os.getenv("TOP_N", "5"))
MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", "7.0"))

BINANCE = "https://fapi.binance.com"


SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "XRPUSDT", "BNBUSDT", "SOLUSDT", "DOGEUSDT",
    "TRXUSDT", "ADAUSDT", "SUIUSDT", "LINKUSDT", "HYPEUSDT", "MNTUSDT",
    "XLMUSDT", "BCHUSDT", "AVAXUSDT", "HBARUSDT", "WIFUSDT", "LTCUSDT",
    "ENAUSDT", "UNIUSDT", "WLFIUSDT", "TAOUSDT", "ETCUSDT", "NEARUSDT",
    "APTUSDT", "POLUSDT", "DOTUSDT", "CROUSDT", "AAVEUSDT", "CHRUSDT",
    "XMRUSDT", "ARBUSDT", "ICPUSDT", "KASUSDT", "ALGOUSDT", "VETUSDT",
    "ATOMUSDT", "WLDUSDT", "SEIUSDT", "FILUSDT", "OPUSDT", "QNTUSDT",
    "LDOUSDT", "CRVUSDT", "STXUSDT", "FLOWUSDT", "GRTUSDT", "BLURUSDT",
    "YGGUSDT", "CELOUSDT", "ZILUSDT", "ACHUSDT", "WOOUSDT", "TWTUSDT",
    "IMXUSDT", "CFXUSDT", "MINAUSDT", "SUSHIUSDT", "ENJUSDT", "1INCHUSDT",
    "INJUSDT", "SANDUSDT", "EGLDUSDT", "GALAUSDT", "ANKRUSDT", "SKLUSDT",
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
        print("GET error:", path, params, e)
        return None


def send_telegram(text):
    if not BOT_TOKEN:
        print("BOT_TOKEN missing")
        print(text)
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHANNEL_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        r = requests.post(url, json=payload, timeout=12)
        print("Telegram:", r.status_code, r.text[:200])
    except Exception as e:
        print("Telegram error:", e)


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

    change_1 = (closes[-1] - opens[-1]) / opens[-1] * 100 if opens[-1] else 0
    change_5 = (closes[-1] - closes[-6]) / closes[-6] * 100 if closes[-6] else 0
    change_20 = (closes[-1] - closes[-21]) / closes[-21] * 100 if closes[-21] else 0

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

    support_20 = min(lows[-20:])
    resistance_20 = max(highs[-20:])
    support_50 = min(lows[-50:])
    resistance_50 = max(highs[-50:])

    high_20 = max(highs[-20:])
    low_20 = min(lows[-20:])

    return {
        "price": price,
        "open": opens[-1],
        "high": highs[-1],
        "low": lows[-1],
        "close": closes[-1],
        "change_1": change_1,
        "change_5": change_5,
        "change_20": change_20,
        "atr_pct": atr_pct,
        "vol_ratio": vol_ratio,
        "volume_20": sum(volumes_usdt[-20:]),
        "ema20": ema(closes, 20),
        "ema50": ema(closes, 50),
        "ema100": ema(closes, 100),
        "support_20": support_20,
        "resistance_20": resistance_20,
        "support_50": support_50,
        "resistance_50": resistance_50,
        "high_20": high_20,
        "low_20": low_20,
        "closes": closes,
        "highs": highs,
        "lows": lows,
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
    data = get_json("/fapi/v1/fundingRate", {
        "symbol": symbol,
        "limit": 1
    })

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
        return {
            "quote_volume": 0,
            "price_change_pct": 0,
            "count": 0,
        }


def pct_distance(price, level):
    if price <= 0:
        return 0.0
    return (level - price) / price * 100


def abs_pct_distance(price, level):
    return abs(pct_distance(price, level))


def get_btc_context():
    m15 = get_candles("BTCUSDT", "15m")
    h1 = get_candles("BTCUSDT", "1h")
    h4 = get_candles("BTCUSDT", "4h")

    if not m15 or not h1 or not h4:
        return {
            "bias": "NEUTRAL",
            "mode": "DIRTY",
            "btc_15m": 0,
            "btc_1h": 0,
            "btc_4h": 0,
            "risk": 0,
        }

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

    if mode == "BULL":
        bias = "BULLISH"
    elif mode == "BEAR":
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    risk = 0
    if abs(btc_15m) > 0.7:
        risk += 1
    if abs(btc_1h) > 1.2:
        risk += 1
    if abs(btc_4h) > 2.5:
        risk += 1

    return {
        "bias": bias,
        "mode": mode,
        "btc_15m": btc_15m,
        "btc_1h": btc_1h,
        "btc_4h": btc_4h,
        "risk": risk,
    }


def relative_strength_engine(m15, h1, h4, btc):
    rs15 = m15["change_1"] - btc["btc_15m"]
    rs1h = h1["change_1"] - btc["btc_1h"]
    rs4h = h4["change_1"] - btc["btc_4h"]

    score_long = 0
    score_short = 0
    note = ""

    weighted = rs15 * 0.25 + rs1h * 0.45 + rs4h * 0.30

    if btc["mode"] == "FLAT" and weighted > 0.8:
        score_long += 1.8
        note = "RS strong while BTC flat"
    elif btc["mode"] == "BEAR" and weighted > 0.5:
        score_long += 2.2
        note = "holds strong while BTC weak"
    elif btc["mode"] == "BULL" and weighted < -0.7:
        score_short += 1.8
        note = "weak while BTC bullish"
    elif weighted > 0.6:
        score_long += 1.2
        note = "strong vs BTC"
    elif weighted < -0.6:
        score_short += 1.2
        note = "weak vs BTC"

    return score_long, score_short, weighted, note


def oi_smart_engine(h1, oi15, oi1h):
    score_long = 0
    score_short = 0
    warning = ""
    note = ""

    price_up = h1["change_1"] > 0.15
    price_down = h1["change_1"] < -0.15
    oi_up = oi15 > 0.25 or oi1h > 0.7
    oi_down = oi15 < -0.35 or oi1h < -0.8

    if price_up and oi_up:
        score_long += 1.6
        note = "price up + OI up"
    elif price_down and oi_up:
        score_short += 1.6
        note = "price down + OI up"
    elif price_up and oi_down:
        score_long -= 0.7
        warning = "price up but OI falling"
    elif price_down and oi_down:
        score_short -= 0.7
        warning = "price down but OI falling"

    return score_long, score_short, note, warning


def funding_engine(funding):
    score_long = 0
    score_short = 0
    note = ""
    warning = ""

    if funding > 0.05:
        score_short += 1.4
        score_long -= 1.1
        warning = "funding very hot"
    elif funding > 0.03:
        score_short += 0.9
        score_long -= 0.6
        warning = "funding hot"
    elif funding < -0.025:
        score_long += 1.4
        score_short -= 1.1
        note = "funding very negative"
    elif funding < -0.01:
        score_long += 0.9
        score_short -= 0.6
        note = "funding negative"
    else:
        score_long += 0.25
        score_short += 0.25
        note = "funding neutral"

    return score_long, score_short, note, warning


def atr_filter_engine(h1):
    atr = h1["atr_pct"]
    score = 0
    warning = ""

    if 0.45 <= atr <= 3.8:
        score += 0.7
    elif atr < 0.25:
        score -= 0.8
        warning = "ATR too low"
    elif atr > 6.0:
        score -= 1.2
        warning = "ATR too high"
    elif atr > 4.5:
        score -= 0.5
        warning = "ATR elevated"

    return score, warning


def distance_filter_engine(price, h4, d1):
    score_long = 0
    score_short = 0
    warnings = []

    dist_4h_res = pct_distance(price, h4["resistance_50"])
    dist_4h_sup = abs_pct_distance(price, h4["support_50"])

    dist_1d_res = pct_distance(price, d1["resistance_50"])
    dist_1d_sup = abs_pct_distance(price, d1["support_50"])

    if dist_4h_res < 2.5:
        score_long -= 1.6
        warnings.append(f"near 4H resistance {dist_4h_res:.2f}%")

    if dist_1d_res < 3.5:
        score_long -= 1.2
        warnings.append(f"near 1D resistance {dist_1d_res:.2f}%")

    if dist_4h_sup < 2.5:
        score_short -= 1.6
        warnings.append(f"near 4H support {dist_4h_sup:.2f}%")

    if dist_1d_sup < 3.5:
        score_short -= 1.2
        warnings.append(f"near 1D support {dist_1d_sup:.2f}%")

    return score_long, score_short, dist_4h_res, dist_4h_sup, dist_1d_res, dist_1d_sup, warnings


def liquidity_rating_engine(ticker):
    volume = ticker["quote_volume"]
    trades = ticker["count"]

    score = 0
    rating = "LOW"

    if volume >= 300_000_000 and trades >= 250_000:
        score = 1.2
        rating = "HIGH"
    elif volume >= 80_000_000 and trades >= 80_000:
        score = 0.8
        rating = "GOOD"
    elif volume >= 20_000_000 and trades >= 25_000:
        score = 0.4
        rating = "OK"
    else:
        score = -1.0
        rating = "LOW"

    return score, rating


def smart_pullback_engine(h1, h4):
    score_long = 0
    score_short = 0
    warning = ""
    note = ""

    # Защита от покупки после вертикального пампа
    if h1["change_5"] > 6:
        score_long -= 1.4
        warning = "after strong pump, wait pullback"
    elif h1["change_5"] < -6:
        score_short -= 1.4
        warning = "after strong dump, wait pullback"

    # Хороший лонг после отката в локальном ап-тренде
    if h4["ema20"] > h4["ema50"] and -2.5 <= h1["change_5"] <= -0.3:
        score_long += 1.0
        note = "smart pullback long"

    # Хороший шорт после отскока в локальном даун-тренде
    if h4["ema20"] < h4["ema50"] and 0.3 <= h1["change_5"] <= 2.5:
        score_short += 1.0
        note = "smart pullback short"

    return score_long, score_short, note, warning


def fake_breakout_engine(price, h1):
    score_long = 0
    score_short = 0
    warning = ""

    prev_high = h1["high_20"]
    prev_low = h1["low_20"]

    # Если цена резко выше диапазона, но свеча закрылась обратно — подозрение на ложный пробой
    if h1["high"] > prev_high * 1.003 and price < prev_high:
        score_long -= 1.0
        score_short += 0.6
        warning = "possible fake breakout high"

    if h1["low"] < prev_low * 0.997 and price > prev_low:
        score_short -= 1.0
        score_long += 0.6
        warning = "possible fake breakdown low"

    return score_long, score_short, warning


def momentum_score_engine(m15, h1, h4):
    score_long = 0
    score_short = 0
    momentum = 0

    momentum = (
        m15["change_1"] * 0.25 +
        h1["change_1"] * 0.45 +
        h4["change_1"] * 0.30
    )

    if 0.3 <= momentum <= 4.5:
        score_long += min(1.4, momentum / 2.5)
    elif momentum > 6:
        score_long -= 0.8

    if -4.5 <= momentum <= -0.3:
        score_short += min(1.4, abs(momentum) / 2.5)
    elif momentum < -6:
        score_short -= 0.8

    return score_long, score_short, momentum


def structure_engine(h1, h4, d1):
    score_long = 0
    score_short = 0
    reasons_long = []
    reasons_short = []

    if h4["ema20"] > h4["ema50"]:
        score_long += 1.1
        reasons_long.append("4H trend up")
    else:
        score_short += 1.1
        reasons_short.append("4H trend down")

    if d1["ema20"] > d1["ema50"]:
        score_long += 1.2
        reasons_long.append("Daily trend up")
    else:
        score_short += 1.2
        reasons_short.append("Daily trend down")
        score_long -= 0.4

    if h1["ema20"] > h1["ema50"]:
        score_long += 0.7
        reasons_long.append("1H trend up")
    else:
        score_short += 0.7
        reasons_short.append("1H trend down")

    return score_long, score_short, reasons_long, reasons_short


def btc_filter_engine(btc):
    score_long = 0
    score_short = 0
    warning = ""

    if btc["mode"] == "BULL":
        score_long += 0.8
        score_short -= 0.3
    elif btc["mode"] == "BEAR":
        score_short += 0.8
        score_long -= 0.3
    elif btc["mode"] == "FLAT":
        score_long += 0.2
        score_short += 0.2
    else:
        score_long -= 0.3
        score_short -= 0.3
        warning = "BTC dirty"

    if btc["risk"] >= 2:
        score_long -= 0.5
        score_short -= 0.5
        warning = "BTC volatile"

    return score_long, score_short, warning


def create_watch_level(direction, price, h1, h4):
    if direction == "LONG":
        base = max(h1["support_20"], price * 0.97)
        watch = max(base, price * 0.985)
        return watch, "WATCH LONG"
    else:
        base = min(h1["resistance_20"], price * 1.03)
        watch = min(base, price * 1.015)
        return watch, "WATCH SHORT"


def risk_reward_filter(direction, price, entry1, invalidation, tp1, tp2):
    if direction == "LONG":
        risk = abs(entry1 - invalidation)
        reward = abs(tp1 - entry1)
    else:
        risk = abs(invalidation - entry1)
        reward = abs(entry1 - tp1)

    rr = reward / risk if risk > 0 else 0

    penalty = 0
    warning = ""

    if rr < 0.55:
        penalty = -1.2
        warning = f"poor RR {rr:.2f}"
    elif rr < 0.75:
        penalty = -0.6
        warning = f"weak RR {rr:.2f}"

    return rr, penalty, warning


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

    # 1. Structure
    s_long, s_short, r_long, r_short = structure_engine(h1, h4, d1)
    long_score += s_long
    short_score += s_short
    reasons_long += r_long
    reasons_short += r_short

    # 2. Relative Strength Engine
    rs_long, rs_short, rs_value, rs_note = relative_strength_engine(m15, h1, h4, btc)
    long_score += rs_long
    short_score += rs_short
    if rs_note:
        if rs_long >= rs_short:
            reasons_long.append(rs_note)
        else:
            reasons_short.append(rs_note)

    # 3. Open Interest Smart
    oi_long, oi_short, oi_note, oi_warning = oi_smart_engine(h1, oi15, oi1h)
    long_score += oi_long
    short_score += oi_short
    if oi_note:
        if oi_long >= oi_short:
            reasons_long.append(oi_note)
        else:
            reasons_short.append(oi_note)
    if oi_warning:
        warnings.append(oi_warning)

    # 4. Funding Engine
    f_long, f_short, f_note, f_warning = funding_engine(funding)
    long_score += f_long
    short_score += f_short
    if f_note:
        if f_long >= f_short:
            reasons_long.append(f_note)
        else:
            reasons_short.append(f_note)
    if f_warning:
        warnings.append(f_warning)

    # 5. ATR Filter
    atr_score, atr_warning = atr_filter_engine(h1)
    long_score += atr_score
    short_score += atr_score
    if atr_warning:
        warnings.append(atr_warning)

    # 6. Distance Filter
    d_long, d_short, dist_4h_res, dist_4h_sup, dist_1d_res, dist_1d_sup, d_warnings = distance_filter_engine(price, h4, d1)
    long_score += d_long
    short_score += d_short
    warnings += d_warnings

    # 7. BTC Context
    b_long, b_short, btc_warning = btc_filter_engine(btc)
    long_score += b_long
    short_score += b_short
    if btc_warning:
        warnings.append(btc_warning)

    # 8. Liquidity Rating
    liq_score, liquidity_rating = liquidity_rating_engine(ticker)
    long_score += liq_score
    short_score += liq_score
    if liquidity_rating == "LOW":
        warnings.append("low liquidity")

    # Extra 1. Smart Pullback
    p_long, p_short, p_note, p_warning = smart_pullback_engine(h1, h4)
    long_score += p_long
    short_score += p_short
    if p_note:
        if p_long >= p_short:
            reasons_long.append(p_note)
        else:
            reasons_short.append(p_note)
    if p_warning:
        warnings.append(p_warning)

    # Extra 2. Fake Breakout Detector
    fb_long, fb_short, fb_warning = fake_breakout_engine(price, h1)
    long_score += fb_long
    short_score += fb_short
    if fb_warning:
        warnings.append(fb_warning)

    # Extra 3. Momentum Score
    mom_long, mom_short, momentum = momentum_score_engine(m15, h1, h4)
    long_score += mom_long
    short_score += mom_short
    if mom_long > mom_short:
        reasons_long.append("momentum score positive")
    elif mom_short > mom_long:
        reasons_short.append("momentum score negative")

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

    # Watch Level
    watch_level, watc
