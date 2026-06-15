from telethon.sync import TelegramClient
from telethon.sessions import StringSession
import os

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
PHONE = os.getenv("PHONE_NUMBER")

client = TelegramClient(StringSession(), API_ID, API_HASH)

client.start(phone=PHONE)

print("========== DIALOGS ==========")

for dialog in client.iter_dialogs():
    print(dialog.name)
    print(dialog.id)
    print("---------------------")

client.disconnect()
