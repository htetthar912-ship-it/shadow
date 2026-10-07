"""Shadow Manager application-security policy engine."""
import re
from datetime import datetime, timedelta

URL_RE = re.compile(r"(?:https?://|www\.|t\.me/|bit\.ly/|tinyurl\.com/|[\w.-]+\.(?:com|net|org|me|io|ly)(?:/|$))", re.I)
SENSITIVE_RE = re.compile(r"(?:password|otp|code|token|secret|national id|မှတ်ပုံတင်|စကားဝှက်|ကုဒ်)", re.I)


def contains_link(text):
    return bool(URL_RE.search(text or ""))


def contains_sensitive_request(text):
    return bool(SENSITIVE_RE.search(text or ""))


def ban_duration(violations, support=False):
    # Support links start at one day; ordinary chat starts at one hour.
    if violations <= 1:
        return timedelta(days=1 if support else 0, hours=0 if support else 1)
    if violations == 2: return timedelta(days=1)
    if violations == 3: return timedelta(days=7)
    if violations == 4: return timedelta(days=30)
    return None  # permanent


def apply_link_enforcement(user, support=False):
    user.security_violations = (user.security_violations or 0) + 1
    duration = ban_duration(user.security_violations, support=support)
    user.is_banned = True
    user.banned_until = None if duration is None else datetime.utcnow() + duration
    return duration


def ban_message(duration):
    if duration is None:
        return "Shadow Manager blocked this account permanently after repeated link-policy violations. Contact an admin."
    seconds = int(duration.total_seconds())
    if seconds >= 2592000: label = "30 days"
    elif seconds >= 604800: label = "7 days"
    elif seconds >= 86400: label = "1 day"
    else: label = "1 hour"
    return f"Shadow Manager blocked this account for {label} because links are not allowed in this chat."


def seller_order_payload(order):
    """Only the fields needed to fulfil a specific order; never serialize User."""
    return {
        "order_id": order.id, "order_code": order.code,
        "customer_name": order.customer.full_name if order.customer else None,
        "delivery_address": order.address,
        "contact_phone": order.contact_phone,
        "items": [{"name": item.product_name, "qty": item.qty} for item in order.items],
    }
