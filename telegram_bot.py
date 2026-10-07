"""
Telegram Bot alerts for riders/couriers.

Free - Telegram's Bot API has no cost and needs no billing account, just
a bot token from @BotFather. This sends a message to one fixed chat
(your own Telegram, or a group with your riders in it) whenever a
seller marks an order "Ready for Pickup" - including the customer's
address, phone number, order items, and a one-tap Google Maps
navigation link.

Setup (free, ~2 minutes):
1. In Telegram, message @BotFather -> /newbot -> follow the prompts.
   You'll get a token like "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11".
2. Message your new bot anything (e.g. "hi") so it can see your chat.
3. Get your chat_id: visit
   https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
   in a browser right after step 2, and read the "chat":{"id": ...}
   value from the JSON response.
4. Put both values in .env:
     TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
     TELEGRAM_CHAT_ID=123456789
5. Restart the app. No code changes needed.

Until those are set, this just prints the message to the console
instead of sending it - so the rest of the app keeps working.
"""

import os
import requests

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
TELEGRAM_UPDATES_API = "https://api.telegram.org/bot{token}/getUpdates"
_discovered_chat_id = None


def _token():
    value = (os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_URL") or "").strip()
    if "/bot" in value:
        value = value.split("/bot", 1)[1].split("/", 1)[0]
    return value


def telegram_enabled() -> bool:
    return bool(_token())


def _chat_id():
    """Use TELEGRAM_CHAT_ID when supplied; otherwise use the latest chat that
    messaged the bot. The owner only needs to paste the BotFather token."""
    global _discovered_chat_id
    explicit = os.environ.get("TELEGRAM_CHAT_ID")
    if explicit:
        return explicit
    if _discovered_chat_id:
        return _discovered_chat_id
    try:
        response = requests.get(
            TELEGRAM_UPDATES_API.format(token=_token()),
            params={"limit": 20, "allowed_updates": ["message"]}, timeout=5,
        )
        updates = response.json().get("result", [])
        for update in reversed(updates):
            message = update.get("message") or update.get("channel_post")
            if message and message.get("chat", {}).get("id") is not None:
                _discovered_chat_id = str(message["chat"]["id"])
                return _discovered_chat_id
    except Exception as exc:
        print(f"[SHADOW Telegram] Could not discover chat id: {exc}")
    return None


def current_chat_id():
    """Return the configured owner chat or discover the latest bot conversation."""
    return _chat_id()


def google_maps_link(lat, lng) -> str | None:
    """A plain navigation deep-link - no API key needed. Opens the Google
    Maps app on a phone, or maps.google.com in a browser, with
    turn-by-turn directions to (lat, lng)."""
    if lat is None or lng is None:
        return None
    return f"https://www.google.com/maps/dir/?api=1&destination={lat},{lng}&travelmode=driving"


def send_pickup_alert(order, shop):
    """order: models.Order, shop: models.Shop"""
    items_text = "\n".join(f"  - {i.qty}x {i.product_name}" for i in order.items)
    maps_link = google_maps_link(order.delivery_lat, order.delivery_lng)

    message = (
        f"🛵 <b>Ready for Pickup - Order #{order.code}</b>\n\n"
        f"<b>Shop:</b> {shop.name}\n"
        f"<b>Customer:</b> {order.customer.full_name}\n"
        f"<b>Phone:</b> {order.contact_phone or 'not provided'}\n"
        f"<b>Address:</b> {order.address}\n\n"
        f"<b>Items:</b>\n{items_text}\n\n"
        f"<b>Total:</b> {order.total:,} Ks ({order.payment_method.upper()})\n"
    )
    if maps_link:
        message += f"\n📍 <a href=\"{maps_link}\">Open navigation in Google Maps</a>"

    _send(message)


def send_text(text: str, chat_id=None):
    """Send a Telegram message and return (success, error)."""
    if not chat_id and telegram_enabled():
        chat_id = _chat_id()
    if not chat_id:
        return False, "No Telegram chat was discovered; message the bot once or set TELEGRAM_CHAT_ID."
    try:
        url = TELEGRAM_API.format(token=_token())
        response = requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=5)
        if response.ok and response.json().get("ok"):
            return True, None
        return False, f"Telegram API error: HTTP {response.status_code}"
    except Exception as e:
        return False, str(e)[:300]


def _send(text: str):
    ok, error = send_text(text)
    if not ok:
        print(f"[SHADOW Telegram] {error}")
