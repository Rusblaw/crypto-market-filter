import os
import time
import requests
from datetime import datetime, timezone

BOT_TOKEN = os.getenv("BOT_TOKEN")
RAW_CHANNEL_ID = os.getenv("CHANNEL_ID", "1003553154123")

SCAN_INTERVAL_MINUTES = int(os.getenv("SCAN_INTERVAL_MINUTES", "30"))
TOP_N = int(os.getenv("TOP_N", "5"))
MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", "7.0"))

BINANCE = "https://fapi.binance.com"

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "XRPUSDT", "BNBUSDT", "SOLUSDT", "SUIUSDT",
    "ADAUSDT", "BCHUSDT", "ALGOUSDT", "INJUSDT", "DOGEUSDT",
    "NEARUSDT", "ICPUSDT", "XLMUSDT", "TAOUSDT", "FILUSDT",
    "ATOMUSDT", "LINKUSDT", "APTUSDT", "ARBUSDT", "ZECUSDT"
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
        print("Telegram:", r.status_code, r.text[:150])
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


def get_candles(symbol, interval, limit=150):
    data = get_json("/fapi/v1/klines", {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    })

    if not data or len(data) < 60:
        return None

    opens = [float(x[1]) for x in data]
    highs = [float(x[2]) for x in data]
    lows = [float(x[3]) for x in data]
    closes = [float(x[4]) for x in data]
    volumes_usdt = [float(x[7]) for x in data]

    price = closes[-1]

    change_last = (closes[-1] - opens[-1]) / opens[-1] * 100 if opens[-1] else 0
    change_5 = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) > 6 and closes[-6] else 0
    change_20 = (closes[-1] - closes[-21]) / closes[-21] * 100 if len(closes) > 21 and closes[-21] else 0

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

    avg_vol = sum(volumes_usdt[-80:-20]) / max(1, len(volumes_usdt[-80:-20]))
    recent_vol = sum(volumes_usdt[-5:]) / 5
    vol_ratio = recent_vol / avg_vol if avg_vol else 1

    return {
        "price": price,
        "change_last": change_last,
        "change_5": change_5,
        "change_20": change_20,
        "atr_pct": atr_pct,
        "vol_ratio": vol_ratio,
        "ema20": ema(closes, 20),
        "ema50": ema(closes, 50),
        "ema100": ema(closes, 100),
        "support": min(lows[-40:]),
        "resistance": max(highs[-40:]),
        "support20": min(lows[-20:]),
        "resistance20": max(highs[-20:]),
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


def get_btc_context():
    h1 = get_candles("BTCUSDT", "1h")
    h4 = get_candles("BTCUSDT", "4h")

    if not h1 or not h4:
        return {"bias": "NEUTRAL", "btc_1h": 0, "btc_4h": 0}

    btc_1h = h1["change_last"]
    btc_4h = h4["change_last"]

    if btc_1h > 0.35 and btc_4h > 0:
        bias = "BULLISH"
    elif btc_1h < -0.35 and btc_4h < 0:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    return {
        "bias": bias,
        "btc_1h": btc_1h,
        "btc_4h": btc_4h,
    }


def distance_pct(price, level):
    if price <= 0:
        return 0
    return (level - price) / price * 100


def score_symbol(symbol, btc):
    d15 = get_candles(symbol, "15m")
    h1 = get_candles(symbol, "1h")
    h4 = get_candles(symbol, "4h")
    d1 = get_candles(symbol, "1d")

    if not d15 or not h1 or not h4 or not d1:
        return None

    price = h1["price"]
    oi15 = get_oi_change(symbol, "15m")
    oi1h = get_oi_change(symbol, "1h")
    funding = get_funding(symbol)

    long_score = 0.0
    short_score = 0.0
    long_reasons = []
    short_reasons = []
    warnings = []

    dist_to_res = distance_pct(price, h4["resistance"])
    dist_to_sup = abs(distance_pct(price, h4["support"]))

    daily_bear = d1["ema20"] < d1["ema50"]
    daily_bull = d1["ema20"] > d1["ema50"]

    # Higher timeframe structure
    if h4["ema20"] > h4["ema50"]:
        long_score += 1.2
        long_reasons.append("4H trend up")
    else:
        short_score += 1.2
        short_reasons.append("4H trend down")

    if daily_bull:
        long_score += 1.2
        long_reasons.append("Daily trend up")
    elif daily_bear:
        short_score += 1.2
        short_reasons.append("Daily trend down")
        long_score -= 0.8

    # Local momentum
    if d15["change_last"] > 0 and h1["change_last"] > 0:
        long_score += 1.0
        long_reasons.append("local momentum up")
    elif d15["change_last"] < 0 and h1["change_last"] < 0:
        short_score += 1.0
        short_reasons.append("local momentum down")

    # OI
    if oi15 > 0.35 or oi1h > 0.8:
        if h1["change_last"] > 0:
            long_score += 1.3
            long_reasons.append(f"OI rising {oi15:.2f}%/15m")
        elif h1["change_last"] < 0:
            short_score += 1.3
            short_reasons.append(f"OI rising {oi15:.2f}%/15m")

    if oi15 < -0.5:
        long_score -= 0.4
        short_score -= 0.4
        warnings.append("OI falling")

    # Funding
    if funding > 0.035:
        short_score += 1.1
        long_score -= 0.8
        short_reasons.append("funding hot")
    elif funding < -0.01:
        long_score += 1.1
        short_score -= 0.8
        long_reasons.append("funding negative")
    else:
        long_score += 0.3
        short_score += 0.3

    # Relative strength
    rs = h1["change_last"] - btc["btc_1h"]

    if rs > 0.45:
        long_score += 0.8
        long_reasons.append("strong vs BTC")
    elif rs < -0.45:
        short_score += 0.8
        short_reasons.append("weak vs BTC")

    # BTC filter
    if btc["bias"] == "BULLISH":
        long_score += 0.6
        short_score -= 0.3
    elif btc["bias"] == "BEARISH":
        short_score += 0.6
        long_score -= 0.3

    # Volume
    if h1["vol_ratio"] > 1.3:
        if h1["change_last"] > 0:
            long_score += 0.7
            long_reasons.append("volume impulse")
        else:
            short_score += 0.7
            short_reasons.append("volume impulse")

    # Main V3 protection: do not long directly under resistance
    if dist_to_res < 2.2:
        long_score -= 1.8
        warnings.append(f"near 4H resistance {dist_to_res:.2f}%")

    # Do not short directly above support
    if dist_to_sup < 2.2:
        short_score -= 1.8
        warnings.append(f"near 4H support {dist_to_sup:.2f}%")

    # ATR quality
    if 0.35 <= h1["atr_pct"] <= 4.0:
        long_score += 0.4
        short_score += 0.4
    elif h1["atr_pct"] > 6:
        long_score -= 0.8
        short_score -= 0.8
        warnings.append("ATR too high")

    direction = "LONG" if long_score >= short_score else "SHORT"
    raw_score = max(long_score, short_score)

    confidence = max(4.0, min(9.3, raw_score + 2.4))

    # Additional confidence cut
    if direction == "LONG" and daily_bear:
        confidence -= 0.7
        warnings.append("long against Daily trend")

    if direction == "SHORT" and daily_bull:
        confidence -= 0.7
        warnings.append("short against Daily trend")

    confidence = max(4.0, min(9.3, confidence))

    atr_pct = max(0.35, min(h1["atr_pct"], 4.0)) / 100

    if direction == "LONG":
        entry1 = price * (1 - atr_pct * 0.45)
        entry2 = price * (1 - atr_pct * 0.95)
        tp1 = price * 1.006
        tp2 = min(price * 1.014, h4["resistance"] * 0.995)
        invalidation = price * (1 - atr_pct * 1.9)
        reasons = long_reasons[:5]
    else:
        entry1 = price * (1 + atr_pct * 0.45)
        entry2 = price * (1 + atr_pct * 0.95)
        tp1 = price * 0.994
        tp2 = max(price * 0.986, h4["support"] * 1.005)
        invalidation = price * (1 + atr_pct * 1.9)
        reasons = short_reasons[:5]

    return {
        "symbol": symbol,
        "direction": direction,
        "confidence": confidence,
        "price": price,
        "ch15": d15["change_last"],
        "ch1": h1["change_last"],
        "ch4": h4["change_last"],
        "daily20": d1["change_20"],
        "oi15": oi15,
        "oi1h": oi1h,
        "funding": funding,
        "rs": rs,
        "atr": h1["atr_pct"],
        "dist_res": dist_to_res,
        "dist_sup": dist_to_sup,
        "entry1": entry1,
        "entry2": entry2,
        "tp1": tp1,
        "tp2": tp2,
        "invalidation": invalidation,
        "reasons": reasons,
        "warnings": warnings[:3],
    }


def fmt(x):
    if x >= 100:
        return f"{x:.2f}"
    if x >= 1:
        return f"{x:.4f}"
    return f"{x:.6f}"


def build_message(rows, btc):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    msg = "🔥 <b>DAILY COIN SCANNER V3</b>\n"
    msg += f"⏰ {now}\n"
    msg += "Источник: Binance Futures\n"
    msg += f"BTC: <b>{btc['bias']}</b> | 1H {btc['btc_1h']:.2f}% | 4H {btc['btc_4h']:.2f}%\n\n"

    if not rows:
        msg += f"Нет монет выше confidence {MIN_CONFIDENCE}.\n"
        return msg

    for i, r in enumerate(rows, 1):
        icon = "🟢" if r["direction"] == "LONG" else "🔴"

        msg += f"{i}) {icon} <b>{r['symbol']} — {r['direction']}</b>\n"
        msg += f"Confidence: <b>{r['confidence']:.1f}/10</b>\n"
        msg += f"Price: {fmt(r['price'])}\n"
        msg += f"15m {r['ch15']:.2f}% | 1H {r['ch1']:.2f}% | 4H {r['ch4']:.2f}%\n"
        msg += f"OI15 {r['oi15']:.2f}% | OI1H {r['oi1h']:.2f}% | Funding {r['funding']:.4f}%\n"
        msg += f"RS vs BTC: {r['rs']:.2f}% | ATR1H: {r['atr']:.2f}%\n"
        msg += f"До 4H resistance: {r['dist_res']:.2f}% | до 4H support: {r['dist_sup']:.2f}%\n"
        msg += f"Entry: <b>{fmt(r['entry1'])}</b> / <b>{fmt(r['entry2'])}</b>\n"
        msg += f"TP: {fmt(r['tp1'])} / {fmt(r['tp2'])}\n"
        msg += f"Invalidation: {fmt(r['invalidation'])}\n"
        msg += "Why: " + (", ".join(r["reasons"]) if r["reasons"] else "mixed signal") + "\n"
        if r["warnings"]:
            msg += "⚠️ " + ", ".join(r["warnings"]) + "\n"
        msg += "\n"

    msg += "⚠️ V3 уже фильтрует входы под сопротивлением, но финально всё равно проверяй график/стакан/BTC."
    return msg


def scan_once():
    btc = get_btc_context()
    results = []

    for symbol in SYMBOLS:
        print("Scanning", symbol)
        row = score_symbol(symbol, btc)
        if row and row["confidence"] >= MIN_CONFIDENCE:
            results.append(row)
        time.sleep(0.25)

    results.sort(key=lambda x: x["confidence"], reverse=True)
    send_telegram(build_message(results[:TOP_N], btc))


def main():
    send_telegram("✅ Daily Coin Scanner V3 started")

    while True:
        try:
            scan_once()
        except Exception as e:
            print("Main error:", e)
            send_telegram(f"⚠️ Scanner error: {e}")

        time.sleep(SCAN_INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    main()
