import os
import time
import json
import urllib.request
import urllib.parse

from telethon.sync import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
PHONE = os.getenv("PHONE_NUMBER")
BOT_TOKEN = os.getenv("BOT_TOKEN")
TG_PASSWORD = os.getenv("TG_PASSWORD", "")

client = TelegramClient(StringSession(), API_ID, API_HASH)


def bot_api(method, params=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    data = urllib.parse.urlencode(params or {}).encode()
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def wait_for_code():
    print("WAITING_FOR_CODE")
    print("Open your Telegram bot and send: /code 12345")

    offset = 0

    while True:
        res = bot_api("getUpdates", {"offset": offset, "timeout": 25})

        for upd in res.get("result", []):
            offset = upd["update_id"] + 1
            msg = upd.get("message", {})
            text = msg.get("text", "").strip()

            if text.startswith("/code"):
                parts = text.split()
                if len(parts) >= 2:
                    code = parts[1].strip()
                    chat_id = msg["chat"]["id"]

                    bot_api("sendMessage", {
                        "chat_id": chat_id,
                        "text": "Code received. Trying login..."
                    })

                    return code, chat_id

        time.sleep(1)


client.connect()

if client.is_user_authorized():
    print("ALREADY_AUTHORIZED")
    print("SESSION_STRING:")
    print(client.session.save())
else:
    sent = client.send_code_request(PHONE)

    print("CODE_SENT")
    print("Do NOT redeploy now.")
    print("Send /code XXXXX to your Telegram bot.")

    code, chat_id = wait_for_code()

    try:
        client.sign_in(
            phone=PHONE,
            code=code,
            phone_code_hash=sent.phone_code_hash
        )
    except SessionPasswordNeededError:
        client.sign_in(password=TG_PASSWORD)

    session = client.session.save()

    print("SESSION_STRING:")
    print(session)

    bot_api("sendMessage", {
        "chat_id": chat_id,
        "text": "✅ SESSION_STRING created. Copy it from Railway logs. Do not share it."
    })

    while True:
        time.sleep(60)
