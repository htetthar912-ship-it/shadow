"""Shadow Support bot — keyword fallback + OpenAI (when OPENAI_API_KEY set)."""
from __future__ import annotations

import os
import json
import urllib.request
import urllib.error

GREETING = (
    "မင်္ဂလာပါ လူကြီးမင်း 👋\n"
    "Shadow Support မှ ကြိုဆိုပါတယ်။\n"
    "Order၊ ပေးချေမှု၊ ပို့ဆောင်မှု၊ ဆိုင်၊ account တို့နဲ့ပတ်သက်ပြီး မေးနိုင်ပါတယ်။\n\n"
    "Admin ဝင်လာရင် AI က ရပ်ပြီး admin ကိုယ်တိုင် ကူညီပါမယ်။"
)

ADMIN_TAKEOVER_NOTICE = (
    "👤 Admin ချိတ်ဆက်ပြီးပါပြီ။\n"
    "AI assistant ယာယီရပ်ပါမယ် — admin က ဆက်လက်ကူညီပေးပါမယ်။"
)

SECURITY_BOT_NAME = os.environ.get("SECURITY_BOT_NAME", "Shadow Security")

APP_KNOWLEDGE = """
You are Shadow Support AI for a Myanmar delivery/marketplace app called Shadow.
Service area: Myanmar only (especially Pyin Oo Lwin and nearby).
Help users in the same language they write (Burmese or English). Be concise and practical.

App facts:
- Roles: customer, seller (shop), taxi/driver, admin.
- Customers: browse shops/products, cart, checkout (COD / KBZ Pay / Wave Pay), track orders, chat with sellers, Shadow Support chat.
- Sellers: My Shop, products, orders, status updates, chat with customers.
- Drivers: accept/assign deliveries, update picked up / on the way / delivered.
- Login: phone OTP, password, Google (then phone link). Password rules: English 8+ chars with letter+number.
- Location: GPS required; app only works inside Myanmar.
- Orders statuses roughly: Order Placed → Seller Confirmed → Preparing → Ready for Pickup → Rider Assigned → Picked Up → On the Way → Delivered (or Cancelled).
- If user reports a bug, summarize clearly and suggest contacting admin if needed.
- Never invent order IDs or payment confirmations. Never ask for full card numbers or OTP codes.
- If admin has joined, you should not reply (handled by server).
"""


def is_security_call(text):
    t = (text or "").lower()
    return any(token in t for token in ("@security", "shadow security", "security bot", "လုံခြုံရေး"))


def security_report(users):
    locked = []
    for user in users or []:
        remaining = 0
        if getattr(user, "locked_until", None):
            from datetime import datetime
            remaining = max(0, int((user.locked_until - datetime.utcnow()).total_seconds()))
        if remaining:
            locked.append(f"{user.username or user.email or user.phone}: {remaining}s")
    return (
        f"🔐 {SECURITY_BOT_NAME}\n"
        f"Locked accounts: {len(locked)}\n"
        + ("\n".join(locked[:10]) if locked else "No active lockouts.")
    )


def bot_reply_keyword(user_text: str) -> str:
    t = (user_text or "").strip().lower()
    if not t:
        return "မေးခွန်းလေး ရေးပေးပါခင်ဗျ။ Order၊ ငွေပေးချေမှု၊ ပို့ဆောင်မှု သို့မဟုတ် account အကြောင်း ကူညီပေးနိုင်ပါတယ်။"
    if any(k in t for k in ("order", "tracking", "track", "အော်ဒါ", "မှာထား", "ခြေရာခံ")):
        return ("📦 Order — Account → **Orders** မှာ status ကြည့်ပါ။\n"
                "Order code သို့မဟုတ် ပြဿနာအဆင့်ကို ပို့ပေးရင် ဆက်ကူညီပါမယ်။")
    if any(k in t for k in ("pay", "payment", "kbz", "wave", "ပေးချေ", "ငွေ", "cod")):
        return ("💳 Checkout မှာ COD၊ KBZ Pay၊ Wave Pay ရွေးနိုင်ပါတယ်။\n"
                "KBZ/Wave မှာ screenshot တင်ရန် လိုနိုင်ပါတယ်။")
    if any(k in t for k in ("delivery", "ပို့", "လိပ်စာ", "address", "vpn", "location", "တည်နေရာ")):
        return ("📍 ပို့ဆောင်လိပ်စာကို map pin နဲ့ တိတိကျကျ ထားပါ။\n"
                "Shadow သည် မြန်မာနိုင်ငံအတွင်းသာ သုံးနိုင်ပါတယ်။ VPN/fake GPS ပိတ်ပါ။")
    if any(k in t for k in ("chat", "seller", "shop", "ဆိုင်", "ရောင်းသူ")):
        return "💬 ဆိုင်/ပစ္စည်းစာမျက်နှာက **Chat** နှိပ်ပြီး ဆိုင်နဲ့ တိုက်ရိုက်ပြောနိုင်ပါတယ်။"
    if any(k in t for k in ("hello", "hi", "မင်္ဂလာပါ", "help", "ကူညီ")):
        return GREETING
    return ("နားလည်ပါတယ်။ Order code၊ screenshot၊ သို့မဟုတ် ပြဿနာအသေးစိတ် ပို့ပေးပါ။\n"
            "Admin online ဖြစ်ရင် လူကိုယ်တိုင် ဆက်ကူညီပါမယ်။")


def openai_enabled() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


def ai_reply(user_text: str, history: list[dict] | None = None) -> str:
    """Answer with OpenAI if key present; else keyword FAQ."""
    text = (user_text or "").strip()
    if not text:
        return bot_reply_keyword(text)

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return bot_reply_keyword(text)

    messages = [{"role": "system", "content": APP_KNOWLEDGE}]
    if history:
        for h in history[-8:]:
            role = "assistant" if h.get("role") in ("admin", "bot", "assistant") else "user"
            content = (h.get("body") or "")[:500]
            if content:
                messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": text[:1500]})

    model = os.environ.get("OPENAI_SUPPORT_MODEL", "gpt-4o-mini")
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": 400,
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        return content or bot_reply_keyword(text)
    except Exception as e:
        print("[SupportAI] fallback:", e)
        return bot_reply_keyword(text)


def bot_reply(user_text: str, history: list[dict] | None = None) -> str:
    return ai_reply(user_text, history=history)
