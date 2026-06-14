import os
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
PHONE = os.getenv("PHONE_NUMBER")
LOGIN_CODE = os.getenv("LOGIN_CODE", "")

client = TelegramClient(StringSession(), API_ID, API_HASH)

client.connect()

if not client.is_user_authorized():
    if LOGIN_CODE == "":
        client.send_code_request(PHONE)
        print("CODE_SENT")
    else:
        client.sign_in(PHONE, LOGIN_CODE)
        print("SESSION_STRING:")
        print(client.session.save())
else:
    print("ALREADY_AUTHORIZED")
