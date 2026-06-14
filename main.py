import os
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
PHONE = os.getenv("PHONE_NUMBER")
LOGIN_CODE = os.getenv("LOGIN_CODE", "")
PHONE_CODE_HASH = os.getenv("PHONE_CODE_HASH", "")

client = TelegramClient(StringSession(), API_ID, API_HASH)
client.connect()

if not client.is_user_authorized():
    if LOGIN_CODE == "":
        sent = client.send_code_request(PHONE)
        print("CODE_SENT")
        print("PHONE_CODE_HASH:")
        print(sent.phone_code_hash)
    else:
        client.sign_in(phone=PHONE, code=LOGIN_CODE, phone_code_hash=PHONE_CODE_HASH)
        print("SESSION_STRING:")
        print(client.session.save())
else:
    print("ALREADY_AUTHORIZED")
