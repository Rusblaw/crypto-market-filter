import os
import re
import time
import requests
from bs4 import BeautifulSoup

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = -1003553154123

SOURCE_URL = "https://t.me/s/market_shock"

MIN_MOVE = 5.0
MIN_VOL_M = 30.0
MAX_TIME_SEC = 120

CHECK_PAUSE_SEC = 600
CASCADE_WINDOW_SEC = 300
COOLDOWN_AFTER_CHECK = 3600

sent_ids = set()
events = {}
last_check_sent = {}


def bot_api(method, params=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    return requests.post(url, data=params or {}, timeout=20).json()


def format_price(price):
    if price is None:
        return "n/a"
    if price >= 100:
        return f"{price:.2f}"
    if price >= 1:
        return f"{price:.4f}"
    return f"{price:.6f}"


def format_pct(value):
    if value is None:
        return "n/a"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def get_current_price_value(pair):
    symbol = f"{pair}USDT"

    try:
        url = "https://fapi.binance.com/fapi/v1/ticker/price"
        r = requests.get(url, params={"symbol": symbol}, timeout=10)
        data = r.json()

        if "price" in data:
            return float(data["price"])

    except Exception as e:
        print(f"Price error for {symbol}: {e}")

    return None


def get_market_context(pair):
    symbol = f"{pair}USDT"

    context = {
        "change_1h": None,
        "change_6h": None,
        "change_24h": None,
        "from_high": None,
        "from_low": None,
    }

    try:
        ticker_url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
        ticker = requests.get(ticker_url, params={"symbol": symbol}, timeout=10).json()

        current = float(ticker["lastPrice"])
        high_24h = float(ticker["highPrice"])
        low_24h = float(ticker["lowPrice"])

        context["change_24h"] = float(ticker["priceChangePercent"])

        if high_24h > 0:
            context["from_high"] = ((current - high_24h) / high_24h) * 100

        if low_24h > 0:
            context["from_low"] = ((current - low_24h) / low_24h) * 100

    except Exception as e:
        print(f"24h context error for {symbol}: {e}")

    try:
        klines_url = "https://fapi.binance.com/fapi/v1/klines"
        klines = requests.get(
            klines_url,
            params={"symbol": symbol, "interval": "1h", "limit": 7},
            timeout=10
        ).json()

        current_price = float(klines[-1][4])
        open_1h = float(klines[-1][1])
        open_6h = float(klines[-6][1])

        if open_1h > 0:
            context["change_1h"] = ((current_price - open_1h) / open_1h) * 100

        if open_6h > 0:
            context["change_6h"] = ((current_price - open_6h) / open_6h) * 100

    except Exception as e:
        print(f"Klines context error for {symbol}: {e}")

    return context


def build_market_context_text(pair):
    ctx = get_market_context(pair)

    return f"""📊 Market Context
🕐 1H    {format_pct(ctx["change_1h"])}
🕕 6H    {format_pct(ctx["change_6h"])}
🕛 24H   {format_pct(ctx["change_24h"])}

📉 From 24H High: {format_pct(ctx["from_high"])}
📈 From 24H Low : {format_pct(ctx["from_low"])}
"""


def build_watch_level_text(s, current_price):
    if current_price is None:
        return "🎯 Watch Level\nn/a"

    move = s["move"]

    if move == 0:
        return "🎯 Watch Level\nn/a"

    origin = current_price / (1 + move / 100)

    if s["direction"] == "PUMP":
        impulse_size = current_price - origin
        retest_low = origin
        retest_high = origin + impulse_size * 0.35

        return f"""🎯 Watch Level
Origin: {format_price(origin)}
Retest zone: {format_price(retest_low)} - {format_price(retest_high)}

Логика:
Ждать возврат к базе / удержание импульса.
Не шортить силу без слабости.
"""

    impulse_size = origin - current_price
    recovery_low = current_price + impulse_size * 0.40
    recovery_high = current_price + impulse_size * 0.60

    return f"""🎯 Watch Level
Origin: {format_price(origin)}
Recovery zone: {format_price(recovery_low)} - {format_price(recovery_high)}

Логика:
Не ловить нож.
Ждать выкуп / базу / rejection.
"""


def parse_time_seconds(text):
    m = re.search(r"/\s*(\d+)m([\d.]+)s", text)
    if m:
        return int(m.group(1)) * 60 + float(m.group(2))

    m = re.search(r"/\s*([\d.]+)s", text)
    if m:
        return float(m.group(1))

    return None


def parse_volume_m(text):
    m = re.search(r"24H Vol:\s*([\d.]+)\s*([MB])", text)
    if not m:
        return None

    value = float(m.group(1))
    unit = m.group(2)

    if unit == "B":
        return value * 1000

    return value


def format_volume(vol_m):
    if vol_m >= 1000:
        return f"{vol_m / 1000:.2f}B"
    return f"{vol_m:.1f}M"


def parse_signal(text):
    pair_match = re.search(r"USDT-([A-Z0-9]+)", text)
    move_match = re.search(r"USDT-[A-Z0-9]+\s*([+-]?\d+(?:\.\d+)?)%", text)

    if not pair_match or not move_match:
        return None

    pair = pair_match.group(1)
    move = float(move_match.group(1))
    seconds = parse_time_seconds(text)
    vol_m = parse_volume_m(text)

    if seconds is None or vol_m is None:
        return None

    signal_type = "SHOCK" if "SHOCK" in text else "SLOW" if "SLOW" in text else "UNKNOWN"
    direction = "PUMP" if move > 0 else "DUMP"

    return {
        "pair": pair,
        "move": move,
        "abs_move": abs(move),
        "seconds": seconds,
        "vol_m": vol_m,
        "type": signal_type,
        "direction": direction,
        "ts": time.time(),
    }


def is_strong_signal(s):
    return (
        s["type"] in ["SHOCK", "SLOW"]
        and s["abs_move"] >= MIN_MOVE
        and s["vol_m"] >= MIN_VOL_M
        and s["seconds"] <= MAX_TIME_SEC
    )


def confidence_score(s, history_count):
    score = 5.5

    if s["type"] == "SHOCK":
        score += 1.0
    if s["abs_move"] >= 7:
        score += 0.8
    if s["abs_move"] >= 10:
        score += 0.7
    if s["seconds"] <= 30:
        score += 0.7
    if s["vol_m"] >= 100:
        score += 0.5
    if s["vol_m"] >= 1000:
        score += 0.4
    if history_count >= 2:
        score += 0.5

    return min(round(score, 1), 9.5)


def build_alert(s):
    pair = s["pair"]
    now = time.time()

    history = events.get(pair, [])
    history = [x for x in history if now - x["ts"] <= CASCADE_WINDOW_SEC]
    history.append(s)
    events[pair] = history

    cascade = len(history) >= 2

    icon = "🟢" if s["direction"] == "PUMP" else "🔴"
    move_icon = "📈" if s["direction"] == "PUMP" else "📉"
    confidence = confidence_score(s, len(history))

    current_price = get_current_price_value(pair)
    price = format_price(current_price)

    market_context = build_market_context_text(pair)
    watch_level = build_watch_level_text(s, current_price)

    previous = ""
    if len(history) > 1:
        lines = []
        for i, x in enumerate(history[:-1][-5:], start=1):
            lines.append(f"{i}) {x['move']}% / {x['seconds']}s / {x['type']}")
        previous = "\n\n📌 Previous signals:\n" + "\n".join(lines)

    cascade_text = ""
    if cascade:
        cascade_text = "\n\n⚠️ Cascade detected\nИмпульс продолжается. Не ловить нож / не шортить силу без подтверждения."

    return f"""🚨 CRYPTO SCANNER V1

{icon} {pair}USDT
{s['type']} {s['direction']}

💲 Price      {price}
{move_icon} Move       {s['move']}%
⚡ Time        {s['seconds']} sec
💰 Volume      {format_volume(s['vol_m'])}

{market_context}

{watch_level}

🟢 Confidence:
{confidence}/10{previous}{cascade_text}

━━━━━━━━━━━━━━

✅ Проверить:
• База
• Импульс
• Удержание
• Ликвидность
• BTC

📌 Только после подтверждения искать вход.
"""


def build_pause_alert(pair, history):
    last = history[-1]
    icon = "🟢" if last["direction"] == "PUMP" else "🔴"

    current_price = get_current_price_value(pair)
    price = format_price(current_price)

    market_context = build_market_context_text(pair)
    watch_level = build_watch_level_text(last, current_price)

    moves = "\n".join(
        [f"{x['move']}% / {x['seconds']}s / {x['type']}" for x in history[-5:]]
    )

    return f"""🧊 IMPULSE PAUSE

{icon} {pair}USDT
💲 Price: {price}

После сильного {last['direction']} новых сигналов нет 10 минут.

Последние сигналы:
{moves}

{market_context}

{watch_level}

━━━━━━━━━━━━━━

📌 Проверить график:
• появился ли возврат к базе
• есть ли удержание импульса
• есть ли быстрый выкуп / rejection
• где ближайшая ликвидность
• что делает BTC

Возможна зона для поиска сетапа.
"""


def fetch_messages():
    r = requests.get(SOURCE_URL, timeout=20)
    soup = BeautifulSoup(r.text, "html.parser")

    messages = []

    for msg in soup.select(".tgme_widget_message"):
        msg_id = msg.get("data-post")
        text_el = msg.select_one(".tgme_widget_message_text")

        if not msg_id or not text_el:
            continue

        text = text_el.get_text("\n", strip=True)
        messages.append((msg_id, text))

    return messages


def check_pauses():
    now = time.time()

    for pair, history in list(events.items()):
        if not history:
            continue

        recent_history = [x for x in history if now - x["ts"] <= CASCADE_WINDOW_SEC]

        if not recent_history:
            continue

        last = recent_history[-1]

        if now - last["ts"] < CHECK_PAUSE_SEC:
            continue

        if len(recent_history) < 2 and abs(last["move"]) < 7:
            continue

        if now - last_check_sent.get(pair, 0) < COOLDOWN_AFTER_CHECK:
            continue

        bot_api("sendMessage", {
            "chat_id": CHANNEL_ID,
            "text": build_pause_alert(pair, recent_history)
        })

        last_check_sent[pair] = now


def main():
    print("Crypto Market Shock Filter started")

    bot_api("sendMessage", {
        "chat_id": CHANNEL_ID,
        "text": "✅ Market Shock Filter started"
    })

    while True:
        try:
            messages = fetch_messages()

            for msg_id, text in messages[-30:]:
                if msg_id in sent_ids:
                    continue

                sent_ids.add(msg_id)

                signal = parse_signal(text)

                if not signal:
                    continue

                if is_strong_signal(signal):
                    bot_api("sendMessage", {
                        "chat_id": CHANNEL_ID,
                        "text": build_alert(signal)
                    })

            check_pauses()
            time.sleep(25)

        except Exception as e:
            print("ERROR:", e)
            time.sleep(30)


if __name__ == "__main__":
    main()
