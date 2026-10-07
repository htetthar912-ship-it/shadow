"""
Phone OTP (one-time-code) for register + login.

Default: SMS_BACKEND=console (prints code in server logs).
Production: set SMS_BACKEND=twilio or custom_http with API credentials.
"""

import os
import random
import re
from datetime import datetime, timedelta
import timeutil

from werkzeug.security import generate_password_hash, check_password_hash

from extensions import db
from models import OTPCode

OTP_TTL_SECONDS = 2 * 60
MAX_ATTEMPTS = 5


def normalize_phone(phone: str) -> str:
    """Normalize Myanmar local numbers to E.164 when possible.
    09xxxxxxx -> +959xxxxxxx
    959xxxxxxx -> +959xxxxxxx
    Already +95... left as-is.
    """
    if not phone:
        return phone
    raw = re.sub(r"[\s\-\(\)]", "", phone.strip())
    if raw.startswith("+"):
        return raw
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("95") and len(digits) >= 10:
        return "+" + digits
    if digits.startswith("0") and len(digits) >= 9:
        # 09... -> +959...
        return "+95" + digits[1:]
    if digits.startswith("9") and len(digits) >= 8:
        return "+95" + digits
    return raw if raw.startswith("+") else ("+" + digits if digits else raw)


def generate_and_send_otp(phone: str, purpose: str = "login") -> dict:
    """Create OTP and try to send SMS. Returns {ok, phone, error?}."""
    phone = normalize_phone(phone)
    code = f"{random.randint(0, 999999):06d}"
    expires_at = datetime.utcnow() + timedelta(seconds=OTP_TTL_SECONDS)

    entry = OTPCode(
        phone=phone,
        code_hash=generate_password_hash(code),
        purpose=purpose,
        expires_at=expires_at,
    )
    db.session.add(entry)
    db.session.commit()

    ok, err = send_otp_sms(phone, code)
    return {"ok": ok, "phone": phone, "error": err}


def verify_otp(phone: str, code: str, purpose: str = "login") -> bool:
    phone = normalize_phone(phone)
    entry = (
        OTPCode.query.filter_by(phone=phone, purpose=purpose, consumed=False)
        .order_by(OTPCode.created_at.desc())
        .first()
    )
    if not entry:
        return False
    if entry.expires_at < datetime.utcnow():
        return False
    if entry.attempts >= MAX_ATTEMPTS:
        return False

    entry.attempts += 1
    ok = check_password_hash(entry.code_hash, code)
    if ok:
        entry.consumed = True
    db.session.commit()
    return ok


def send_otp_sms(phone: str, code: str):
    """Returns (success: bool, error: str|None)."""
    backend = (os.environ.get("SMS_BACKEND") or "console").strip().lower()
    message = (
        f"Your Shadow verification code is {code}. "
        f"It expires in 2 minutes. "
        f"({timeutil.now_mm_str()} MM time)"
    )
    phone = normalize_phone(phone)
    is_prod = (os.environ.get("FLASK_ENV") or "").lower() == "production" or os.environ.get("FORCE_PRODUCTION", "").lower() in ("1", "true", "yes")

    # Production must not silently print OTP to logs as the only delivery path
    if is_prod and backend in ("console", "log", ""):
        msg = "SMS_BACKEND is console/log — real SMS required in production (set SMS_BACKEND=twilio and Twilio keys)."
        print(f"[SHADOW OTP] {msg}")
        return False, msg

    if backend == "twilio":
        sid = os.environ.get("TWILIO_ACCOUNT_SID")
        token = os.environ.get("TWILIO_AUTH_TOKEN")
        from_num = os.environ.get("TWILIO_FROM_NUMBER")
        if not (sid and token and from_num):
            msg = "Twilio env vars missing (TWILIO_ACCOUNT_SID / AUTH_TOKEN / FROM_NUMBER)"
            print(f"[SHADOW OTP] {msg}")
            print(f"[SHADOW OTP] (fallback log) code for {phone}: {code}")
            return False, msg
        try:
            from twilio.rest import Client
        except ImportError:
            msg = "twilio package not installed"
            print(f"[SHADOW OTP] {msg}. pip install twilio")
            print(f"[SHADOW OTP] (fallback log) code for {phone}: {code}")
            return False, msg
        try:
            client = Client(sid, token)
            client.messages.create(body=message, from_=from_num, to=phone)
            print(f"[SHADOW OTP] Twilio SMS sent to {phone}")
            return True, None
        except Exception as exc:
            print(f"[SHADOW OTP] Twilio failed: {exc}")
            print(f"[SHADOW OTP] (fallback log) code for {phone}: {code}")
            return False, str(exc)

    if backend == "custom_http":
        import requests

        url = os.environ.get("SMS_API_URL")
        if not url:
            msg = "SMS_API_URL not set"
            print(f"[SHADOW OTP] {msg}")
            print(f"[SHADOW OTP] (fallback log) code for {phone}: {code}")
            return False, msg

        method = os.environ.get("SMS_API_METHOD", "POST").upper()
        phone_param = os.environ.get("SMS_API_PHONE_PARAM", "to")
        message_param = os.environ.get("SMS_API_MESSAGE_PARAM", "message")
        key_param = os.environ.get("SMS_API_KEY_PARAM", "api_key")
        api_key = os.environ.get("SMS_API_KEY")

        # Some Myanmar gateways want local format 09... not +95
        send_phone = phone
        if os.environ.get("SMS_API_LOCAL_FORMAT") == "1" and phone.startswith("+95"):
            send_phone = "0" + phone[3:]

        params = {phone_param: send_phone, message_param: message}
        if api_key:
            params[key_param] = api_key
        extra = os.environ.get("SMS_API_EXTRA_PARAMS", "")
        for pair in extra.split("&"):
            if "=" in pair:
                k, v = pair.split("=", 1)
                params[k] = v

        try:
            if method == "GET":
                resp = requests.get(url, params=params, timeout=15)
            else:
                resp = requests.post(url, data=params, timeout=15)
            resp.raise_for_status()
            print(f"[SHADOW OTP] custom_http SMS sent to {send_phone}")
            return True, None
        except Exception as exc:
            print(f"[SHADOW OTP] custom_http failed: {exc}")
            print(f"[SHADOW OTP] (fallback log) code for {phone}: {code}")
            return False, str(exc)

    # console backend — development only
    print(f"[SHADOW OTP] Verification code for {phone}: {code}  (expires in {OTP_TTL_SECONDS // 60} min)")
    print("[SHADOW OTP] Tip: set SMS_BACKEND=twilio on Railway to send real SMS.")
    return True, None
