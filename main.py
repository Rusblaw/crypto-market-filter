def get_chat_id():
    updates = bot_api("getUpdates")

    for upd in reversed(updates.get("result", [])):

        # если написали /channel в канале
        channel_post = upd.get("channel_post", {})
        if channel_post.get("text") == "/channel":
            return channel_post["chat"]["id"]

        # если написали /start в личку боту
        msg = upd.get("message", {})
        if msg.get("text") == "/start":
            return msg["chat"]["id"]

    return None
