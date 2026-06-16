import os
import time
import requests
from datetime import datetime, timezone

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID", "-1003553154123")

SCAN_INTERVAL_MINUTES = int(os.getenv("SCAN_INTERVAL_MINUTES", "15"))
TOP_N = int(os.getenv("TOP_N", "5"))
MIN_CONFIDENCE = float(os.getenv("MIN_CONFIDENCE", "6.8"))

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "XRPUSDT", "BNBUSDT", "SOLUSDT", "SUIUSDT",
    "ADAUSDT", "BCHUSDT", "ALGOUSDT", "INJUSDT", "DOGEUSDT",
    "NEARUSDT", "ICPUSDT", "XLMUSDT", "TAOUSDT", "FILUSDT",
    "ATOMUSDT", "LINKUSDT", "APTUSDT", "ARBUSDT", "ZECUSDT"
]

BINANCE_FAPI = "https://fapi.binance.com"
BYBIT_API = "https://api.bybit.com"


def get_json(url, params=None, timeout=12):
    try:
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"GET error: {url} | {params} | {e}")
        return None


def send_telegram(text):
    if not BOT_TOKEN:
        print(text)
        print("BOT_TOKEN missing")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHANNEL_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:
        r = requests.post(url, json=payload, timeout=12)
        print("Telegram:", r.status_code, r.text[:150])
    except Exception as e:
        print("Telegram error:", e)


def klines(symbol, interval, limit=120):
    return get_json(
        f"{BINANCE_FAPI}/fapi/v1/klines",
        {"symbol": symbol, "interval": interval, "limit": limit}
    )


def candle_data(symbol, interval, limit=120):
    data = klines(symbol, interval, limit)
    if not data or len(data) < 30:
        return None

    opens = [float(x[1]) for x in data]
    highs = [float(x[2]) for x in data]
    lows = [float(x[3]) for x in data]
    closes = [float(x[4]) for x in data]
    volumes_usdt = [float(x[7]) for x in data]

    price = closes[-1]
    change = (closes[-1] - opens[0]) / opens[0] * 100 if opens[0] else 0
    vol_sum = sum(volumes_usdt[-20:])
    avg_vol = sum(volumes_usdt[-80:-20]) / max(1, len(volumes_usdt[-80:-20]))
    vol_ratio = (sum(volumes_usdt[-5:]) / 5) / avg_vol if avg_vol else 1

    recent_high = max(highs[-30:])
    recent_low = min(lows[-30:])
    support = min(lows[-20:])
    resistance = max(highs[-20:])

    atr_values = []
    for i in range(1, len(data)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        )
        atr_values.append(tr)

    atr = sum(atr_values[-14:]) / 14 if len(atr_values) >= 14 else 0
    atr_pct = atr / price * 100 if price else 0

    ema_fast = ema(closes, 20)
    ema_slow = ema(closes, 50)

    return {
        "price": price,
        "change": change,
        "volume": vol_sum,
        "vol_ratio": vol_ratio,
        "recent_high": recent_high,
        "recent_low": recent_low,
        "support": support,
        "resistance": resistance,
        "atr_pct": atr_pct,
        "ema_fast": ema_fast,
        "ema_slow": ema_slow,
        "closes": closes
    }


def ema(values, period):
    if len(values) < period:
        return values[-1]
    k = 2 / (period + 1)
    result = sum(values[:period]) / period
    for v in values[period:]:
        result = v * k + result * (1 - k)
    return result


def bybit_oi_change(symbol, interval="15min"):
    data = get_json(
        f"{BYBIT_API}/v5/market/open-interest",
        {
            "category": "linear",
            "symbol": symbol,
            "intervalTime": interval,
            "limit": 2
        }
    )
    try:
        items = data["result"]["list"]
        latest = float(items[0]["openInterest"])
        prev = float(items[1]["openInterest"])
        return (latest - prev) / prev * 100 if prev else 0
    except Exception:
        return 0


def bybit_funding(symbol):
    data = get_json(
        f"{BYBIT_API}/v5/market/tickers",
        {"category": "linear", "symbol": symbol}
    )
    try:
        item = data["result"]["list"][0]
        return float(item.get("fundingRate", 0)) * 100
    except Exception:
        return 0


def btc_context():
    h1 = candle_data("BTCUSDT", "1h", 80)
    h4 = candle_data("BTCUSDT", "4h", 80)

    if not h1 or not h4:
        return {"bias": "NEUTRAL", "btc_1h": 0, "btc_4h": 0}

    if h1["change"] > 0.35 and h4["change"] > 0:
        bias = "BULLISH"
    elif h1["change"] < -0.35 and h4["change"] < 0:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    return {
        "bias": bias,
        "btc_1h": h1["change"],
        "btc_4h": h4["change"]
    }


def score_symbol(symbol, btc):
    d15 = candle_data(symbol, "15m", 120)
    h1 = candle_data(symbol, "1h", 120)
    h4 = candle_data(symbol, "4h", 120)

    if not d15 or not h1 or not h4:
        return None

    price = h1["price"]
    oi15 = bybit_oi_change(symbol, "15min")
    funding = bybit_funding(symbol)

    long_score = 0
    short_score = 0
    reasons_long = []
    reasons_short = []

    # Trend / structure
    if h1["ema_fast"] > h1["ema_slow"] and h4["ema_fast"] > h4["ema_slow"]:
        long_score += 1.6
        reasons_long.append("trend up 1H/4H")
    elif h1["ema_fast"] < h1["ema_slow"] and h4["ema_fast"] < h4["ema_slow"]:
        short_score += 1.6
        reasons_short.append("trend down 1H/4H")

    # Momentum
    if d15["change"] > 0 and h1["change"] > 0:
        long_score += 1.2
        reasons_long.append("momentum long")
    elif d15["change"] < 0 and h1["change"] < 0:
        short_score += 1.2
        reasons_short.append("momentum short")

    # OI confirmation
    if oi15 > 0.4:
        if h1["change"] > 0:
            long_score += 1.7
            reasons_long.append(f"OI +{oi15:.2f}%")
        elif h1["change"] < 0:
            short_score += 1.7
            reasons_short.append(f"OI +{oi15:.2f}%")
    elif oi15 < -0.5:
        long_score -= 0.4
        short_score -= 0.4

    # Funding contrarian filter
    if funding > 0.035:
        short_score += 1.2
        long_score -= 0.7
        reasons_short.append("funding hot")
    elif funding < -0.010:
        long_score += 1.2
        short_score -= 0.7
        reasons_long.append("funding negative")
    else:
        long_score += 0.4
        short_score += 0.4

    # Relative strength vs BTC
    rs = h1["change"] - btc["btc_1h"]
    if rs > 0.45:
        long_score += 1.0
        reasons_long.append("strong vs BTC")
    elif rs < -0.45:
        short_score += 1.0
        reasons_short.append("weak vs BTC")

    # BTC context
    if btc["bias"] == "BULLISH":
        long_score += 0.8
        short_score -= 0.3
    elif btc["bias"] == "BEARISH":
        short_score += 0.8
        long_score -= 0.3

    # Volume impulse
    if h1["vol_ratio"] > 1.3:
        if h1["change"] > 0:
            long_score += 0.8
            reasons_long.append("volume impulse")
        else:
            short_score += 0.8
            reasons_short.append("volume impulse")

    # Volatility quality
    if 0.35 <= h1["atr_pct"] <= 3.5:
        long_score += 0.5
        short_score += 0.5
    elif h1["atr_pct"] > 5:
        long_score -= 0.7
        short_score -= 0.7

    direction = "LONG" if long_score >= short_score else "SHORT"
    raw = max(long_score, short_score)
    confidence = max(4.0, min(9.4, raw + 2.5))

    atr_pct = max(0.35, min(h1["atr_pct"], 4.0)) / 100

    if direction == "LONG":
        entry1 = price * (1 - atr_pct * 0.35)
        entry2 = price * (1 - atr_pct * 0.85)
        tp1 = price * 1.006
        tp2 = price * 1.014
        invalidation = price * (1 - atr_pct * 1.7)
        reasons = reasons_long[:4]
    else:
        entry1 = price * (1 + atr_pct * 0.35)
        entry2 = price * (1 + atr_pct * 0.85)
        tp1 = price * 0.994
        tp2 = price * 0.986
        invalidation = price * (1 + atr_pct * 1.7)
        reasons = reasons_short[:4]

    return {
        "symbol": symbol,
        "direction": direction,
        "confidence": confidence,
        "price": price,
        "ch15": d15["change"],
        "ch1": h1["change"],
        "ch4": h4["change"],
        "oi15": oi15,
        "funding": funding,
        "rs": rs,
        "atr": h1["atr_pct"],
        "entry1": entry1,
        "entry2": entry2,
        "tp1": tp1,
        "tp2": tp2,
        "invalidation": invalidation,
        "reasons": reasons
    }


def fmt(x):
    if x >= 100:
        return f"{x:.2f}"
    if x >= 1:
        return f"{x:.4f}"
    return f"{x:.6f}"


def build_message(rows, btc):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    msg = "🔥 <b>DAILY COIN SCANNER V2</b>\n"
    msg += f"⏰ {now}\n"
    msg += f"BTC: <b>{btc['bias']}</b> | 1H {btc['btc_1h']:.2f}% | 4H {btc['btc_4h']:.2f}%\n\n"

    if not rows:
        msg += "Нет монет выше фильтра confidence.\n"
        return msg

    for i, r in enumerate(rows, 1):
        icon = "🟢" if r["direction"] == "LONG" else "🔴"
        msg += f"{i}) {icon} <b>{r['symbol']} — {r['direction']}</b>\n"
        msg += f"Confidence: <b>{r['confidence']:.1f}/10</b>\n"
        msg += f"Price: {fmt(r['price'])}\n"
        msg += f"15m {r['ch15']:.2f}% | 1H {r['ch1']:.2f}% | 4H {r['ch4']:.2f}%\n"
        msg += f"OI15: {r['oi15']:.2f}% | Funding: {r['funding']:.4f}% | RS: {r['rs']:.2f}%\n"
        msg += f"Entry: <b>{fmt(r['entry1'])}</b> / <b>{fmt(r['entry2'])}</b>\n"
        msg += f"TP: {fmt(r['tp1'])} / {fmt(r['tp2'])}\n"
        msg += f"Invalidation: {fmt(r['invalidation'])}\n"
        msg += "Why: " + ", ".join(r["reasons"]) + "\n\n"

    msg += "⚠️ Без автоторговли. Перед входом проверяй график, стакан и BTC."
    return msg


def scan_once():
    btc = btc_context()
    results = []

    for symbol in SYMBOLS:
        print("Scanning", symbol)
        row = score_symbol(symbol, btc)
        if row and row["confidence"] >= MIN_CONFIDENCE:
            results.append(row)
        time.sleep(0.25)

    results.sort(key=lambda x: x["confidence"], reverse=True)
    top = results[:TOP_N]

    send_telegram(build_message(top, btc))


def main():
    send_telegram("✅ Daily Coin Scanner V2 started")

    while True:
        try:
            scan_once()
        except Exception as e:
            print("Main error:", e)
            send_telegram(f"⚠️ Scanner error: {e}")

        time.sleep(SCAN_INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    main()
