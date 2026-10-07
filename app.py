"""
SHADOW - marketplace + food delivery (Flask + HTML/CSS/JS), now backed
by a real SQLite database with real accounts.
Login is Gmail-only (no password, no OTP / verification code).
Admin Gmails are configured via ADMIN1_EMAIL / ADMIN2_EMAIL.
Live chat over Socket.IO.

Run:
    pip install -r requirements.txt
    python app.py

Then open http://127.0.0.1:5000 in your browser (works on desktop and
on a phone browser - see README for how to open it from another device
on your Wi-Fi).

Security summary (see README for the full write-up):
- Passwords: hashed with Werkzeug's PBKDF2 (never stored in plain text).
- OTP codes: hashed, single-use, expire in 2 minutes, rate-limited
  attempts (see otp.py).
- CSRF: every form and every state-changing fetch() call carries a
  CSRF token (Flask-WTF); requests without a valid token are rejected.
- SQL injection: all queries go through the SQLAlchemy ORM.
- Sessions: server-signed cookies (Flask's default), `SESSION_COOKIE_HTTPONLY`
  and `SESSION_COOKIE_SAMESITE=Lax` are set below.
- File uploads: extension allow-list + `secure_filename`.
"""

import os
import time
from datetime import datetime, timedelta
from sqlalchemy import inspect as sa_inspect, text
from dotenv import load_dotenv
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Always load secrets beside this app.py. This avoids accidentally reading a
# different .env from the terminal's current working directory.
load_dotenv(os.path.join(BASE_DIR, ".env"), override=False)

from flask import (
    Flask, render_template, request, redirect, url_for, session, jsonify, flash,
)
from werkzeug.utils import secure_filename
from flask_wtf.csrf import generate_csrf

from extensions import db, socketio, csrf
from models import User, Shop, Product, Order, OrderItem, Favorite, TaxiProfile, Ad, Address, Coupon, WalletTransaction, AuditLog, ProductReview, CommerceSecurityEvent, TelegramReportLog, AppNotification, DeliveryOffer
import constants as const
import otp as otp_service
import security
import email_otp
import manager_bot
import commerce_bot
import geo
import geocode
import timeutil
import telegram_bot
import telegram_reports
import voice_ai
from google_auth import init_google_oauth, google_enabled, oauth
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXT = {"png", "jpg", "jpeg", "webp", "gif"}
OTP_PURPOSE = "verify"

app = Flask(__name__)

# Railway (and most PaaS hosts) terminate HTTPS at a reverse proxy and
# forward plain HTTP to this container, setting X-Forwarded-* headers to
# say what the real client used. Without this, Flask thinks every request
# is plain http:// - which breaks two real things: (1) Google's OAuth
# redirect_uri is built from the request's scheme, so it comes out as
# http://... instead of https://..., which Google rejects as a mismatch
# against the https:// URI registered in Google Cloud Console: this is
# the most common reason "Login with Google" looks broken in production
# even though the code and credentials are correct; (2) session cookies
# marked Secure (see FORCE_HTTPS below) would never be sent back by the
# browser on what it thinks is an http:// origin.
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

def env(key, default=None):
    """os.environ.get(), but a blank value (as left by `cp .env.example .env`
    with a key not yet filled in, e.g. `DATABASE_URL=`) is treated the same
    as the variable being unset, so it still falls back to `default` instead
    of using the empty string."""
    value = os.environ.get(key)
    return value if value else default


_secret = env("SECRET_KEY", "dev-secret-key-change-me")
_flask_env = (os.environ.get("FLASK_ENV") or os.environ.get("ENV") or "").lower()
_is_prod = _flask_env == "production" or os.environ.get("FORCE_PRODUCTION", "").lower() in ("1", "true", "yes")
if _is_prod and _secret in ("dev-secret-key-change-me", "", "change-me", "secret"):
    raise RuntimeError("Set a long random SECRET_KEY in the environment before production.")
app.config["SECRET_KEY"] = _secret
app.config["DEBUG"] = False if _is_prod else (os.environ.get("FLASK_DEBUG", "0").lower() in ("1", "true", "yes"))
app.config["ENV"] = "production" if _is_prod else "development"

# --- Map tiles ---
# Default: OpenStreetMap's standard tile server - genuinely free forever,
# no API key, no account, no billing (their usage policy just asks for
# visible attribution, which we always show below the map). This is the
# same tile source Leaflet's own official examples use.
#
# If you want a paid/keyed provider's dark-styled map instead (MapTiler,
# Stadia Maps, Mapbox, etc.), sign up, copy the exact tile URL THEY give
# you (with your key already baked into it) from their dashboard, and
# set it here - no code changes needed:
#   MAP_TILE_URL=https://api.maptiler.com/maps/dark-matter/{z}/{x}/{y}.png?key=YOUR_KEY
#   MAP_TILE_ATTRIBUTION=&copy; MapTiler &copy; OpenStreetMap contributors
_DEFAULT_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
_DEFAULT_TILE_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
app.config["MAP_TILE_URL"] = env("MAP_TILE_URL", _DEFAULT_TILE_URL)
app.config["MAP_TILE_ATTRIBUTION"] = env("MAP_TILE_ATTRIBUTION", _DEFAULT_TILE_ATTRIBUTION)
app.config["USING_CUSTOM_TILES"] = bool(os.environ.get("MAP_TILE_URL"))
app.config["SQLALCHEMY_DATABASE_URI"] = env(
    "DATABASE_URL", "sqlite:///" + os.path.join(BASE_DIR, "shadow.db")
)
# Render/Railway/Heroku-style platforms hand you a URL starting with
# "postgres://" (old scheme) - SQLAlchemy 2.x needs "postgresql://".
if app.config["SQLALCHEMY_DATABASE_URI"].startswith("postgres://"):
    app.config["SQLALCHEMY_DATABASE_URI"] = app.config["SQLALCHEMY_DATABASE_URI"].replace(
        "postgres://", "postgresql://", 1
    )
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_DIR"] = UPLOAD_DIR
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# Once deployed behind real HTTPS (Render/Railway give you this for free),
# set FORCE_HTTPS=true so session cookies are marked Secure too - browsers
# then refuse to ever send them over a plain http:// connection.
# Never mark cookies Secure for local/LAN HTTP testing. In production, set
# FORCE_HTTPS=true behind a real HTTPS reverse proxy.
app.config["SESSION_COOKIE_SECURE"] = _is_prod and os.environ.get("FORCE_HTTPS", "").lower() in ("1", "true", "yes")
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 8MB upload cap

db.init_app(app)
csrf.init_app(app)
_cors = os.environ.get("SOCKETIO_CORS_ORIGINS", "").strip()
if _cors:
    _cors_list = [o.strip() for o in _cors.split(",") if o.strip()]
elif _is_prod:
    _cors_list = []  # set per-request via after_request not available; require env
else:
    _cors_list = "*"
if _is_prod and _cors_list == []:
    # Fallback: allow only PUBLIC_BASE_URL origin if set
    _pub = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    _cors_list = [_pub] if _pub else "*"
socketio.init_app(
    app,
    cors_allowed_origins=_cors_list,
    logger=False,
    engineio_logger=False,
    message_queue=(os.environ.get("REDIS_URL") or None),
)

init_google_oauth(app)
app.jinja_env.globals["csrf_token"] = generate_csrf
app.jinja_env.filters["mm_datetime"] = timeutil.format_mm
app.jinja_env.filters["mm_short"] = timeutil.format_mm_short
app.jinja_env.filters["mm_time"] = timeutil.format_mm_time
app.jinja_env.globals["now_mm"] = timeutil.now_mm_str

import sockets  # noqa: E402,F401  (registers the @socketio.on(...) handlers)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT



# ---------------------------------------------------------------------------
# Simple in-memory rate limit (per process). For multi-instance use Redis.
# ---------------------------------------------------------------------------
from collections import defaultdict, deque
_rate_buckets = defaultdict(deque)

def rate_limit_ok(key: str, max_hits: int, window_sec: int) -> bool:
    now = time.time()
    q = _rate_buckets[key]
    while q and q[0] < now - window_sec:
        q.popleft()
    if len(q) >= max_hits:
        return False
    q.append(now)
    return True

def save_upload(file_storage):
    if not file_storage or file_storage.filename == "":
        return None
    if not allowed_file(file_storage.filename):
        return None
    filename = secure_filename(file_storage.filename)
    unique = f"{int(time.time() * 1000)}_{filename}"
    data = file_storage.read()
    file_storage.stream.seek(0)
    # Optional S3/R2/Blob via env (production durable storage)
    bucket = os.environ.get("S3_BUCKET") or os.environ.get("UPLOAD_S3_BUCKET")
    if bucket:
        try:
            import boto3
            key_prefix = os.environ.get("S3_PREFIX", "shadow-uploads/")
            key = f"{key_prefix}{unique}"
            client = boto3.client(
                "s3",
                endpoint_url=os.environ.get("S3_ENDPOINT_URL") or None,
                aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID") or os.environ.get("S3_ACCESS_KEY"),
                aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY") or os.environ.get("S3_SECRET_KEY"),
                region_name=os.environ.get("AWS_REGION", "auto"),
            )
            client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=file_storage.mimetype or "application/octet-stream")
            public = os.environ.get("S3_PUBLIC_BASE_URL", "").rstrip("/")
            if public:
                return f"{public}/{key}"
            return client.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=60 * 60 * 24 * 7)
        except Exception as e:
            print("[upload] S3 failed, falling back to local:", e)
    dest = os.path.join(app.config["UPLOAD_DIR"], unique)
    file_storage.save(dest)
    return url_for("static", filename=f"uploads/{unique}")


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return db.session.get(User, uid)

def ensure_delivery_schema():
    """Upgrade databases created by older builds without deleting user data."""
    tables = set(sa_inspect(db.engine).get_table_names())
    # SQLite accepts DATETIME, while PostgreSQL requires TIMESTAMP.
    timestamp_type = "TIMESTAMP" if db.engine.dialect.name == "postgresql" else "DATETIME"
    additions = {
        "user": {
            "username": "VARCHAR(50)", "google_sub": "VARCHAR(255)", "avatar_url": "VARCHAR(255)",
            "last_lat": "FLOAT", "last_lng": "FLOAT", "last_location_at": timestamp_type,
            "address_text": "VARCHAR(255)", "address_lat": "FLOAT", "address_lng": "FLOAT",
            "phone_verified": "BOOLEAN DEFAULT FALSE", "is_banned": "BOOLEAN DEFAULT FALSE",
            "preferred_payment_method": "VARCHAR(20) DEFAULT 'cod'", "wallet_balance": "INTEGER DEFAULT 0",
            "failed_login_attempts": "INTEGER DEFAULT 0", "locked_until": timestamp_type, "last_login_at": timestamp_type,
            "banned_until": timestamp_type, "security_violations": "INTEGER DEFAULT 0",
        },
        "order": {"driver_id": "INTEGER"},
        "taxi_profile": {"last_lat": "FLOAT", "last_lng": "FLOAT"},
        "commerce_security_event": {},
        "chat_message": {
            "msg_type": "VARCHAR(16) DEFAULT 'text'", "reply_to_id": "INTEGER",
            "is_read": "BOOLEAN DEFAULT FALSE", "is_edited": "BOOLEAN DEFAULT FALSE",
            "is_deleted": "BOOLEAN DEFAULT FALSE",
        },
    }
    for table, columns_to_add in additions.items():
        if table not in tables:
            continue
        existing = {column["name"] for column in sa_inspect(db.engine).get_columns(table)}
        for name, sql_type in columns_to_add.items():
            if name not in existing:
                quoted_table = f'"{table}"'
                db.session.execute(text(f'ALTER TABLE {quoted_table} ADD COLUMN "{name}" {sql_type}'))
    # Older deployments used the phone-only OTP schema. Email OTP keys are
    # prefixed with ``email:`` and can exceed VARCHAR(30) on PostgreSQL.
    if db.engine.dialect.name == "postgresql" and "otp_code" in tables:
        otp_columns = {column["name"] for column in sa_inspect(db.engine).get_columns("otp_code")}
        if "phone" in otp_columns:
            db.session.execute(text('ALTER TABLE "otp_code" ALTER COLUMN "phone" TYPE VARCHAR(160)'))
    db.session.commit()



def push_notification(user_id, title, body="", kind="general", link="", commit=False):
    """Create a real in-app notification for the bell icon (no fake rows)."""
    if not user_id:
        return None
    n = AppNotification(
        user_id=user_id, title=(title or "Shadow")[:120],
        body=(body or "")[:2000], kind=kind or "general",
        link=(link or "")[:255], is_read=False,
    )
    db.session.add(n)
    if commit:
        db.session.commit()
    return n

def login_user_session(user):
    session.permanent = True
    session["user_id"] = user.id
    session["role"] = user.role
    session["user_name"] = user.full_name
    session["location"] = user.location_text or "Pyin Oo Lwin, Mandalay Region, Myanmar"


from functools import wraps


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def role_required(role):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("user_id"):
                return redirect(url_for("login", next=request.path))
            if session.get("role") != role:
                return redirect(url_for("home"))
            return view(*args, **kwargs)
        return wrapped
    return decorator

def record_audit(action, module, record_id=None, details=""):
    admin_id = session.get("user_id")
    if not admin_id or session.get("role") != "admin":
        return
    db.session.add(AuditLog(
        admin_id=admin_id, action=action, module=module,
        record_id=str(record_id) if record_id is not None else None,
        details=details, ip_address=request.headers.get("X-Forwarded-For", request.remote_addr),
    ))


def current_cart():
    return session.setdefault("cart", {})


def cart_count():
    return sum(session.get("cart", {}).values())


@app.context_processor
def inject_notification_badge():
    def unread_notification_count():
        uid = session.get("user_id")
        if not uid:
            return 0
        try:
            return AppNotification.query.filter_by(user_id=uid, is_read=False).count()
        except Exception:
            return 0
    return dict(unread_notification_count=unread_notification_count())

@app.context_processor
def inject_globals():
    user = current_user()
    return {
        "cart_count": cart_count(),
        "role": session.get("role"),
        "user_name": session.get("user_name"),
        "seller_shop_id": (user.shop.id if user and user.role == "seller" and user.shop else None),
        "google_enabled": google_enabled(),
        "map_tile_url": app.config["MAP_TILE_URL"],
        "map_tile_attribution": app.config["MAP_TILE_ATTRIBUTION"],
        "using_custom_tiles": app.config["USING_CUSTOM_TILES"],
    }


def get_products_by_shop(shop_id):
    return Product.query.filter_by(shop_id=shop_id).all()


def search_everything(query):
    q = (query or "").strip()
    if not q:
        return Shop.query.all(), Product.query.all()
    like = f"%{q}%"
    shops = Shop.query.filter(db.or_(Shop.name.ilike(like), Shop.category.ilike(like))).all()
    products = Product.query.filter(db.or_(Product.name.ilike(like), Product.category.ilike(like))).all()
    return shops, products


def cart_line_items(cart):
    by_shop = {}
    removed_sold_out = []
    for pid_str, qty in list(cart.items()):
        if qty <= 0:
            continue
        product = db.session.get(Product, int(pid_str))
        if not product:
            continue
        if product.status != "available":
            removed_sold_out.append(product.name)
            cart.pop(pid_str, None)
            session.modified = True
            continue
        shop = product.shop
        entry = by_shop.setdefault(product.shop_id, {"shop": shop, "lines": []})
        entry["lines"].append({"product": product, "qty": qty, "line_total": product.price * qty})
    if removed_sold_out:
        flash(f"Removed from your cart (sold out): {', '.join(removed_sold_out)}", "error")
    return list(by_shop.values())


def cart_totals(grouped_lines, delivery_method="standard", promo_code=""):
    subtotal = sum(line["line_total"] for group in grouped_lines for line in group["lines"])
    shop = grouped_lines[0]["shop"] if grouped_lines else None
    fee = geo.calc_delivery_fee(shop, delivery_method) if subtotal else 0
    distance_km = geo.distance_to_shop(shop) if shop else None

    discount = 0
    coupon_error = None
    code = promo_code.strip().upper()
    if code:
        from datetime import datetime as _dt
        coupon = Coupon.query.filter_by(code=code, is_active=True).first()
        if not coupon:
            coupon_error = "Coupon not found or no longer active."
        elif coupon.expires_at and coupon.expires_at < _dt.utcnow():
            coupon_error = "This coupon has expired."
        elif subtotal < (coupon.min_order or 0):
            coupon_error = f"This coupon needs a minimum order of {coupon.min_order:,} Ks."
        else:
            discount = round(subtotal * coupon.discount_pct / 100)

    service_fee = round(subtotal * 0.02) if subtotal else 0
    total = subtotal + fee + service_fee - discount
    return {"subtotal": subtotal, "delivery_fee": fee, "discount": discount,
            "service_fee": service_fee, "total": max(total, 0), "coupon_error": coupon_error,
            "distance_km": round(distance_km, 1) if distance_km is not None else None}


def ensure_seller_shop(user):
    if not user.shop:
        shop = Shop(owner_id=user.id, name=f"{user.full_name}'s Shop", category="Groceries",
                    description="Tell customers what you sell.")
        db.session.add(shop)
        db.session.commit()
    return user.shop


# ---------------------------------------------------------------------------
# Location gateway - a customer cannot use the shopping app at all until
# they grant (or explicitly deny, landing on a blocker screen) location
# access. This mirrors the requested "GPS Permission Popup" + "Blocker
# Screen" + "Session Location Storage" flow.
# ---------------------------------------------------------------------------

LOCATION_EXEMPT_ENDPOINTS = {
    "splash", "account_type", "register_customer", "register_seller",
    "auth_verify_phone", "auth_otp_request", "auth_otp_verify", "auth_verify_email", "signup_phone", "verify_email_login",
    "login", "auth_google_login", "auth_google_callback", "logout",
    "location_gate", "api_location_set", "link_phone", "link_phone_skip", "static", None,
}


@app.before_request
def enforce_location_gate():
    if session.get("user_id") and session.get("role") != "admin":
        active = db.session.get(User, session["user_id"])
        if active and active.is_banned:
            if active.banned_until and active.banned_until <= datetime.utcnow():
                active.is_banned = False
                active.banned_until = None
                db.session.commit()
            else:
                session.clear()
                flash("This account is temporarily restricted. Contact Shadow support.", "error")
                return redirect(url_for("login"))
    if session.get("role") == "admin":
        last_seen = session.get("admin_last_seen", time.time())
        if time.time() - last_seen > 8 * 60 * 60:
            session.clear()
            flash("Admin session expired. Please sign in again.", "error")
            return redirect(url_for("login"))
        session["admin_last_seen"] = time.time()
        return
    if session.get("role") not in ("customer", "taxi", "seller"):
        return
    if request.endpoint in LOCATION_EXEMPT_ENDPOINTS:
        return
    if "lat" in session and "lng" in session:
        if geo.is_in_myanmar(session.get("lat"), session.get("lng")):
            return
        session.pop("lat", None)
        session.pop("lng", None)
        session["location_blocked"] = True
        session["location_block_reason"] = (
            "Shadow is only available inside Myanmar. "
            "Turn off VPN or fake GPS and use a real Myanmar location."
        )
        session.modified = True
    return redirect(url_for("location_gate"))


@app.route("/location-gate")
@login_required
def location_gate():
    reason = session.get("location_block_reason") or ""
    blocked = bool(session.get("location_blocked"))
    return render_template(
        "location_gate.html",
        outside_myanmar=blocked,
        block_reason=reason,
    )


@app.route("/api/location/set", methods=["POST"])
@login_required
def api_location_set():
    data = request.get_json(force=True) or {}
    lat, lng = data.get("lat"), data.get("lng")
    if lat is None or lng is None:
        return jsonify({"ok": False, "error": "missing_coords"}), 400
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "invalid_coords"}), 400

    outside = geo.myanmar_location_error(lat, lng)
    if outside:
        session.pop("lat", None)
        session.pop("lng", None)
        session["location_blocked"] = True
        session["location_block_reason"] = outside
        session.modified = True
        return jsonify({"ok": False, "error": "outside_myanmar", "message": outside}), 403

    place_name = geocode.reverse_geocode(lat, lng) or ""
    lower = place_name.lower()
    if lower and any(k in lower for k in (
        "thailand", "china", "india", "bangladesh", "laos", "malaysia",
        "singapore", "united states", "usa", "uk", "korea", "japan",
    )) and "myanmar" not in lower and "burma" not in lower:
        msg = (
            "Shadow is only available inside Myanmar. "
            "Detected location suggests another country. "
            "Disable VPN / fake GPS and try again."
        )
        session.pop("lat", None)
        session.pop("lng", None)
        session["location_blocked"] = True
        session["location_block_reason"] = msg
        session.modified = True
        return jsonify({"ok": False, "error": "outside_myanmar", "message": msg}), 403

    session["lat"] = lat
    session["lng"] = lng
    session["location"] = place_name or "Myanmar"
    session.pop("location_blocked", None)
    session.pop("location_block_reason", None)
    user = current_user()
    if user:
        user.location_text = place_name or user.location_text
        user.last_lat = lat
        user.last_lng = lng
        user.last_location_at = datetime.utcnow()
        # Drivers: also mirror onto taxi profile for Dispatch Bot radius
        if user.role == "taxi":
            profile = user.taxi_profile
            if profile is None:
                profile = TaxiProfile(owner_id=user.id)
                db.session.add(profile)
            profile.last_lat = lat
            profile.last_lng = lng
        db.session.commit()
    session.modified = True
    return jsonify({"ok": True, "place_name": session["location"]})


@app.route("/address")
@login_required
def address_picker():
    user = current_user()
    start_lat = user.address_lat or session.get("lat") or 22.03455
    start_lng = user.address_lng or session.get("lng") or 96.45875
    return render_template(
        "address_picker.html", start_lat=start_lat, start_lng=start_lng,
        current_address=user.address_text,
    )


@app.route("/api/geocode/reverse", methods=["POST"])
@login_required
def api_geocode_reverse():
    data = request.get_json(force=True) or {}
    lat, lng = data.get("lat"), data.get("lng")
    if lat is None or lng is None:
        return jsonify({"ok": False}), 400
    address_text = geocode.reverse_geocode_street(float(lat), float(lng))
    return jsonify({"ok": True, "address_text": address_text})


@app.route("/api/address/set", methods=["POST"])
@login_required
def api_address_set():
    data = request.get_json(force=True) or {}
    lat, lng = data.get("lat"), data.get("lng")
    address_text = (data.get("address_text") or "").strip()
    label = (data.get("label") or "Home").strip()[:30]
    if lat is None or lng is None or not address_text:
        return jsonify({"ok": False, "error": "Missing pin location or address."}), 400
    try:
        lat_f, lng_f = float(lat), float(lng)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Invalid coordinates."}), 400
    outside = geo.myanmar_location_error(lat_f, lng_f)
    if outside:
        return jsonify({"ok": False, "error": "outside_myanmar", "message": outside}), 403

    user = current_user()
    user.address_lat = lat_f
    user.address_lng = lng_f
    user.address_text = address_text

    # Also save/update this as a named entry in the address book, so it
    # shows up under "My Addresses" for next time instead of only being
    # remembered as the single "current" address.
    entry = Address.query.filter_by(user_id=user.id, label=label).first()
    if not entry:
        entry = Address(user_id=user.id, label=label)
        db.session.add(entry)
    entry.address_text = address_text
    entry.lat = float(lat)
    entry.lng = float(lng)

    db.session.commit()
    session.setdefault("lat", user.address_lat)
    session.setdefault("lng", user.address_lng)
    session.modified = True
    return jsonify({"ok": True, "address_text": address_text})


@app.route("/addresses")
@login_required
def my_addresses():
    user = current_user()
    addresses = Address.query.filter_by(user_id=user.id).order_by(Address.created_at.desc()).all()
    return render_template("my_addresses.html", addresses=addresses, user=user)


@app.route("/addresses/<int:address_id>/set-default", methods=["POST"])
@login_required
def address_set_default(address_id):
    addr = db.get_or_404(Address, address_id)
    if addr.user_id != session["user_id"]:
        return jsonify({"ok": False}), 403
    user = current_user()
    user.address_lat, user.address_lng, user.address_text = addr.lat, addr.lng, addr.address_text
    db.session.commit()
    session["lat"], session["lng"] = addr.lat, addr.lng
    session.modified = True
    return jsonify({"ok": True})


@app.route("/addresses/<int:address_id>/delete", methods=["POST"])
@login_required
def address_delete(address_id):
    addr = db.get_or_404(Address, address_id)
    if addr.user_id != session["user_id"]:
        return jsonify({"ok": False}), 403
    db.session.delete(addr)
    db.session.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Onboarding: splash -> account type -> register/login (OTP + Google)
# ---------------------------------------------------------------------------

def validate_registration_fields(email, password):
    ok, message, normalized_email = security.validate_email(email)
    if not ok:
        return None, message
    if password:
        ok, message = security.validate_password(password)
        if not ok:
            return None, message
    return normalized_email, None

@app.route("/")
def splash():
    return render_template("splash.html")


@app.route("/account-type")
def account_type():
    return render_template("account_type.html")


@app.route("/register/customer", methods=["GET", "POST"])
def register_customer():
    if request.method == "POST":
        username = security.normalize_username(request.form.get("username"))
        valid_user, user_error = security.validate_username(username)
        valid_email, email_error, email = security.validate_email(request.form.get("email"), required=True)
        if not valid_user or not valid_email:
            flash(user_error or email_error, "error")
            return redirect(url_for("register_customer"))
        if User.query.filter_by(email=email).first():
            flash("This Gmail is already registered. Please sign in.", "error")
            return redirect(url_for("login"))
        if username and User.query.filter_by(username=username).first():
            flash("This username is already taken.", "error")
            return redirect(url_for("register_customer"))
        # Block registering the configured admin Gmails as customer.
        allowed_admin_emails = {
            security.normalize_email(env("ADMIN1_EMAIL", "")),
            security.normalize_email(env("ADMIN2_EMAIL", "")),
        } - {None, ""}
        if email in allowed_admin_emails:
            flash("This Gmail is reserved for admin. Use Sign in instead.", "error")
            return redirect(url_for("login"))
        full_name = (request.form.get("full_name") or "Shadow User").strip()
        user = User(role="customer", full_name=full_name, username=username or None, email=email)
        db.session.add(user)
        db.session.commit()
        login_user_session(user)
        flash("Account created. Welcome!", "success")
        return redirect(url_for("home"))
    return render_template("register_customer.html")


@app.route("/register/seller", methods=["GET", "POST"])
def register_seller():
    if request.method == "POST":
        username = security.normalize_username(request.form.get("username"))
        valid_user, user_error = security.validate_username(username)
        valid_email, email_error, email = security.validate_email(request.form.get("email"), required=True)
        if not valid_user or not valid_email:
            flash(user_error or email_error, "error")
            return redirect(url_for("register_seller"))
        if User.query.filter_by(email=email).first():
            flash("This Gmail is already registered. Please sign in.", "error")
            return redirect(url_for("login"))
        if username and User.query.filter_by(username=username).first():
            flash("This username is already taken.", "error")
            return redirect(url_for("register_seller"))
        allowed_admin_emails = {
            security.normalize_email(env("ADMIN1_EMAIL", "")),
            security.normalize_email(env("ADMIN2_EMAIL", "")),
        } - {None, ""}
        if email in allowed_admin_emails:
            flash("This Gmail is reserved for admin. Use Sign in instead.", "error")
            return redirect(url_for("login"))
        logo_url = save_upload(request.files.get("shop_logo"))
        cover_url = save_upload(request.files.get("shop_cover"))
        full_name = (request.form.get("owner_name") or "Shadow Seller").strip()
        user = User(role="seller", full_name=full_name, username=username or None, email=email)
        db.session.add(user)
        db.session.flush()
        db.session.add(Shop(
            owner_id=user.id,
            name=request.form.get("shop_name") or "My New Shop",
            category=request.form.get("shop_category") or "Groceries",
            description=request.form.get("shop_description") or "",
            logo_url=logo_url,
            cover_url=cover_url,
        ))
        db.session.commit()
        login_user_session(user)
        flash("Shop account created. Welcome!", "success")
        return redirect(url_for("seller_dashboard"))
    return render_template("register_seller.html")


@app.route("/register/taxi", methods=["GET", "POST"])
def register_taxi():
    if request.method == "POST":
        username = security.normalize_username(request.form.get("username"))
        valid_user, user_error = security.validate_username(username)
        valid_email, email_error, email = security.validate_email(request.form.get("email"), required=True)
        if not valid_user or not valid_email:
            flash(user_error or email_error, "error")
            return redirect(url_for("register_taxi"))
        if User.query.filter_by(email=email).first():
            flash("This Gmail is already registered. Please sign in.", "error")
            return redirect(url_for("login"))
        if username and User.query.filter_by(username=username).first():
            flash("This username is already taken.", "error")
            return redirect(url_for("register_taxi"))
        allowed_admin_emails = {
            security.normalize_email(env("ADMIN1_EMAIL", "")),
            security.normalize_email(env("ADMIN2_EMAIL", "")),
        } - {None, ""}
        if email in allowed_admin_emails:
            flash("This Gmail is reserved for admin. Use Sign in instead.", "error")
            return redirect(url_for("login"))
        vehicle_photo_url = save_upload(request.files.get("vehicle_photo"))
        full_name = (request.form.get("full_name") or "Shadow Driver").strip()
        user = User(role="taxi", full_name=full_name, username=username or None, email=email)
        db.session.add(user)
        db.session.flush()
        db.session.add(TaxiProfile(
            owner_id=user.id,
            vehicle_type=request.form.get("vehicle_type") or "car",
            vehicle_photo_url=vehicle_photo_url,
        ))
        db.session.commit()
        login_user_session(user)
        flash("Driver account created. Welcome!", "success")
        return redirect(url_for("driver_orders"))
    return render_template("register_taxi.html")


@app.route("/auth/verify-phone")
def auth_verify_phone():
    pending = session.get("pending_registration")
    if pending and not session.get("email_verified"):
        return redirect(url_for("auth_verify_email"))
    phone = pending["phone"] if pending else request.args.get("phone", "")
    if not phone:
        return redirect(url_for("login"))
    return render_template("auth_verify_phone.html", phone=phone)


@app.route("/auth/verify-email", methods=["GET", "POST"])
def auth_verify_email():
    pending = session.get("pending_registration") or {}
    email = pending.get("email")
    if not email:
        return redirect(url_for("account_type"))
    if request.method == "POST":
        code = request.form.get("code", "")
        if not email_otp.verify_code(email, code, "signup_email"):
            flash("That email verification code is invalid or expired.", "error")
            return redirect(url_for("auth_verify_email"))
        session["email_verified"] = True
        return redirect(url_for("signup_phone"))
    return render_template("auth_verify_email.html", email=email)


def finalize_pending_registration(pending, phone):
    existing = User.query.filter((User.username == pending.get("username")) | (User.email == pending.get("email"))).first()
    if existing:
        return None, "That username or email is already registered."
    user = User(role=pending["role"], full_name=pending["full_name"], username=pending.get("username"),
                phone=phone, email=pending.get("email"), phone_verified=False)
    db.session.add(user)
    db.session.flush()
    if pending["role"] == "seller":
        db.session.add(Shop(owner_id=user.id, name=pending["shop_name"], category=pending["shop_category"],
                            description=pending["shop_description"], logo_url=pending.get("logo_url"), cover_url=pending.get("cover_url")))
    elif pending["role"] == "taxi":
        db.session.add(TaxiProfile(owner_id=user.id, vehicle_type=pending.get("vehicle_type", "car"), vehicle_photo_url=pending.get("vehicle_photo_url")))
    return user, None


@app.route("/auth/signup-phone", methods=["GET", "POST"])
def signup_phone():
    pending = session.get("pending_registration") or {}
    if not pending or not session.get("email_verified"):
        return redirect(url_for("account_type"))
    if request.method == "POST":
        phone = otp_service.normalize_phone(request.form.get("phone", "").strip())
        if not phone or len(phone) < 8:
            flash("Please enter a valid phone number.", "error")
            return redirect(url_for("signup_phone"))
        user, error = finalize_pending_registration(pending, phone)
        if error:
            flash(error, "error")
            return redirect(url_for("signup_phone"))
        db.session.commit()
        session.pop("pending_registration", None)
        session.pop("email_verified", None)
        login_user_session(user)
        if user.role == "seller": return redirect(url_for("seller_dashboard"))
        if user.role == "taxi": return redirect(url_for("taxi_profile_edit"))
        return redirect(url_for("home"))
    return render_template("signup_phone.html", email=pending.get("email"))


@app.route("/auth/otp/request", methods=["POST"])
def auth_otp_request():
    data = request.get_json(force=True) or {}
    phone = (data.get("phone") or "").strip()
    if not phone:
        return jsonify({"ok": False, "error": "Phone number is required."}), 400
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    if not rate_limit_ok(f"otp:{ip}", 5, 600) or not rate_limit_ok(f"otp-phone:{phone}", 3, 600):
        return jsonify({"ok": False, "error": "Too many OTP requests. Try again later."}), 429
    result = otp_service.generate_and_send_otp(phone, purpose=OTP_PURPOSE)
    # Always return ok=True if code was created; warn if SMS provider failed
    # so local/console still works. Client can show a soft message.
    payload = {"ok": True, "phone": result.get("phone")}
    if result.get("error"):
        payload["sms_warning"] = result["error"]
    return jsonify(payload)


@app.route("/auth/otp/verify", methods=["POST"])
def auth_otp_verify():
    data = request.get_json(force=True) or {}
    phone = (data.get("phone") or "").strip()
    code = (data.get("code") or "").strip()

    if session.get("pending_registration") and not session.get("email_verified"):
        return jsonify({"ok": False, "error": "Verify your Gmail before verifying your phone."}), 403
    if not otp_service.verify_otp(phone, code, purpose=OTP_PURPOSE):
        return jsonify({"ok": False, "error": "That code is invalid or expired."}), 400

    pending = session.pop("pending_registration", None)
    session.pop("email_verified", None)
    if pending:
        normalized_email, email_error = security.validate_email(pending.get("email"))
        if email_error:
            return jsonify({"ok": False, "error": email_error}), 400
        pending["email"] = normalized_email
    user = User.query.filter_by(phone=phone).first()

    # Prevent duplicate email registration. A user may verify a phone number
    # while the email was already registered before. Reuse that account
    # instead of crashing on the UNIQUE email constraint.
    if user is None and pending and pending.get("email"):
        user = User.query.filter_by(email=pending.get("email")).first()

    if user is None:
        if pending and pending.get("phone") == phone:
            user = User(role=pending["role"], full_name=pending["full_name"],
                        username=pending.get("username"), phone=phone, email=pending.get("email"))
            user.phone_verified = True
            db.session.add(user)
            db.session.flush()
            if pending["role"] == "seller":
                db.session.add(Shop(
                    owner_id=user.id, name=pending["shop_name"], category=pending["shop_category"],
                    description=pending["shop_description"], logo_url=pending.get("logo_url"),
                    cover_url=pending.get("cover_url"),
                ))
            elif pending["role"] == "taxi":
                db.session.add(TaxiProfile(
                    owner_id=user.id, vehicle_type=pending.get("vehicle_type", "car"),
                    vehicle_photo_url=pending.get("vehicle_photo_url"),
                ))
        else:
            # Login OTP only works for existing accounts. New users must register first.
            return jsonify({
                "ok": False,
                "error": "No account with this phone. Please register / sign up first.",
                "need_register": True,
            }), 404
    else:
        user.phone_verified = True
        if not user.phone:
            user.phone = phone

    db.session.commit()
    login_user_session(user)
    dest = url_for("home") if user.role != "admin" else url_for("admin_dashboard")
    return jsonify({"ok": True, "redirect": dest})


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        _lip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
        if not rate_limit_ok(f"login:{_lip}", 20, 300):
            flash("Too many login attempts. Wait a few minutes.", "error")
            return redirect(url_for("login"))

        identifier = request.form.get("identifier", "").strip()
        valid_email, email_err, normalized_email = security.validate_email(identifier)
        if not valid_email:
            flash(email_err or "Please enter a valid Gmail address.", "error")
            return redirect(url_for("login"))

        user = User.query.filter_by(email=normalized_email).first()
        if not user or user.is_banned:
            flash("No account found with this Gmail. Please register first.", "error")
            return redirect(url_for("login"))

        allowed_admin_emails = {
            security.normalize_email(env("ADMIN1_EMAIL", "")),
            security.normalize_email(env("ADMIN2_EMAIL", "")),
        } - {None, ""}
        if user.role == "admin" and normalized_email not in allowed_admin_emails:
            flash("This admin account is not authorized.", "error")
            return redirect(url_for("login"))

        # Direct Gmail login — no password, no OTP / verification code.
        security.clear_failures(user)
        db.session.commit()
        login_user_session(user)
        next_url = request.form.get("next") or ""
        if next_url and next_url.startswith("/"):
            return redirect(next_url)
        if user.role == "admin":
            return redirect(url_for("admin_dashboard"))
        if user.role == "seller":
            return redirect(url_for("seller_dashboard"))
        if user.role == "taxi":
            return redirect(url_for("driver_orders"))
        return redirect(url_for("home"))
    return render_template("login.html")


@app.route("/auth/email-login/verify", methods=["POST"])
def verify_email_login():
    email = session.get("pending_email_login")
    code = request.form.get("code", "")
    user = User.query.filter_by(email=email).first() if email else None
    if user and security.lockout_remaining(user):
        remaining = security.lockout_remaining(user)
        db.session.commit()
        flash(f"Too many attempts. Try again in {remaining} seconds.", "error")
        return redirect(url_for("login"))
    if not email or not email_otp.verify_code(email, code, "login_email"):
        if user:
            remaining = security.register_failure(user)
            db.session.commit()
            if remaining:
                flash(f"Too many attempts. Try again in {remaining} seconds.", "error")
                return redirect(url_for("login"))
        flash("That verification code is invalid or expired.", "error")
        return redirect(url_for("login"))
    if not user or user.is_banned:
        flash("We could not verify that account.", "error")
        return redirect(url_for("login"))
    session.pop("pending_email_login", None)
    next_url = session.pop("pending_login_next", "")
    security.clear_failures(user)
    db.session.commit()
    login_user_session(user)
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        return redirect(next_url)
    if user.role == "admin": return redirect(url_for("admin_dashboard"))
    if user.role == "seller": return redirect(url_for("seller_dashboard"))
    if user.role == "taxi": return redirect(url_for("taxi_profile_edit"))
    return redirect(url_for("home"))


@app.route("/auth/google/login")
def auth_google_login():
    role = request.args.get("role", "customer")
    if not google_enabled():
        return redirect(url_for("login", google="unavailable"))
    session["oauth_role"] = role
    redirect_uri = env("GOOGLE_REDIRECT_URI") or url_for("auth_google_callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@app.route("/auth/google/callback")
def auth_google_callback():
    if not google_enabled():
        return redirect(url_for("login"))
    try:
        token = oauth.google.authorize_access_token()
        resp = oauth.google.get("https://openidconnect.googleapis.com/v1/userinfo", token=token)
        info = resp.json()
    except Exception:
        flash("Google sign-in failed or was cancelled.", "error")
        return redirect(url_for("login"))

    google_sub = info.get("sub")
    email = info.get("email")
    name = info.get("name") or "Shadow User"
    picture = info.get("picture")

    user = User.query.filter_by(google_sub=google_sub).first()
    if not user and email:
        user = User.query.filter_by(email=email).first()

    oauth_role = (session.pop("oauth_role", None) or "customer").lower()
    if oauth_role not in {"customer", "seller", "taxi"}:
        oauth_role = "customer"

    if not user:
        user = User(role=oauth_role, full_name=name, email=email,
                    google_sub=google_sub, avatar_url=picture)
        db.session.add(user)
        db.session.flush()
        if oauth_role == "seller":
            db.session.add(Shop(owner_id=user.id, name=f"{name}'s Shop", category="General", description="Add your shop details in Seller settings."))
        elif oauth_role == "taxi":
            db.session.add(TaxiProfile(owner_id=user.id, vehicle_type="car"))

    # Link Google identity to existing account
    user.google_sub = user.google_sub or google_sub
    user.avatar_url = user.avatar_url or picture
    if email and not user.email:
        user.email = email
    db.session.commit()
    login_user_session(user)

    # If account has no phone yet, ask once to link phone (for OTP login later)
    if not user.phone:
        session["need_link_phone"] = True
        return redirect(url_for("link_phone"))

    return redirect(url_for("admin_dashboard") if user.role == "admin" else url_for("home"))



@app.route("/auth/link-phone", methods=["GET", "POST"])
@login_required
def link_phone():
    """After Google login, let the user attach a phone so OTP login works later."""
    user = current_user()
    if request.method == "POST":
        phone = (request.form.get("phone") or "").strip()
        if not phone:
            flash("Phone number is required.", "error")
            return redirect(url_for("link_phone"))
        taken = User.query.filter(User.phone == phone, User.id != user.id).first()
        if taken:
            flash("This phone is already used by another account.", "error")
            return redirect(url_for("link_phone"))
        normalized = phone.replace(" ", "").replace("-", "")
        if not (normalized.startswith("+") or normalized.isdigit()):
            flash("Please enter a valid phone number.", "error")
            return redirect(url_for("link_phone"))
        user.phone = normalized
        user.phone_verified = True
        db.session.commit()
        session.pop("need_link_phone", None)
        flash("Phone linked. You can log in with OTP next time.", "success")
        if user.role == "seller":
            return redirect(url_for("seller_dashboard"))
        if user.role == "taxi":
            return redirect(url_for("taxi_profile_edit"))
        return redirect(url_for("home"))
    return render_template("link_phone.html", user=user)


@app.route("/auth/link-phone/skip", methods=["POST"])
@login_required
def link_phone_skip():
    if session.get("need_link_phone"):
        flash("Please add a phone number to finish your Google account.", "error")
        return redirect(url_for("link_phone"))
    session.pop("need_link_phone", None)
    return redirect(url_for("home"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("splash"))


# ---------------------------------------------------------------------------
# Customer app
# ---------------------------------------------------------------------------

@app.route("/home")
@login_required
def home():
    popular = geo.attach_live_distance(Shop.query.all())
    popular.sort(key=lambda s: s.live_distance_km)
    popular = popular[:3]
    flash_deals = Product.query.filter(Product.discount_pct >= 15).limit(4).all()
    user = current_user()
    map_lat = user.address_lat or session.get("lat") or 22.03455
    map_lng = user.address_lng or session.get("lng") or 96.45875

    # Category rows: one horizontally-scrollable shelf per category that
    # actually has products, so scrolling down moves between categories
    # and scrolling a shelf sideways browses that category's items -
    # skips any category with nothing listed yet instead of showing an
    # empty row.
    category_rows = []
    for cat in const.CATEGORIES:
        items = (
            Product.query.filter_by(category=cat["name"], status="available")
            .order_by(Product.reviews_count.desc())
            .limit(10)
            .all()
        )
        if items:
            category_rows.append({"name": cat["name"], "products": items})

    return render_template(
        "home.html", categories=const.CATEGORIES[:8], shops=popular, flash_deals=flash_deals,
        user_address=user.address_text, map_lat=map_lat, map_lng=map_lng,
        shops_json=[s.to_public_dict() for s in popular], category_rows=category_rows,
        active_ads=active_ads(),
    )


@app.route("/categories")
def categories():
    return render_template("categories.html", categories=const.CATEGORIES)


@app.route("/search")
def search():
    query = request.args.get("q", "")
    category = request.args.get("category", "")
    shops, products = search_everything(query or category)
    shops = geo.attach_live_distance(shops)
    if not (query or category):
        # Nothing specific being searched for -> browse view, nearest first.
        shops.sort(key=lambda s: s.live_distance_km)
    # A direct shop-name search always shows that shop regardless of
    # distance - we simply never filter/re-sort matches by distance here.
    return render_template("search.html", query=query or category, shops=shops, products=products)


@app.route("/shop/<int:shop_id>")
def shop_detail(shop_id):
    shop = db.get_or_404(Shop, shop_id)
    geo.attach_live_distance([shop])
    products = get_products_by_shop(shop_id)
    customer_loc = geo.delivery_location() or (shop.lat + 0.01, shop.lng + 0.01)
    return render_template("shop_detail.html", shop=shop, products=products, customer_loc=customer_loc)


@app.route("/product/<int:product_id>")
def product_detail(product_id):
    product = db.get_or_404(Product, product_id)
    shop = product.shop
    related = [p for p in get_products_by_shop(product.shop_id) if p.id != product_id][:4]
    return render_template("product_detail.html", product=product, shop=shop, related=related)


@app.route("/nearby")
def nearby():
    shops = Shop.query.all()
    shops_json = [s.to_public_dict() for s in shops]
    return render_template("nearby.html", shops=shops, shops_json=shops_json)


@app.route("/taxi-drivers")
def taxi_drivers():
    profiles = (
        TaxiProfile.query.join(User, TaxiProfile.owner_id == User.id)
        .filter(TaxiProfile.is_available.is_(True))
        .all()
    )
    # Attach approximate lat/lng from owner address for distance sorting
    drivers = []
    for p in profiles:
        owner = p.owner
        lat = getattr(owner, "address_lat", None)
        lng = getattr(owner, "address_lng", None)
        # lightweight proxy object attributes used by template
        p.lat = lat
        p.lng = lng
        drivers.append(p)
    return render_template("taxi_list.html", drivers=drivers)


@app.route("/taxi/profile", methods=["GET", "POST"])
@role_required("taxi")
def taxi_profile_edit():
    user = current_user()
    profile = user.taxi_profile
    if profile is None:
        profile = TaxiProfile(owner_id=user.id)
        db.session.add(profile)

    if request.method == "POST":
        profile.vehicle_type = request.form.get("vehicle_type") or profile.vehicle_type
        profile.is_available = request.form.get("is_available") == "on"
        new_photo = save_upload(request.files.get("vehicle_photo"))
        if new_photo:
            profile.vehicle_photo_url = new_photo
        db.session.commit()
        flash("Driver profile updated.", "success")
        return redirect(url_for("taxi_profile_edit"))

    return render_template("taxi_profile_edit.html", profile=profile, user=user)


@app.route("/cart")
def cart():
    grouped = cart_line_items(current_cart())
    totals = cart_totals(grouped)
    return render_template("cart.html", grouped=grouped, totals=totals)


@app.route("/api/cart/apply-coupon", methods=["POST"])
@login_required
def api_apply_coupon():
    data = request.get_json(force=True) or {}
    grouped = cart_line_items(current_cart())
    totals = cart_totals(grouped, data.get("delivery_method", "standard"), data.get("promo_code", ""))
    return jsonify(totals)


@app.route("/checkout", methods=["GET", "POST"])
@login_required
def checkout():
    grouped = cart_line_items(current_cart())
    shop = grouped[0]["shop"] if grouped else None
    user = current_user()

    if request.method == "POST":
        delivery_method = request.form.get("delivery_method", "standard")
        payment_method = request.form.get("payment_method", "kbz")
        address = request.form.get("address", "No address provided")
        if not grouped:
            return redirect(url_for("home"))
        if len(grouped) != 1:
            commerce_bot.log_event(db, session.get("user_id"), "cross_shop_order_blocked", f"shops={len(grouped)}", request.remote_addr)
            db.session.commit()
            flash("Please place separate orders for items from different shops.", "error")
            return redirect(url_for("cart"))
        valid_cart, cart_error = commerce_bot.validate_cart(grouped)
        if not valid_cart:
            commerce_bot.log_event(db, session.get("user_id"), "invalid_order_quantity", cart_error, request.remote_addr)
            db.session.commit()
            flash(cart_error, "error")
            return redirect(url_for("cart"))
        recent = (Order.query.filter_by(customer_id=session["user_id"], shop_id=grouped[0]["shop"].id)
                  .filter(Order.created_at >= datetime.utcnow() - timedelta(seconds=30)).first())
        if recent:
            commerce_bot.log_event(db, session.get("user_id"), "duplicate_order_blocked", f"recent_order={recent.id}", request.remote_addr)
            db.session.commit()
            flash("A very similar order was just placed. Please wait a moment.", "error")
            return redirect(url_for("order_tracking", order_id=recent.id))

        screenshot_url = None
        if payment_method in ("kbz", "wave"):
            screenshot_url = save_upload(request.files.get("payment_screenshot"))
            if not screenshot_url:
                flash("Please upload a payment screenshot for KBZ Pay / Wave Pay orders.", "error")
                return redirect(url_for("checkout", delivery_method=delivery_method))

        totals = cart_totals(grouped, delivery_method, request.form.get("promo_code", ""))
        if totals.get("coupon_error"):
            flash(totals["coupon_error"], "error")
            return redirect(url_for("checkout", delivery_method=delivery_method))
        shop_id = grouped[0]["shop"].id
        code = f"SHD{123456 + Order.query.count() + 1}"
        delivery_loc = geo.delivery_location()
        order = Order(
            code=code, customer_id=session["user_id"], shop_id=shop_id,
            subtotal=totals["subtotal"], delivery_fee=totals["delivery_fee"],
            discount=totals["discount"], service_fee=totals["service_fee"], total=totals["total"],
            status="Order Placed", delivery_method=delivery_method, payment_method=payment_method,
            payment_screenshot_url=screenshot_url, address=address,
            contact_phone=request.form.get("contact"),
            delivery_lat=delivery_loc[0] if delivery_loc else None,
            delivery_lng=delivery_loc[1] if delivery_loc else None,
        )
        db.session.add(order)
        db.session.flush()
        for group in grouped:
            for line in group["lines"]:
                db.session.add(OrderItem(
                    order_id=order.id, product_id=line["product"].id,
                    product_name=line["product"].name, qty=line["qty"],
                    price_at_purchase=line["product"].price,
                ))
                line["product"].stock -= line["qty"]
        db.session.commit()

        # Real-time "new order" alert to the shop's dashboard (Socket.IO).
        shop_owner = db.session.get(Shop, shop_id)
        if shop_owner:
            push_notification(shop_owner.owner_id, "New order", f"{order.code} · {order.total} Ks", kind="order", link=url_for("seller_orders"))
        socketio.emit("new_order", {
            "order_id": order.id, "code": order.code, "total": order.total,
            "customer": session.get("user_name", "A customer"),
        }, room=f"shop-{shop_id}")

        # Dispatch Bot: notify nearby riders (~3 miles of shop)
        try:
            _dispatch_after_order(order, db.session.get(Shop, shop_id))
        except Exception as _de:
            print("[DispatchBot] offer error", _de)

        session["cart"] = {}
        session.modified = True
        return redirect(url_for("order_tracking", order_id=order.id))

    delivery_method = request.args.get("delivery_method", "standard")
    totals = cart_totals(grouped, delivery_method)
    delivery_options = [
        {**m, "computed_fee": geo.calc_delivery_fee(shop, m["id"])}
        for m in const.DELIVERY_METHODS
    ]
    return render_template(
        "checkout.html", grouped=grouped, totals=totals, selected_delivery=delivery_method,
        saved_address=user.address_text,
        delivery_methods=delivery_options, payment_methods=const.PAYMENT_METHODS,
    )




def _dispatch_models():
    return {
        "Order": Order,
        "User": User,
        "TaxiProfile": TaxiProfile,
        "DeliveryOffer": DeliveryOffer,
    }


def _dispatch_after_order(order, shop):
    """Create offers and socket-notify each nearby rider."""
    if not order or not shop:
        return
    created = dispatch_bot.create_offers_for_order(db, _dispatch_models(), order, shop)
    db.session.commit()
    for offer, driver, dist in created:
        payload = {
            "offer_id": offer.id,
            "order_id": order.id,
            "code": order.code,
            "shop_name": shop.name,
            "shop_lat": shop.lat,
            "shop_lng": shop.lng,
            "customer_address": order.address or "",
            "delivery_lat": order.delivery_lat,
            "delivery_lng": order.delivery_lng,
            "distance_km": offer.distance_km,
            "shop_to_customer_km": offer.shop_to_customer_km,
            "total": order.total,
            "message": offer.message,
        }
        socketio.emit("delivery_offer", payload, room=f"driver-{driver.id}")
        # In-app notification
        try:
            push_notification(
                driver.id,
                "New delivery nearby",
                f"{shop.name} · {offer.distance_km:.1f} km · {order.code}",
                kind="order",
                link=url_for("driver_orders"),
                commit=False,
            )
        except Exception:
            pass
    if created:
        db.session.commit()
        print(f"[DispatchBot] order {order.code}: {len(created)} rider offers")
    else:
        print(f"[DispatchBot] order {order.code}: no nearby riders")


@app.route("/api/driver/offers")
@role_required("taxi")
def api_driver_offers():
    uid = session["user_id"]
    rows = (
        DeliveryOffer.query.filter_by(driver_id=uid, status="pending")
        .order_by(DeliveryOffer.created_at.desc())
        .limit(30)
        .all()
    )
    out = []
    for o in rows:
        order = o.order
        shop = order.shop if order else None
        out.append({
            "offer_id": o.id,
            "order_id": o.order_id,
            "code": order.code if order else "",
            "shop_name": shop.name if shop else "",
            "distance_km": o.distance_km,
            "shop_to_customer_km": o.shop_to_customer_km,
            "message": o.message,
            "total": order.total if order else 0,
            "delivery_lat": order.delivery_lat if order else None,
            "delivery_lng": order.delivery_lng if order else None,
            "shop_lat": shop.lat if shop else None,
            "shop_lng": shop.lng if shop else None,
        })
    return jsonify({"ok": True, "offers": out})


@app.route("/api/driver/offers/<int:offer_id>/accept", methods=["POST"])
@role_required("taxi")
def api_driver_accept_offer(offer_id):
    uid = session["user_id"]
    ok, err, *rest = dispatch_bot.accept_offer(db, _dispatch_models(), offer_id, uid)
    if not ok:
        return jsonify({"ok": False, "error": err}), 409
    order = rest[0]
    cancelled_ids = rest[1] if len(rest) > 1 else []
    shop = order.shop
    payload = {
        "status": order.status,
        "order_id": order.id,
        "code": order.code,
        "driver_id": uid,
        "driver_name": session.get("user_name") or order.rider_name,
        "shop_name": shop.name if shop else "",
    }
    socketio.emit("order_status_update", payload, room=f"order-{order.id}")
    socketio.emit("order_status_update", payload, room=f"customer-{order.customer_id}")
    socketio.emit("driver_order_assigned", payload, room=f"driver-{uid}")
    # Auto-delete offers on other drivers' devices
    for did in cancelled_ids:
        socketio.emit("delivery_offer_taken", {
            "offer_order_id": order.id,
            "order_id": order.id,
            "code": order.code,
        }, room=f"driver-{did}")
    # Notify customer
    try:
        push_notification(
            order.customer_id,
            "Rider assigned",
            f"{order.code}: {payload['driver_name']} is on the way to pick up",
            kind="order",
            link=url_for("order_tracking", order_id=order.id),
            commit=True,
        )
    except Exception:
        db.session.commit()
    return jsonify({
        "ok": True,
        "order_id": order.id,
        "status": order.status,
        "track_url": url_for("order_tracking", order_id=order.id),
        "shop_lat": shop.lat if shop else None,
        "shop_lng": shop.lng if shop else None,
        "delivery_lat": order.delivery_lat,
        "delivery_lng": order.delivery_lng,
        "shop_to_customer_km": dispatch_bot.haversine_km(
            shop.lat, shop.lng, order.delivery_lat or shop.lat, order.delivery_lng or shop.lng
        ) if shop and shop.lat is not None else None,
    })


@app.route("/api/driver/offers/<int:offer_id>/decline", methods=["POST"])
@role_required("taxi")
def api_driver_decline_offer(offer_id):
    ok, err = dispatch_bot.decline_offer(db, _dispatch_models(), offer_id, session["user_id"])
    if not ok:
        return jsonify({"ok": False, "error": err}), 409
    return jsonify({"ok": True})




@app.route("/api/admin/live-locations")
@role_required("admin")
def api_admin_live_locations():
    """Where logged-in users last reported GPS (Myanmar-only app)."""
    users = User.query.filter(User.last_lat.isnot(None), User.last_lng.isnot(None)).limit(500).all()
    out = []
    for u in users:
        out.append({
            "id": u.id,
            "name": u.full_name,
            "role": u.role,
            "phone": u.phone,
            "lat": u.last_lat,
            "lng": u.last_lng,
            "at": u.last_location_at.isoformat() + "Z" if u.last_location_at else None,
            "place": u.location_text,
        })
    return jsonify({"ok": True, "users": out})

@app.route("/api/driver/location", methods=["POST"])
@role_required("taxi")
def api_driver_location():
    """Update rider last known GPS (used for 3-mile dispatch radius)."""
    data = request.get_json(force=True) or {}
    try:
        lat, lng = float(data["lat"]), float(data["lng"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"ok": False, "error": "Invalid coordinates"}), 400
    if not geo.is_in_myanmar(lat, lng):
        return jsonify({"ok": False, "error": "Location outside Myanmar"}), 403
    user = current_user()
    profile = user.taxi_profile
    if profile is None:
        profile = TaxiProfile(owner_id=user.id)
        db.session.add(profile)
    profile.last_lat = lat
    profile.last_lng = lng
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/order/<int:order_id>/track")
@login_required
def order_tracking(order_id):
    order = db.get_or_404(Order, order_id)
    allowed_tracker = (
        order.customer_id == session["user_id"]
        or (session.get("role") == "seller" and order.shop and order.shop.owner_id == session["user_id"])
        or session.get("role") == "admin"
        or order.driver_id == session.get("user_id")
    )
    if not allowed_tracker:
        return redirect(url_for("order_history"))
    shop = order.shop
    shop_loc = (shop.lat, shop.lng) if shop else (22.03455, 96.45875)
    if order.delivery_lat is not None and order.delivery_lng is not None:
        customer_loc = (order.delivery_lat, order.delivery_lng)
    else:
        customer_loc = (shop_loc[0] + 0.012, shop_loc[1] + 0.015)
    distance_km = geo.haversine_km(shop_loc[0], shop_loc[1], customer_loc[0], customer_loc[1]) if shop else None
    try:
        progress = const.STATUS_SEQUENCE.index(order.status) / (len(const.STATUS_SEQUENCE) - 1)
    except ValueError:
        progress = 0
    driver = order.driver
    taxi_profile = driver.taxi_profile if driver else None
    vehicle_raw = (taxi_profile.vehicle_type if taxi_profile and taxi_profile.vehicle_type else "") or ""
    vehicle_map = {
        "car": "Car",
        "motorbike": "Motorbike",
        "motorcycle": "Motorbike",
        "bicycle": "Bicycle",
        "bike": "Bicycle",
        "taxi": "Taxi",
    }
    vehicle_label = vehicle_map.get(vehicle_raw.lower(), vehicle_raw.title() if vehicle_raw else "Rider")
    if not driver:
        vehicle_label = "Awaiting assignment"
    # Keep denormalized rider fields in sync for older UI bits
    if driver:
        order.rider_name = driver.full_name or order.rider_name
        if driver.phone:
            order.rider_phone = driver.phone
    return render_template(
        "order_tracking.html",
        order=order,
        shop=shop,
        status_sequence=const.STATUS_SEQUENCE,
        shop_loc=shop_loc,
        customer_loc=customer_loc,
        progress=progress,
        distance_km=distance_km,
        driver=driver,
        taxi_profile=taxi_profile,
        vehicle_label=vehicle_label,
    )


@app.route("/orders")
@login_required
def order_history():
    orders = Order.query.filter_by(customer_id=session["user_id"]).order_by(Order.created_at.desc()).all()
    return render_template("order_history.html", orders=orders)




@app.route("/rewards")
@login_required
def rewards():
    user = current_user()
    # Simple loyalty from delivered order count
    delivered = Order.query.filter_by(customer_id=user.id, status="Delivered").count()
    points = delivered * 10
    tier = "Platinum" if points >= 2000 else ("Gold" if points >= 500 else "Silver")
    return render_template("rewards.html", points=points, tier=tier)


@app.route("/refer")
@login_required
def refer_friend():
    user = current_user()
    code = f"SHD{(user.id * 7919) % 1000000:06d}"
    link = request.url_root.rstrip("/") + "/register/customer?ref=" + code
    return render_template("refer_friend.html", code=code, link=link)


@app.route("/language")
@login_required
def language_region():
    return render_template("language_region.html")


@app.route("/notification-settings")
@login_required
def notification_settings():
    return render_template("notification_settings.html")

@app.route("/profile")
@login_required
def profile():
    return render_template("profile.html", user=current_user())


@app.route("/payment-methods", methods=["GET", "POST"])
@login_required
def payment_methods():
    user = current_user()
    if request.method == "POST":
        method = request.form.get("preferred_payment_method")
        if method in ("cod", "kbz", "wave"):
            user.preferred_payment_method = method
            db.session.commit()
            flash("Preferred payment method updated.", "success")
        return redirect(url_for("payment_methods"))
    return render_template("payment_methods.html", user=user)


@app.route("/coupons")
@login_required
def coupons():
    from datetime import datetime as _dt
    active = Coupon.query.filter_by(is_active=True).filter(
        db.or_(Coupon.expires_at.is_(None), Coupon.expires_at > _dt.utcnow())
    ).order_by(Coupon.created_at.desc()).all()
    return render_template("coupons.html", coupons=active)


@app.route("/wallet")
@login_required
def wallet():
    user = current_user()
    txns = WalletTransaction.query.filter_by(user_id=user.id).order_by(WalletTransaction.created_at.desc()).limit(50).all()
    return render_template("wallet.html", user=user, txns=txns)




@app.route("/api/avatar", methods=["POST"])
@login_required
def api_avatar_upload():
    """Accept cropped profile image (JPEG/PNG from client cropper)."""
    f = request.files.get("avatar") or request.files.get("file")
    if not f:
        return jsonify({"ok": False, "error": "No file"}), 400
    url = save_upload(f)
    if not url:
        return jsonify({"ok": False, "error": "Invalid image"}), 400
    user = current_user()
    user.avatar_url = url
    db.session.commit()
    return jsonify({"ok": True, "avatar_url": url})

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    user = current_user()
    if request.method == "POST":
        user.full_name = request.form.get("full_name", user.full_name).strip() or user.full_name
        email = request.form.get("email", "").strip()
        if email and email != user.email and User.query.filter_by(email=email).first():
            flash("That email is already in use.", "error")
            return redirect(url_for("settings"))
        user.email = email or user.email
        db.session.commit()
        session["user_name"] = user.full_name
        flash("Profile updated.", "success")
        return redirect(url_for("settings"))
    return render_template("settings.html", user=user)


@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    user = current_user()
    if request.method == "POST":
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        if user.password_hash and not user.check_password(current):
            flash("Current password is incorrect.", "error")
            return redirect(url_for("change_password"))
        valid, message = security.validate_password(new)
        if not valid:
            flash(message, "error")
            return redirect(url_for("change_password"))
        user.set_password(new)
        db.session.commit()
        flash("Password changed.", "success")
        return redirect(url_for("profile"))
    return render_template("change_password.html", has_password=bool(user.password_hash))


@app.route("/help")
def help_support():
    return render_template("help_support.html")


@app.route("/favorites")
@login_required
def favorites():
    favs = Favorite.query.filter_by(user_id=session["user_id"]).all()
    shop_ids = [f.target_id for f in favs if f.kind == "shop"]
    product_ids = [f.target_id for f in favs if f.kind == "product"]
    shops = Shop.query.filter(Shop.id.in_(shop_ids)).all() if shop_ids else []
    products = Product.query.filter(Product.id.in_(product_ids)).all() if product_ids else []
    return render_template("favorites.html", shops=shops, products=products)


@app.route("/api/notifications/unread-count")
@login_required
def api_notifications_unread():
    uid = session.get("user_id")
    c = AppNotification.query.filter_by(user_id=uid, is_read=False).count()
    return jsonify({"ok": True, "count": c})


@app.route("/notifications")
@login_required
def notifications():
    uid = session.get("user_id")
    rows = (AppNotification.query.filter_by(user_id=uid)
            .order_by(AppNotification.created_at.desc()).limit(100).all())
    # mark all as read when opening
    for n in rows:
        n.is_read = True
    db.session.commit()
    return render_template("notifications.html", notifications=rows)


# ---------------------------------------------------------------------------
# Chat (customer <-> seller), backed by Socket.IO (see sockets.py)
# ---------------------------------------------------------------------------

@app.route("/chats")
@login_required
def chat_list():
    user = current_user()
    if user.role == "admin":
        support = ensure_support_shop()
        # Distinct customers who messaged support
        from models import ChatMessage
        from sqlalchemy import func
        rows = (
            db.session.query(ChatMessage.customer_id, func.max(ChatMessage.id))
            .filter_by(shop_id=support.id)
            .group_by(ChatMessage.customer_id)
            .all()
        )
        tickets = []
        for cid, mid in rows:
            cu = db.session.get(User, cid)
            msg = db.session.get(ChatMessage, mid)
            if cu and msg:
                tickets.append({
                    "customer": cu,
                    "last_body": msg.body if not getattr(msg, "is_deleted", False) else "Deleted",
                    "last_at": msg.created_at.strftime("%H:%M") if msg.created_at else "",
                })
        tickets.sort(key=lambda x: x["last_at"] or "", reverse=True)
        return render_template("admin_support_chats.html", tickets=tickets, support=support)
    if user.role == "seller":
        shop = ensure_seller_shop(user)
        rooms = db.session.query(Order.customer_id).filter_by(shop_id=shop.id).distinct().all()
        customers = User.query.filter(User.id.in_([r[0] for r in rooms])).all() if rooms else []
        return render_template("seller_chat_list.html", shop=shop, customers=customers)

    # Customer: build conversation list from ChatMessage history + shops contacted via orders
    from models import ChatMessage
    from sqlalchemy import func

    # Rooms this customer has messages in
    room_rows = (
        db.session.query(ChatMessage.shop_id, func.max(ChatMessage.id))
        .filter_by(customer_id=user.id)
        .group_by(ChatMessage.shop_id)
        .all()
    )
    last_by_shop = {}
    for shop_id, msg_id in room_rows:
        msg = db.session.get(ChatMessage, msg_id)
        if msg:
            last_by_shop[shop_id] = msg

    # Also include shops from past orders even if no messages yet
    order_shop_ids = {
        row[0] for row in
        db.session.query(Order.shop_id).filter_by(customer_id=user.id).distinct().all()
    }
    all_shop_ids = set(last_by_shop.keys()) | order_shop_ids
    shops_map = {s.id: s for s in Shop.query.filter(Shop.id.in_(all_shop_ids)).all()} if all_shop_ids else {}

    conversations = []
    for sid in all_shop_ids:
        shop = shops_map.get(sid)
        if not shop:
            continue
        last = last_by_shop.get(sid)
        conversations.append({
            "shop": shop,
            "last_body": last.body if last else None,
            "last_at": last.created_at.strftime("%H:%M") if last else None,
            "sort_key": last.created_at if last else None,
        })
    conversations.sort(key=lambda c: c["sort_key"] or __import__("datetime").datetime.min, reverse=True)

    # Other shops the user can start chatting with (not yet in list)
    existing_ids = set(all_shop_ids)
    other_shops = (
        Shop.query.filter(~Shop.id.in_(existing_ids) if existing_ids else True)
        .order_by(Shop.name.asc())
        .limit(20)
        .all()
    )

    support = ensure_support_shop()
    from models import ChatMessage as _CM
    last_support = (
        _CM.query.filter_by(customer_id=user.id, shop_id=support.id)
        .order_by(_CM.created_at.desc())
        .first()
    )
    support_entry = {
        "shop": support,
        "last_body": (last_support.body if last_support and not getattr(last_support, "is_deleted", False) else None),
        "last_at": last_support.created_at.strftime("%H:%M") if last_support else None,
        "is_support": True,
    }
    # Remove support shop from normal lists if present
    conversations = [c for c in conversations if c["shop"].id != support.id]
    other_shops = [s for s in other_shops if s.id != support.id]
    return render_template(
        "customer_chat_list.html",
        conversations=conversations,
        other_shops=other_shops,
        support_entry=support_entry,
    )


@app.route("/admin/support")
@role_required("admin")
def admin_support_inbox():
    return chat_list()


@app.route("/chat/support/<int:customer_id>")
@role_required("admin")
def chat_support_customer(customer_id):
    support = ensure_support_shop()
    customer = db.get_or_404(User, customer_id)
    room = f"c{customer.id}-s{support.id}"
    return render_template(
        "chat.html",
        room=room,
        other_name=customer.full_name or "Customer",
        other_emoji="👤",
        role="admin",
    )


@app.route("/chat/shop/<int:shop_id>")

@login_required
def chat_with_shop(shop_id):
    shop = db.get_or_404(Shop, shop_id)
    user = current_user()
    if user.role == "seller":
        return redirect(url_for("chat_list"))
    room = f"c{user.id}-s{shop_id}"
    return render_template(
        "chat.html",
        room=room,
        other_name=shop.name,
        other_emoji=shop.emoji or "🏪",
        role=user.role,
    )


@app.route("/chat/customer/<int:customer_id>")
@role_required("seller")
def chat_with_customer(customer_id):
    shop = ensure_seller_shop(current_user())
    customer = db.get_or_404(User, customer_id)
    room = f"c{customer_id}-s{shop.id}"
    return render_template("chat.html", room=room, other_name=customer.full_name, other_emoji="🧑")


# ---------------------------------------------------------------------------
# Customer JSON API
# ---------------------------------------------------------------------------

@app.route("/api/cart/add", methods=["POST"])
def api_cart_add():
    data = request.get_json(force=True) or {}
    pid = str(data.get("product_id"))
    qty = int(data.get("qty", 1))
    product = db.session.get(Product, int(pid))
    if not product:
        return jsonify({"cart_count": cart_count(), "error": "Product not found."}), 404
    if product.status != "available":
        return jsonify({"cart_count": cart_count(), "error": "This item is sold out."}), 409
    cart = current_cart()
    cart[pid] = max(0, cart.get(pid, 0) + qty)
    if cart[pid] == 0:
        cart.pop(pid, None)
    session.modified = True
    return jsonify({"cart_count": cart_count()})


@app.route("/api/cart/set", methods=["POST"])
def api_cart_set():
    data = request.get_json(force=True) or {}
    pid = str(data.get("product_id"))
    qty = int(data.get("qty", 1))
    cart = current_cart()
    if qty <= 0:
        cart.pop(pid, None)
    else:
        cart[pid] = qty
    session.modified = True
    grouped = cart_line_items(cart)
    totals = cart_totals(grouped)
    return jsonify({"cart_count": cart_count(), "totals": totals})


@app.route("/api/favorite/toggle", methods=["POST"])
@login_required
def api_favorite_toggle():
    data = request.get_json(force=True) or {}
    kind = data.get("kind")
    target_id = int(data.get("id"))
    existing = Favorite.query.filter_by(user_id=session["user_id"], kind=kind, target_id=target_id).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        return jsonify({"active": False})
    db.session.add(Favorite(user_id=session["user_id"], kind=kind, target_id=target_id))
    db.session.commit()
    return jsonify({"active": True})


@app.route("/api/reviews", methods=["POST"])
@role_required("customer")
def api_create_review():
    data = request.get_json(force=True) or {}
    try:
        product_id, order_id = int(data.get("product_id")), int(data.get("order_id"))
        rating = int(data.get("rating"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Invalid review data."}), 400
    if rating < 1 or rating > 5:
        return jsonify({"ok": False, "error": "Rating must be between 1 and 5."}), 400
    order = db.session.get(Order, order_id)
    product = db.session.get(Product, product_id)
    if not order or not product or order.customer_id != session["user_id"]:
        return jsonify({"ok": False, "error": "You cannot review this order."}), 403
    if order.status != "Delivered":
        return jsonify({"ok": False, "error": "You can review after delivery is completed."}), 409
    if order.shop_id != product.shop_id or not any(item.product_id == product_id for item in order.items):
        return jsonify({"ok": False, "error": "This product was not part of that order."}), 403
    if ProductReview.query.filter_by(user_id=session["user_id"], product_id=product_id).first():
        return jsonify({"ok": False, "error": "You have already reviewed this product."}), 409
    review = ProductReview(user_id=session["user_id"], product_id=product_id, order_id=order_id,
                           rating=rating, body=(data.get("body") or "").strip()[:1000])
    db.session.add(review)
    product.rating = round(((product.rating or 0) * (product.reviews_count or 0) + rating) / ((product.reviews_count or 0) + 1), 2)
    product.reviews_count = (product.reviews_count or 0) + 1
    db.session.commit()
    return jsonify({"ok": True, "rating": product.rating, "reviews": product.reviews_count})


@app.route("/ai-assistant")
@login_required
def ai_assistant():
    return render_template("ai_assistant.html", voice_enabled=voice_ai.voice_ordering_enabled())


def _process_order_text(text):
    items = voice_ai.extract_order_items(text)
    all_products = Product.query.filter_by(status="available").all()
    matched, unmatched = voice_ai.match_products(items, all_products)

    cart = current_cart()
    added = []
    for m in matched:
        pid = str(m["product"].id)
        cart[pid] = cart.get(pid, 0) + m["qty"]
        added.append({"name": m["product"].name, "qty": m["qty"], "price": m["product"].price})
    session.modified = True

    reply_parts = []
    if added:
        reply_parts.append("Added " + ", ".join(f"{a['qty']}x {a['name']}" for a in added) + " to your cart.")
    if unmatched:
        reply_parts.append("Couldn't find a matching product for: " + ", ".join(unmatched) + ".")
    if not added and not unmatched:
        reply_parts.append("Sorry, I couldn't understand an order in that.")

    return {"added": added, "unmatched": unmatched, "reply": " ".join(reply_parts), "cart_count": cart_count()}


@app.route("/api/voice-order", methods=["POST"])
@login_required
def api_voice_order():
    audio_file = request.files.get("audio")
    if not audio_file:
        return jsonify({"ok": False, "error": "No audio received."}), 400

    try:
        transcript = voice_ai.transcribe_audio(audio_file.read(), audio_file.filename or "voice.webm")
    except RuntimeError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    result = _process_order_text(transcript)
    return jsonify({"ok": True, "transcript": transcript, **result})


@app.route("/api/voice-order/text", methods=["POST"])
@login_required
def api_voice_order_text():
    """Text-only version of the same pipeline - skips Whisper entirely,
    so it works even without an OPENAI_API_KEY configured."""
    data = request.get_json(force=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "Type something first."}), 400
    result = _process_order_text(text)
    return jsonify({"ok": True, "transcript": text, **result})


# ---------------------------------------------------------------------------
# Seller app
# ---------------------------------------------------------------------------

@app.route("/seller/dashboard")
@role_required("seller")
def seller_dashboard():
    shop = ensure_seller_shop(current_user())
    products = get_products_by_shop(shop.id)
    shop_orders = Order.query.filter_by(shop_id=shop.id).all()
    stats = {
        "today_sales": sum(o.total for o in shop_orders),
        "total_orders": len(shop_orders),
        "products": len(products),
        "revenue": sum(o.total for o in shop_orders),
        "customers": len({o.customer_id for o in shop_orders}) or 0,
    }
    return render_template("seller_dashboard.html", shop=shop, stats=stats)


@app.route("/seller/products")
@role_required("seller")
def seller_products():
    shop = ensure_seller_shop(current_user())
    return render_template("seller_products.html", shop=shop, products=get_products_by_shop(shop.id))


@app.route("/seller/products/add", methods=["GET", "POST"])
@role_required("seller")
def seller_add_product():
    shop = ensure_seller_shop(current_user())
    if request.method == "POST":
        image_url = save_upload(request.files.get("photo"))
        try:
            price = int(request.form.get("price") or 0)
            discount_pct = int(request.form.get("discount") or 0)
            stock = int(request.form.get("stock") or 0)
        except (TypeError, ValueError):
            price, discount_pct, stock = -1, -1, -1
        valid, error = commerce_bot.validate_product_input(request.form.get("name"), price, stock, discount_pct)
        if not valid:
            commerce_bot.log_event(db, session.get("user_id"), "invalid_product_create", error, request.remote_addr)
            db.session.commit()
            flash(error, "error")
            return redirect(url_for("seller_add_product"))
        old_price = round(price / (1 - discount_pct / 100)) if discount_pct else None
        db.session.add(Product(
            shop_id=shop.id, name=request.form.get("name", "Untitled product"),
            category=request.form.get("category", "Groceries"), image_url=image_url,
            price=price, old_price=old_price, discount_pct=discount_pct,
            description=request.form.get("description", ""), stock=stock,
            sku=request.form.get("sku") or None, free_delivery=bool(request.form.get("free_delivery")),
        ))
        db.session.commit()
        return redirect(url_for("seller_products"))
    return render_template("seller_add_product.html", shop=shop)


def _owned_product_or_404(product_id):
    product = db.get_or_404(Product, product_id)
    shop = ensure_seller_shop(current_user())
    if product.shop_id != shop.id:
        return None
    return product


@app.route("/seller/products/<int:product_id>/edit", methods=["GET", "POST"])
@role_required("seller")
def seller_edit_product(product_id):
    product = _owned_product_or_404(product_id)
    if not product:
        commerce_bot.log_event(db, session.get("user_id"), "product_ownership_denied", f"product_id={product_id}", request.remote_addr)
        db.session.commit()
        return redirect(url_for("seller_products"))
    if request.method == "POST":
        try:
            price = int(request.form.get("price") or product.price)
            discount = int(request.form.get("discount") or 0)
            stock = int(request.form.get("stock") or product.stock)
        except (TypeError, ValueError):
            price, discount, stock = -1, -1, -1
        name = request.form.get("name", product.name)
        valid, error = commerce_bot.validate_product_input(name, price, stock, discount)
        if not valid:
            commerce_bot.log_event(db, session.get("user_id"), "invalid_product_edit", error, request.remote_addr)
            db.session.commit()
            flash(error, "error")
            return redirect(url_for("seller_edit_product", product_id=product.id))
        product.name = name
        product.category = request.form.get("category", product.category)
        product.description = request.form.get("description", product.description)
        product.price, product.discount_pct, product.stock = price, discount, stock
        product.old_price = round(price / (1 - discount / 100)) if discount else None
        db.session.commit()
        return redirect(url_for("seller_products"))
    return render_template("seller_edit_product.html", product=product, shop=product.shop)


@app.route("/api/seller/products/<int:product_id>/delete", methods=["POST"])
@role_required("seller")
def api_seller_delete_product(product_id):
    product = _owned_product_or_404(product_id)
    if product:
        db.session.delete(product)
        db.session.commit()
    else:
        commerce_bot.log_event(db, session.get("user_id"), "product_delete_denied", f"product_id={product_id}", request.remote_addr)
        db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/seller/products/<int:product_id>/duplicate", methods=["POST"])
@role_required("seller")
def api_seller_duplicate_product(product_id):
    original = _owned_product_or_404(product_id)
    if original:
        db.session.add(Product(
            shop_id=original.shop_id, name=f"{original.name} (Copy)", category=original.category,
            description=original.description, price=original.price, old_price=original.old_price,
            discount_pct=original.discount_pct, stock=original.stock, emoji=original.emoji,
            image_url=original.image_url, free_delivery=original.free_delivery,
        ))
        db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/seller/products/<int:product_id>/toggle", methods=["POST"])
@role_required("seller")
def api_seller_toggle_product(product_id):
    product = _owned_product_or_404(product_id)
    if not product:
        return jsonify({"status": None}), 404
    product.status = "unavailable" if product.status == "available" else "available"
    db.session.commit()
    # Live-push to anyone currently browsing this shop/product (public info,
    # no auth needed to receive it - see sockets.py join_shop_public).
    socketio.emit("product_availability_changed", {
        "product_id": product.id, "status": product.status,
    }, room=f"shop-{product.shop_id}-public")
    return jsonify({"status": product.status})


@app.route("/seller/orders")
@role_required("seller")
def seller_orders():
    shop = ensure_seller_shop(current_user())
    orders = Order.query.filter_by(shop_id=shop.id).order_by(Order.created_at.desc()).all()
    drivers = (TaxiProfile.query.join(User, TaxiProfile.owner_id == User.id)
               .filter(TaxiProfile.is_available.is_(True), User.is_banned.is_(False))
               .order_by(User.full_name.asc()).all())
    return render_template("seller_orders.html", shop=shop, orders=orders, drivers=drivers)


@app.route("/api/seller/orders/<int:order_id>/assign-driver", methods=["POST"])
@role_required("seller")
def api_assign_driver(order_id):
    shop = ensure_seller_shop(current_user())
    order = db.get_or_404(Order, order_id)
    if order.shop_id != shop.id:
        commerce_bot.log_event(db, session.get("user_id"), "seller_order_access_denied", f"order_id={order_id}", request.remote_addr)
        db.session.commit()
        return jsonify({"error": "This order does not belong to your shop."}), 403
    if order.status != "Ready for Pickup" or not commerce_bot.valid_status_transition(order.status, "Rider Assigned", const.STATUS_SEQUENCE):
        commerce_bot.log_event(db, session.get("user_id"), "invalid_driver_assignment", f"order={order.id} status={order.status}", request.remote_addr)
        db.session.commit()
        return jsonify({"error": "The order must be ready before assigning a driver."}), 409
    driver_id = (request.get_json(force=True) or {}).get("driver_id")
    driver = db.session.get(User, driver_id) if driver_id else None
    if not driver or driver.role != "taxi" or not driver.taxi_profile or not driver.taxi_profile.is_available:
        return jsonify({"error": "Choose an available driver."}), 400
    order.driver_id = driver.id
    order.rider_name = driver.full_name
    order.rider_phone = driver.phone or ""
    order.status = "Rider Assigned"
    db.session.commit()
    payload = {"status": order.status, "order_id": order.id, "code": order.code,
               "shop_name": shop.name, "driver_name": driver.full_name}
    socketio.emit("order_status_update", payload, room=f"order-{order.id}")
    socketio.emit("order_status_update", payload, room=f"customer-{order.customer_id}")
    push_notification(order.customer_id, "Order update", f"{order.code}: {payload.get('status', order.status)}", kind="order", link=url_for("order_tracking", order_id=order.id))
    db.session.commit()
    socketio.emit("driver_order_assigned", payload, room=f"driver-{driver.id}")
    return jsonify({"ok": True, **payload})


@app.route("/api/seller/orders/<int:order_id>/status", methods=["POST"])
@role_required("seller")
def api_seller_update_status(order_id):
    shop = ensure_seller_shop(current_user())
    order = db.get_or_404(Order, order_id)
    if order.shop_id != shop.id:
        return jsonify({"status": None}), 403
    data = request.get_json(force=True) or {}
    new_status = data.get("status")
    allowed_statuses = set(const.STATUS_SEQUENCE) | {"Cancelled"}
    if new_status not in allowed_statuses:
        return jsonify({"status": order.status, "error": "Invalid order status."}), 400
    if new_status == "Rider Assigned":
        return jsonify({"status": order.status, "error": "Select an available driver to assign this order."}), 409
    if order.driver_id and new_status in ("Picked Up", "On the Way", "Delivered"):
        return jsonify({"status": order.status, "error": "The assigned driver must update this delivery."}), 403
    if new_status:
        if not commerce_bot.valid_status_transition(order.status, new_status, const.STATUS_SEQUENCE):
            commerce_bot.log_event(db, session.get("user_id"), "invalid_seller_status_transition", f"order={order.id} {order.status}->{new_status}", request.remote_addr)
            db.session.commit()
            return jsonify({"status": order.status, "error": "Order status must move to the next step."}), 409
        order.status = new_status
        db.session.commit()
        if new_status == "Ready for Pickup":
            telegram_bot.send_pickup_alert(order, shop)
        socketio.emit("order_status_update", {"status": order.status},
                       room=f"order-{order.id}")
        socketio.emit("order_status_update", {
            "status": order.status, "order_id": order.id, "code": order.code,
            "shop_name": shop.name,
        }, room=f"customer-{order.customer_id}")
    return jsonify({"status": order.status})


@app.route("/driver/orders")
@role_required("taxi")
def driver_orders():
    uid = session["user_id"]
    orders = Order.query.filter_by(driver_id=uid).order_by(Order.created_at.desc()).all()
    offers = (
        DeliveryOffer.query.filter_by(driver_id=uid, status="pending")
        .order_by(DeliveryOffer.created_at.desc())
        .limit(20)
        .all()
    )
    return render_template("driver_orders.html", orders=orders, offers=offers, driver=current_user())


@app.route("/api/driver/orders/<int:order_id>/status", methods=["POST"])
@role_required("taxi")
def api_driver_update_status(order_id):
    order = db.get_or_404(Order, order_id)
    if order.driver_id != session["user_id"]:
        commerce_bot.log_event(db, session.get("user_id"), "driver_order_access_denied", f"order_id={order_id}", request.remote_addr)
        db.session.commit()
        return jsonify({"error": "This order is not assigned to you."}), 403
    new_status = (request.get_json(force=True) or {}).get("status")
    if not commerce_bot.valid_status_transition(order.status, new_status, const.STATUS_SEQUENCE):
        commerce_bot.log_event(db, session.get("user_id"), "invalid_driver_status_transition", f"order={order.id} {order.status}->{new_status}", request.remote_addr)
        db.session.commit()
        return jsonify({"status": order.status, "error": "Use the next delivery step."}), 409
    order.status = new_status
    db.session.commit()
    payload = {"status": order.status, "order_id": order.id, "code": order.code,
               "driver_name": current_user().full_name}
    socketio.emit("order_status_update", payload, room=f"order-{order.id}")
    socketio.emit("order_status_update", payload, room=f"customer-{order.customer_id}")
    push_notification(order.customer_id, "Order update", f"{order.code}: {payload.get('status', order.status)}", kind="order", link=url_for("order_tracking", order_id=order.id))
    db.session.commit()
    return jsonify({"ok": True, **payload})


@app.route("/seller/sales")
@role_required("seller")
def seller_sales():
    shop = ensure_seller_shop(current_user())
    orders = Order.query.filter_by(shop_id=shop.id).all()
    products = get_products_by_shop(shop.id)
    best_sellers = sorted(products, key=lambda p: p.reviews_count, reverse=True)[:5]
    return render_template("seller_sales.html", shop=shop, orders=orders, best_sellers=best_sellers)



def ensure_support_shop():
    """Official Shadow Support inbox (customers <-> bot/admins)."""
    shop = Shop.query.filter_by(name="Shadow Support").first()
    if shop:
        return shop
    admin = User.query.filter_by(role="admin").first()
    if not admin:
        ensure_admin_accounts()
        admin = User.query.filter_by(role="admin").first()
    shop = Shop(
        owner_id=admin.id,
        name="Shadow Support",
        category="Support",
        description="In-app help desk. Bot answers when admins are offline.",
        emoji="🎧",
        is_open=True,
    )
    db.session.add(shop)
    db.session.commit()
    return shop


def ensure_admin_accounts():
    """Two fixed admin logins always exist, regardless of demo-data
    settings - admin accounts aren't self-registerable through the public
    UI, so they need to be created here instead.
    Login is Gmail-only (no password / no OTP code)."""
    def _admin_cred(i):
        u = os.environ.get(f"ADMIN{i}_USERNAME") or ("" if _is_prod else f"admin{i}local")
        p = os.environ.get(f"ADMIN{i}_PASSWORD") or ("" if _is_prod else f"LocalDev{i}23")
        e = os.environ.get(f"ADMIN{i}_EMAIL") or ""
        return (
            security.normalize_username(u),
            p,
            security.normalize_email(e),
            f"Admin {i}",
        )
    admin_specs = [_admin_cred(1), _admin_cred(2)]
    # Only Gmail is required for admin identity. Password is optional/legacy.
    for username, password, email, _ in admin_specs:
        if not email:
            if _is_prod:
                raise RuntimeError(
                    "Production requires ADMIN1_EMAIL and ADMIN2_EMAIL set to valid Gmail addresses."
                )
            continue
        if username:
            valid, message = security.validate_username(username)
            if not valid:
                raise RuntimeError(f"Invalid admin username configuration: {message}")
        valid, message, normalized_email = security.validate_email(email, required=True)
        if not valid or not normalized_email.endswith("@gmail.com"):
            raise RuntimeError("Set ADMIN1_EMAIL and ADMIN2_EMAIL to valid Gmail addresses in .env before startup.")
    for index, (username, password, email, name) in enumerate(admin_specs):
        user = User.query.filter_by(username=username).first()
        email_user = User.query.filter_by(email=email).first()
        if email_user:
            # The configured Gmail is the identity. If it was registered
            # earlier as a customer/seller, promote that same row instead of
            # inserting a duplicate email. Preserve any unrelated account
            # that happens to own the configured admin username.
            user = email_user
            if user.username != username:
                requested_owner = User.query.filter_by(username=username).first()
                if requested_owner and requested_owner.id != user.id:
                    base = username or f"admin{index}"
                    candidate = base[:44]
                    suffix = 2
                    while User.query.filter_by(username=candidate).first() and suffix < 10000:
                        tail = str(suffix)
                        candidate = f"{base[:50-len(tail)]}{tail}"
                        suffix += 1
                    user.username = candidate
                else:
                    user.username = username
        elif user:
            user.email = email
        if not user:
            legacy = User.query.filter_by(username=("a_dmin", "a_dmin2")[index]).first()
            if legacy:
                legacy.username = username
                user = legacy
        if not user:
            user = User(role="admin", full_name=name, username=username, phone_verified=True)
            db.session.add(user)
            user.set_password(password)
        user.role = "admin"
        user.full_name = name
        user.email = email
        # Do not overwrite a password changed in Admin Settings on every restart.
        if not user.password_hash:
            user.set_password(password)
    db.session.commit()


def active_ads():
    return Ad.query.filter_by(is_active=True).order_by(Ad.sort_order.asc(), Ad.created_at.desc()).all()


# ---------------------------------------------------------------------------
# Admin panel
# ---------------------------------------------------------------------------

@app.route("/admin")
@role_required("admin")
def admin_dashboard():
    orders = Order.query.order_by(Order.created_at.desc()).all()
    completed = [o for o in orders if o.status == "Delivered"]
    pending = [o for o in orders if o.status in ("Order Placed", "Seller Confirmed")]
    active_deliveries = [o for o in orders if o.status in ("Rider Assigned", "Picked Up", "On the Way")]
    stats = {
        "users": User.query.filter_by(role="customer").count(),
        "sellers": User.query.filter_by(role="seller").count(),
        "taxi_drivers": User.query.filter_by(role="taxi").count(),
        "shops": Shop.query.count(),
        "products": Product.query.count(),
        "orders": Order.query.count(),
        "ads": Ad.query.count(),
        "pending_orders": len(pending),
        "preparing_orders": Order.query.filter(Order.status.in_(["Preparing", "Ready for Pickup"])).count(),
        "active_deliveries": len(active_deliveries),
        "completed_orders": len(completed),
        "cancelled_orders": Order.query.filter_by(status="Cancelled").count(),
        "revenue": sum((o.total or 0) for o in completed),
    }
    status_counts = {status: sum(1 for o in orders if o.status == status) for status in const.STATUS_SEQUENCE + ["Cancelled"]}
    return render_template("admin_dashboard.html", stats=stats, status_counts=status_counts, recent_orders=orders[:8])


@app.route("/admin/orders")
@role_required("admin")
def admin_orders():
    status = request.args.get("status", "").strip()
    query = Order.query.order_by(Order.created_at.desc())
    if status:
        query = query.filter_by(status=status)
    available_drivers = (TaxiProfile.query.join(User, TaxiProfile.owner_id == User.id)
                         .filter(TaxiProfile.is_available.is_(True), User.is_banned.is_(False)).all())
    return render_template("admin_orders.html", orders=query.limit(300).all(), status_filter=status,
                           status_sequence=const.STATUS_SEQUENCE, available_drivers=available_drivers)


@app.route("/admin/orders/<int:order_id>/status", methods=["POST"])
@role_required("admin")
def admin_order_status(order_id):
    order = db.get_or_404(Order, order_id)
    new_status = (request.get_json(force=True) or {}).get("status")
    allowed = set(const.STATUS_SEQUENCE) | {"Cancelled"}
    if new_status not in allowed or not commerce_bot.valid_status_transition(order.status, new_status, const.STATUS_SEQUENCE):
        commerce_bot.log_event(db, session.get("user_id"), "invalid_admin_status_transition", f"order={order.id} {order.status}->{new_status}", request.remote_addr)
        db.session.commit()
        return jsonify({"error": "Invalid status transition."}), 409
    old_status = order.status
    order.status = new_status
    record_audit("change_status", "orders", order.id, f"{old_status} -> {new_status}")
    db.session.commit()
    payload = {"status": order.status, "order_id": order.id, "code": order.code}
    socketio.emit("order_status_update", payload, room=f"order-{order.id}")
    socketio.emit("order_status_update", payload, room=f"customer-{order.customer_id}")
    push_notification(order.customer_id, "Order update", f"{order.code}: {payload.get('status', order.status)}", kind="order", link=url_for("order_tracking", order_id=order.id))
    db.session.commit()
    return jsonify({"ok": True, **payload})


@app.route("/admin/orders/<int:order_id>/assign-driver", methods=["POST"])
@role_required("admin")
def admin_assign_driver(order_id):
    order = db.get_or_404(Order, order_id)
    driver_id = (request.get_json(force=True) or {}).get("driver_id")
    driver = db.session.get(User, driver_id) if driver_id else None
    if not driver or driver.role != "taxi" or not driver.taxi_profile or not driver.taxi_profile.is_available:
        return jsonify({"error": "Choose an available driver."}), 400
    if order.status not in ("Ready for Pickup", "Rider Assigned"):
        return jsonify({"error": "Order must be ready for pickup."}), 409
    order.driver_id = driver.id
    order.rider_name = driver.full_name
    order.rider_phone = driver.phone or ""
    order.status = "Rider Assigned"
    record_audit("assign_driver", "orders", order.id, f"driver_id={driver.id}")
    db.session.commit()
    payload = {"status": order.status, "order_id": order.id, "code": order.code, "driver_name": driver.full_name}
    socketio.emit("order_status_update", payload, room=f"order-{order.id}")
    socketio.emit("order_status_update", payload, room=f"customer-{order.customer_id}")
    push_notification(order.customer_id, "Order update", f"{order.code}: {payload.get('status', order.status)}", kind="order", link=url_for("order_tracking", order_id=order.id))
    db.session.commit()
    socketio.emit("driver_order_assigned", payload, room=f"driver-{driver.id}")
    return jsonify({"ok": True, **payload})


@app.route("/admin/vendors")
@role_required("admin")
def admin_vendors():
    shops = Shop.query.order_by(Shop.created_at.desc()).all()
    return render_template("admin_vendors.html", shops=shops)


@app.route("/admin/vendors/<int:shop_id>/toggle", methods=["POST"])
@role_required("admin")
def admin_vendor_toggle(shop_id):
    shop = db.get_or_404(Shop, shop_id)
    shop.is_open = not shop.is_open
    record_audit("toggle_vendor", "vendors", shop.id, f"is_open={shop.is_open}")
    db.session.commit()
    return jsonify({"ok": True, "is_open": shop.is_open})


@app.route("/admin/drivers")
@role_required("admin")
def admin_drivers():
    drivers = (TaxiProfile.query.join(User, TaxiProfile.owner_id == User.id)
               .order_by(TaxiProfile.created_at.desc()).all())
    driver_stats = {}
    for d in drivers:
        assigned = Order.query.filter_by(driver_id=d.owner.id).all()
        driver_stats[d.owner.id] = {
            "active": sum(1 for o in assigned if o.status in ("Rider Assigned", "Picked Up", "On the Way")),
            "completed": sum(1 for o in assigned if o.status == "Delivered"),
        }
    return render_template("admin_drivers.html", drivers=drivers, driver_stats=driver_stats)


@app.route("/admin/audit")
@role_required("admin")
def admin_audit():
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(300).all()
    return render_template("admin_audit.html", logs=logs)


@app.route("/admin/commerce-security")
@role_required("admin")
def admin_commerce_security():
    events = CommerceSecurityEvent.query.order_by(CommerceSecurityEvent.created_at.desc()).limit(300).all()
    return render_template("admin_commerce_security.html", events=events)


@app.route("/admin/telegram-reports", methods=["GET", "POST"])
@role_required("admin")
def admin_telegram_reports():
    if request.method == "POST":
        if telegram_reports.send_report_now(db, force=True):
            flash("Telegram report sent.", "success")
        else:
            flash("Telegram report was not sent. Check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID (or message the bot once).", "error")
        return redirect(url_for("admin_telegram_reports"))
    reports = TelegramReportLog.query.order_by(TelegramReportLog.sent_at.desc()).limit(100).all()
    try:
        interval_hours = max(1, int(env("TELEGRAM_REPORT_INTERVAL_HOURS", "6")))
    except (TypeError, ValueError):
        interval_hours = 6
    return render_template(
        "admin_telegram_reports.html", reports=reports,
        interval_hours=interval_hours,
        enabled=telegram_reports.reports_enabled(),
        bot_configured=telegram_bot.telegram_enabled(),
    )



@app.route("/admin/broadcast", methods=["GET", "POST"])
@role_required("admin")
def admin_broadcast():
    """Send an in-app notification to many users (KPay-style broadcast)."""
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()[:120]
        body = (request.form.get("body") or "").strip()[:2000]
        audience = (request.form.get("audience") or "all").strip()
        link = (request.form.get("link") or "").strip()[:255]
        if not title or not body:
            flash("Title and message are required.", "error")
            return redirect(url_for("admin_broadcast"))

        q = User.query.filter(User.role != "admin") if audience != "admins" else User.query.filter_by(role="admin")
        if audience in ("customer", "seller", "taxi"):
            q = User.query.filter_by(role=audience)
        elif audience == "all":
            q = User.query.filter(User.role.in_(("customer", "seller", "taxi")))
        users = q.all()
        kind = f"broadcast:{audience}"
        count = 0
        for u in users:
            push_notification(u.id, title, body, kind=kind, link=link, commit=False)
            count += 1
            try:
                socketio.emit(
                    "app_notification",
                    {"title": title, "body": body, "link": link},
                    room=f"user-{u.id}",
                )
            except Exception:
                pass
        db.session.commit()
        try:
            db.session.add(AuditLog(
                admin_id=session["user_id"],
                action="broadcast",
                module="notifications",
                details=f"audience={audience}; recipients={count}; title={title[:80]}",
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()
        flash(f"Broadcast sent to {count} user(s).", "success")
        return redirect(url_for("admin_broadcast"))

    # Recent broadcast-ish notifications grouped by title+minute (sample)
    recent_rows = (
        AppNotification.query.filter(AppNotification.kind.like("broadcast:%"))
        .order_by(AppNotification.created_at.desc())
        .limit(200)
        .all()
    )
    recent = []
    seen = set()
    for n in recent_rows:
        key = (n.title, n.kind, n.created_at.strftime("%Y%m%d%H%M") if n.created_at else "")
        if key in seen:
            continue
        seen.add(key)
        cnt = AppNotification.query.filter_by(title=n.title, kind=n.kind).count()
        recent.append(type("R", (), {
            "created_at": n.created_at,
            "title": n.title,
            "body": n.body or "",
            "kind": n.kind,
            "count": cnt,
        })())
        if len(recent) >= 15:
            break
    return render_template("admin_broadcast.html", recent=recent)


@app.route("/admin/settings", methods=["GET", "POST"])
@role_required("admin")
def admin_settings():
    if request.method == "POST":
        current = current_user()
        current_password = request.form.get("current_password", "")
        password = request.form.get("password", "")
        if not security.password_matches(current, current_password):
            flash("Current password is incorrect.", "error")
            return redirect(url_for("admin_settings"))
        valid, message = security.validate_password(password)
        if not valid:
            flash(message, "error")
        else:
            current.set_password(password)
            record_audit("change_password", "admin", current.id, "Admin changed own password")
            db.session.commit()
            flash("Your admin password has been updated.", "success")
            return redirect(url_for("admin_settings"))
    return render_template("admin_settings.html", admin=current_user())


@app.route("/admin/ads")
@role_required("admin")
def admin_ads():
    ads = Ad.query.order_by(Ad.sort_order.asc(), Ad.created_at.desc()).all()
    return render_template("admin_ads.html", ads=ads)


@app.route("/admin/ads/add", methods=["POST"])
@role_required("admin")
def admin_ads_add():
    image_url = save_upload(request.files.get("image"))
    if not image_url:
        flash("Please choose an image for the ad.", "error")
        return redirect(url_for("admin_ads"))
    ad = Ad(
        image_url=image_url, title=request.form.get("title") or None,
        link_url=request.form.get("link_url") or None,
        sort_order=int(request.form.get("sort_order") or 0),
        created_by=session.get("user_id"),
    )
    db.session.add(ad)
    db.session.commit()
    flash("Ad added.", "success")
    return redirect(url_for("admin_ads"))


@app.route("/admin/ads/<int:ad_id>/toggle", methods=["POST"])
@role_required("admin")
def admin_ads_toggle(ad_id):
    ad = db.get_or_404(Ad, ad_id)
    ad.is_active = not ad.is_active
    db.session.commit()
    return jsonify({"ok": True, "is_active": ad.is_active})


@app.route("/admin/ads/<int:ad_id>/delete", methods=["POST"])
@role_required("admin")
def admin_ads_delete(ad_id):
    ad = db.get_or_404(Ad, ad_id)
    db.session.delete(ad)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/admin/coupons")
@role_required("admin")
def admin_coupons():
    coupons = Coupon.query.order_by(Coupon.created_at.desc()).all()
    return render_template("admin_coupons.html", coupons=coupons)


@app.route("/admin/coupons/add", methods=["POST"])
@role_required("admin")
def admin_coupons_add():
    from datetime import datetime as _dt, timedelta as _td
    days = request.form.get("expires_in_days")
    expires_at = _dt.utcnow() + _td(days=int(days)) if days else None
    code = request.form.get("code", "").strip().upper()
    if not code or Coupon.query.filter_by(code=code).first():
        flash("Please choose a unique coupon code.", "error")
        return redirect(url_for("admin_coupons"))
    db.session.add(Coupon(
        code=code, discount_pct=int(request.form.get("discount_pct") or 10),
        min_order=int(request.form.get("min_order") or 0),
        expires_at=expires_at, created_by=session.get("user_id"),
    ))
    db.session.commit()
    flash("Coupon added.", "success")
    return redirect(url_for("admin_coupons"))


@app.route("/admin/coupons/<int:coupon_id>/toggle", methods=["POST"])
@role_required("admin")
def admin_coupons_toggle(coupon_id):
    c = db.get_or_404(Coupon, coupon_id)
    c.is_active = not c.is_active
    db.session.commit()
    return jsonify({"ok": True, "is_active": c.is_active})


@app.route("/admin/users/<int:user_id>/credit-wallet", methods=["POST"])
@role_required("admin")
def admin_credit_wallet(user_id):
    user = db.get_or_404(User, user_id)
    data = request.get_json(force=True) or {}
    try:
        amount = int(data.get("amount"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Invalid amount."}), 400
    if amount == 0:
        return jsonify({"ok": False, "error": "Amount cannot be zero."}), 400
    user.wallet_balance = (user.wallet_balance or 0) + amount
    db.session.add(WalletTransaction(
        user_id=user.id, amount=amount,
        reason=data.get("reason") or ("Admin credit" if amount > 0 else "Admin debit"),
        created_by=session.get("user_id"),
    ))
    record_audit("wallet_adjustment", "users", user.id, f"amount={amount}")
    db.session.commit()
    return jsonify({"ok": True, "new_balance": user.wallet_balance})


@app.route("/admin/users")
@role_required("admin")
def admin_users():
    role_filter = request.args.get("role", "")
    q = User.query.filter(User.role != "admin")
    if role_filter:
        q = q.filter_by(role=role_filter)
    users = q.order_by(User.created_at.desc()).limit(200).all()
    return render_template("admin_users.html", users=users, role_filter=role_filter)


@app.route("/admin/users/<int:user_id>/ban", methods=["POST"])
@role_required("admin")
def admin_user_ban(user_id):
    user = db.get_or_404(User, user_id)
    if user.role == "admin":
        return jsonify({"ok": False, "error": "Cannot ban an admin account."}), 400
    user.is_banned = not user.is_banned
    record_audit("ban_toggle", "users", user.id, f"is_banned={user.is_banned}")
    db.session.commit()
    return jsonify({"ok": True, "is_banned": user.is_banned})


@app.route("/admin/products")
@role_required("admin")
def admin_products():
    q = request.args.get("q", "").strip()
    query = Product.query
    if q:
        query = query.filter(Product.name.ilike(f"%{q}%"))
    products = query.order_by(Product.id.desc()).limit(200).all()
    return render_template("admin_products.html", products=products, q=q)


@app.route("/admin/products/<int:product_id>/delete", methods=["POST"])
@role_required("admin")
def admin_product_delete(product_id):
    product = db.get_or_404(Product, product_id)
    record_audit("delete_product", "products", product.id, product.name)
    db.session.delete(product)
    db.session.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------

with app.app_context():
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    db.create_all()
    ensure_delivery_schema()
    ensure_admin_accounts()
    import seed
    seed.seed_if_empty()
    telegram_reports.start_scheduler(app, db)


if __name__ == "__main__":
    # Local development only - gunicorn (see Procfile) runs the app in
    # production and never executes this block at all.
    debug_mode = env("FLASK_DEBUG", "true").lower() in ("1", "true", "yes")
    socketio.run(app, debug=debug_mode, host="0.0.0.0",
                 port=int(env("PORT", "5000")), allow_unsafe_werkzeug=True)
