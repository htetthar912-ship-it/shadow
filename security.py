"""Central authentication security policy for Shadow."""
import re
from datetime import datetime, timedelta
from werkzeug.security import check_password_hash

USERNAME_RE = re.compile(r"^[A-Za-z0-9\u1000-\u109F]{2,40}$")
PASSWORD_RE = re.compile(r"^[\x21-\x7E]+$")
EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$")
LOCKOUT_SECONDS = 120
MAX_FAILURES = 3


def normalize_email(value):
    value = (value or "").strip().lower()
    return value or None


def normalize_username(value):
    return (value or "").strip().lower()


def validate_username(value):
    value = (value or "").strip()
    if not USERNAME_RE.fullmatch(value):
        return False, "Username must be 2–40 characters using Myanmar/English letters and numbers only."
    return True, ""


def validate_email(value, required=False):
    value = normalize_email(value)
    if not value and not required:
        return True, "", value
    if not value or len(value) > 120 or not EMAIL_RE.fullmatch(value):
        return False, "Please enter a valid email address.", value
    return True, "", value


def validate_password(value):
    value = value or ""
    if len(value) < 8:
        return False, "Password must be at least 8 characters."
    if not PASSWORD_RE.fullmatch(value):
        return False, "Password may use English letters, numbers, and symbols only; no spaces or Myanmar characters."
    if not re.search(r"[A-Za-z]", value) or not re.search(r"[0-9]", value):
        return False, "Password must contain at least one English letter and one number."
    return True, ""


def lockout_remaining(user, now=None):
    now = now or datetime.utcnow()
    if user.locked_until and user.locked_until > now:
        return max(1, int((user.locked_until - now).total_seconds()))
    if user.locked_until:
        user.locked_until = None
        user.failed_login_attempts = 0
    return 0


def register_failure(user, now=None):
    now = now or datetime.utcnow()
    if lockout_remaining(user, now):
        return lockout_remaining(user, now)
    user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
    if user.failed_login_attempts >= MAX_FAILURES:
        user.locked_until = now + timedelta(seconds=LOCKOUT_SECONDS)
        user.failed_login_attempts = 0
        return LOCKOUT_SECONDS
    return 0


def clear_failures(user, now=None):
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = now or datetime.utcnow()


def password_matches(user, supplied):
    return bool(user and user.password_hash and check_password_hash(user.password_hash, supplied or ""))
