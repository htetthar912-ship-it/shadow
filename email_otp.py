"""Gmail SMTP verification codes. Plain codes are never stored."""
import os, random, smtplib, ssl
from email.message import EmailMessage
from datetime import datetime, timedelta
import timeutil
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db
from models import OTPCode

TTL_SECONDS = 300
MAX_ATTEMPTS = 5
LAST_SEND_ERROR = None

def enabled():
    return bool(os.environ.get("SMTP_EMAIL") and os.environ.get("SMTP_APP_PASSWORD"))

def normalize_email(value):
    return (value or "").strip().lower()

def send_code(email, purpose):
    global LAST_SEND_ERROR
    LAST_SEND_ERROR = None
    email = normalize_email(email)
    code = f"{random.randint(0, 999999):06d}"
    row = OTPCode(phone=f"email:{email}", code_hash=generate_password_hash(code), purpose=purpose, expires_at=datetime.utcnow()+timedelta(seconds=TTL_SECONDS))
    db.session.add(row); db.session.commit()
    if not enabled():
        print(f"[SHADOW EMAIL OTP] SMTP not configured; code for {email}: {code}")
        return True
    msg = EmailMessage()
    msg["Subject"] = "Your Shadow verify code"
    msg["From"] = os.environ["SMTP_EMAIL"].strip()
    msg["To"] = email
    msg.set_content(
        f"Your Shadow verify code is {code}.\n"
        f"It expires in 5 minutes.\n"
        f"Sent at: {timeutil.now_mm_str()} (Myanmar time)\n"
        f"If you did not request this, ignore this email."
    )
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com").strip()
    configured_port = int(os.environ.get("SMTP_PORT", "465"))
    ports = [configured_port] + ([587] if configured_port != 587 else [465])
    errors = []
    for port in ports:
        try:
            # Google displays App Passwords in four-character groups; Gmail
            # SMTP expects the same secret without visual spaces.
            app_password = os.environ["SMTP_APP_PASSWORD"].replace(" ", "").strip()
            if port == 587:
                with smtplib.SMTP(host, port, timeout=20) as server:
                    server.starttls(context=ssl.create_default_context())
                    server.login(os.environ["SMTP_EMAIL"].strip(), app_password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=20) as server:
                    server.login(os.environ["SMTP_EMAIL"].strip(), app_password)
                    server.send_message(msg)
            return True
        except Exception as exc:
            errors.append(f"port {port}: {type(exc).__name__}: {exc}")
    LAST_SEND_ERROR = " | ".join(errors)[:500]
    print(f"[SHADOW EMAIL OTP] send failed: {LAST_SEND_ERROR}")
    return False


def last_send_error():
    return LAST_SEND_ERROR

def verify_code(email, code, purpose):
    key = f"email:{normalize_email(email)}"
    row = OTPCode.query.filter_by(phone=key, purpose=purpose, consumed=False).order_by(OTPCode.created_at.desc()).first()
    if not row or row.expires_at < datetime.utcnow() or row.attempts >= MAX_ATTEMPTS:
        return False
    row.attempts += 1
    ok = check_password_hash(row.code_hash, str(code or "").strip())
    if ok: row.consumed = True
    db.session.commit()
    return ok
