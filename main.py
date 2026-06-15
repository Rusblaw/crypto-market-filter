import os
import re
import time
import requests
from bs4 import BeautifulSoup

BOT_TOKEN = os.getenv("BOT_TOKEN")
SOURCE_URL = "https://t.me/s/market_shock"

MIN_MOVE = 5.0
MIN_VOL_M = 30.0
MAX_TIME_SEC = 120

sent_ids = set()
last_events = {}


def bot_api(method, params=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    return requests.post(url, data=params or {}, timeout=20).json()


def get_chat_id():
    updates = bot_api("getUpdates")
    for upd in reversed(updates.get("result", [])):
        msg = upd.get("message", {})
        if msg.get("text") == "/start":
            return msg["chat"]["id"]
    return None


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


def parse_signal(text):
    pair_match = re.search(r"USDT-([A-Z0-9]+)", text)
    move_match = re.search(r"USDT-[A-Z0-9]+\s*([+-]\d+(?:\.\d+)?)%", text)

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
        "raw": text,
    }


def is_strong_signal(s):
    if s["type"] not in ["SHOCK", "SLOW"]:
        return False

    if s["abs_move"] < MIN_MOVE:
        return False

    if s["vol_m"] < MIN_VOL_M:
        return False

    if s["seconds"] > MAX_TIME_SEC:
        return False

    return True


def build_message(s):
    pair = s["pair"]
    now = time.time()

    history = last_events.get(pair, [])
    history = [x for x in history if now - x["ts"] <= 120]
    history.append({"ts": now, "move": s["move"]})
    last_events[pair] = history

    cascade = len(history) >= 3

    icon = "🚀" if s["direction"] == "PUMP" else "🔻"
    priority = "🔥 EXTREME EVENT" if cascade else "⚡ STRONG MARKET SHOCK"

    moves = "\n".join([f"{x['move']}%" for x in history[-5:]])

    return f"""
{priority}

{icon} {pair}USDT
Direction: {s['direction']}
Type: {s['type']}
Move: {s['move']}%
Time: {s['seconds']}s
24H Vol: {s['vol_m']:.1f}M

Recent signals:
{moves}

Action:
Не вход сразу. Проверить график:
Base → Impulse → Retention → Liquidity → Reaction.
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


def main():
    print("Crypto Market Shock Filter started")

    chat_id = get_chat_id()

    if not chat_id:
        print("Send /start to your bot first.")
        while not chat_id:
            time.sleep(10)
            chat_id = get_chat_id()

    bot_api("sendMessage", {
        "chat_id": chat_id,
        "text": "✅ Market Shock Filter started"
    })

    while True:
        try:
            messages = fetch_messages()

            for msg_id, text in messages[-20:]:
                if msg_id in sent_ids:
                    continue

                sent_ids.add(msg_id)

                signal = parse_signal(text)

                if not signal:
                    continue

                if is_strong_signal(signal):
                    bot_api("sendMessage", {
                        "chat_id": chat_id,
                        "text": build_message(signal)
                    })

            time.sleep(25)

        except Exception as e:
            print("ERROR:", e)
            time.sleep(30)


if __name__ == "__main__":
    main()
