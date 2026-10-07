"""
Real, persistent data model (SQLite via SQLAlchemy).

This replaces the old in-memory data_store.py for anything that must
survive a server restart or be shared correctly across many users at
once: accounts, shops, products, orders, chat messages, favorites and
OTP codes.

Security notes (see README for the full checklist):
- Passwords are never stored in plain text - only a salted hash
  (Werkzeug's generate_password_hash/check_password_hash, which uses
  PBKDF2-SHA256 by default).
- OTP codes are stored hashed too, expire quickly, are single-use, and
  have a limited number of verification attempts (see otp.py).
- All queries go through SQLAlchemy's ORM (parameterised under the
  hood), so normal use of this module is not vulnerable to SQL
  injection - just never build raw SQL by string-concatenating user
  input.
"""

from datetime import datetime

from werkzeug.security import generate_password_hash, check_password_hash

from extensions import db


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(10), nullable=False, default="customer")  # customer | seller | taxi | admin
    full_name = db.Column(db.String(120), nullable=False, default="Shadow User")
    username = db.Column(db.String(50), unique=True, nullable=True)  # admin accounts log in with this, not a phone
    phone = db.Column(db.String(30), unique=True, nullable=True)
    email = db.Column(db.String(120), unique=True, nullable=True)
    password_hash = db.Column(db.String(255), nullable=True)  # null for Google-only accounts
    google_sub = db.Column(db.String(255), unique=True, nullable=True)
    avatar_url = db.Column(db.String(255))
    location_text = db.Column(db.String(255), default="Pyin Oo Lwin, Mandalay Region, Myanmar")
    last_lat = db.Column(db.Float)  # last live GPS from device
    last_lng = db.Column(db.Float)
    last_location_at = db.Column(db.DateTime)
    address_text = db.Column(db.String(255))  # confirmed delivery address (house/road/quarter)
    address_lat = db.Column(db.Float)
    address_lng = db.Column(db.Float)
    phone_verified = db.Column(db.Boolean, default=False)
    is_banned = db.Column(db.Boolean, default=False)
    banned_until = db.Column(db.DateTime, nullable=True)
    security_violations = db.Column(db.Integer, nullable=False, default=0)
    failed_login_attempts = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)
    last_login_at = db.Column(db.DateTime, nullable=True)
    preferred_payment_method = db.Column(db.String(20), default="cod")
    wallet_balance = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    shop = db.relationship("Shop", backref="owner", uselist=False)

    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, raw_password)


class Shop(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(80), default="Groceries")
    description = db.Column(db.Text, default="")
    logo_url = db.Column(db.String(255))
    cover_url = db.Column(db.String(255))
    emoji = db.Column(db.String(10), default="🏪")
    lat = db.Column(db.Float, default=22.03455)
    lng = db.Column(db.Float, default=96.45875)
    is_open = db.Column(db.Boolean, default=True)
    is_verified = db.Column(db.Boolean, default=False)
    free_delivery = db.Column(db.Boolean, default=False)
    delivery_min = db.Column(db.Integer, default=30)
    distance_km = db.Column(db.Float, default=1.0)
    rating = db.Column(db.Float, default=0.0)
    rating_count = db.Column(db.Integer, default=0)
    is_restaurant = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    products = db.relationship("Product", backref="shop", cascade="all, delete-orphan")

    def to_public_dict(self):
        return {
            "id": self.id, "name": self.name, "category": self.category, "emoji": self.emoji,
            "rating": self.rating, "reviews": self.rating_count, "distance_km": self.distance_km,
            "delivery_min": self.delivery_min, "free_delivery": self.free_delivery,
            "open": self.is_open, "verified": self.is_verified, "description": self.description,
            "logo_url": self.logo_url, "cover_url": self.cover_url,
            "lat": self.lat, "lng": self.lng,
        }


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    shop_id = db.Column(db.Integer, db.ForeignKey("shop.id"), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    category = db.Column(db.String(80), default="Groceries")
    description = db.Column(db.Text, default="")
    # Price is set entirely by the seller (per the request: "shop owners can
    # change the price however they like") - no platform-side price logic.
    price = db.Column(db.Integer, nullable=False, default=0)
    old_price = db.Column(db.Integer, nullable=True)
    discount_pct = db.Column(db.Integer, default=0)
    stock = db.Column(db.Integer, default=0)
    sku = db.Column(db.String(40))
    emoji = db.Column(db.String(10), default="📦")
    image_url = db.Column(db.String(255))
    status = db.Column(db.String(20), default="available")  # available | unavailable
    is_food = db.Column(db.Boolean, default=False)
    free_delivery = db.Column(db.Boolean, default=False)
    rating = db.Column(db.Float, default=0.0)
    reviews_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_public_dict(self):
        return {
            "id": self.id, "shop_id": self.shop_id, "name": self.name, "category": self.category,
            "description": self.description, "price": self.price, "old_price": self.old_price,
            "discount_pct": self.discount_pct, "stock": self.stock, "sku": self.sku,
            "emoji": self.emoji, "image_url": self.image_url, "status": self.status,
            "is_food": self.is_food, "free_delivery": self.free_delivery,
            "rating": self.rating, "reviews": self.reviews_count,
        }


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    shop_id = db.Column(db.Integer, db.ForeignKey("shop.id"), nullable=False)
    driver_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    subtotal = db.Column(db.Integer, default=0)
    delivery_fee = db.Column(db.Integer, default=0)
    discount = db.Column(db.Integer, default=0)
    service_fee = db.Column(db.Integer, default=0)
    total = db.Column(db.Integer, default=0)
    status = db.Column(db.String(30), default="Order Placed")
    delivery_method = db.Column(db.String(20), default="standard")
    payment_method = db.Column(db.String(20), default="cod")
    payment_screenshot_url = db.Column(db.String(255))
    address = db.Column(db.String(255))
    contact_phone = db.Column(db.String(30))
    delivery_lat = db.Column(db.Float)
    delivery_lng = db.Column(db.Float)
    rider_name = db.Column(db.String(80), default="Ko Ko Aung")
    rider_phone = db.Column(db.String(30), default="09 123 456 789")
    rider_rating = db.Column(db.Float, default=4.8)
    eta_min = db.Column(db.Integer, default=30)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    customer = db.relationship("User", foreign_keys=[customer_id])
    driver = db.relationship("User", foreign_keys=[driver_id])
    shop = db.relationship("Shop")
    items = db.relationship("OrderItem", backref="order", cascade="all, delete-orphan")


class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    product_name = db.Column(db.String(150))
    qty = db.Column(db.Integer, default=1)
    price_at_purchase = db.Column(db.Integer, default=0)

    product = db.relationship("Product")


class Address(db.Model):
    """One saved address in a customer's address book (Home/Work/Other,
    Amazon/Grab-style) - separate from User.address_* which tracks
    whichever one is currently active for delivery/distance calculations."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    label = db.Column(db.String(30), default="Home")
    address_text = db.Column(db.String(255), nullable=False)
    lat = db.Column(db.Float, nullable=False)
    lng = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Coupon(db.Model):
    """Admin-issued discount code. Kept deliberately simple: a flat
    percentage off, an optional minimum order, and an optional expiry -
    no per-shop/per-category targeting yet (see README-style scope note
    if that's needed later)."""
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), unique=True, nullable=False)
    discount_pct = db.Column(db.Integer, nullable=False)
    min_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class WalletTransaction(db.Model):
    """A single credit/debit line in a customer's wallet ledger - always
    keep this alongside User.wallet_balance so the balance is auditable,
    not just a bare number admins can silently change."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    amount = db.Column(db.Integer, nullable=False)  # positive = credit, negative = debit
    reason = db.Column(db.String(200), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"))  # admin who issued it, if applicable
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Ad(db.Model):
    """A banner shown in the home-page ad carousel. Admin-managed only -
    sellers/customers never create these."""
    id = db.Column(db.Integer, primary_key=True)
    image_url = db.Column(db.String(255), nullable=False)
    title = db.Column(db.String(120))
    link_url = db.Column(db.String(255))  # where tapping the ad goes, optional
    is_active = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer, default=0)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class TaxiProfile(db.Model):
    """A driver's public contact card - phone (via the linked User) and a
    photo of their car or motorbike. Deliberately simple: this is a
    browsable directory a customer can call from, not a dispatch/matching
    system with live GPS (see README for that scope note)."""
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, unique=True)
    vehicle_type = db.Column(db.String(20), default="car")  # car | motorbike
    vehicle_photo_url = db.Column(db.String(255))
    is_available = db.Column(db.Boolean, default=True)
    last_lat = db.Column(db.Float)  # last known rider GPS
    last_lng = db.Column(db.Float)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    owner = db.relationship("User", backref=db.backref("taxi_profile", uselist=False))


class DeliveryOffer(db.Model):
    """Dispatch Bot offer sent to a nearby rider for one order."""
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False, index=True)
    driver_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    status = db.Column(db.String(20), default="pending")  # pending | accepted | declined | cancelled
    distance_km = db.Column(db.Float)  # rider → shop
    shop_to_customer_km = db.Column(db.Float)
    message = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    resolved_at = db.Column(db.DateTime)

    order = db.relationship("Order", backref=db.backref("delivery_offers", lazy="dynamic"))
    driver = db.relationship("User", foreign_keys=[driver_id])




class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    action = db.Column(db.String(80), nullable=False)
    module = db.Column(db.String(40), nullable=False)
    record_id = db.Column(db.String(40))
    details = db.Column(db.Text)
    ip_address = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    admin = db.relationship("User", foreign_keys=[admin_id])


class Favorite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    kind = db.Column(db.String(10), nullable=False)  # shop | product
    target_id = db.Column(db.Integer, nullable=False)

    __table_args__ = (db.UniqueConstraint("user_id", "kind", "target_id", name="uq_favorite"),)


class ProductReview(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    body = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint("user_id", "product_id", name="uq_product_review_user_product"),)


class CommerceSecurityEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    kind = db.Column(db.String(80), nullable=False)
    details = db.Column(db.Text)
    ip_address = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class TelegramReportLog(db.Model):
    """Audit trail for scheduled platform reports sent to the owner's Telegram."""
    id = db.Column(db.Integer, primary_key=True)
    report_type = db.Column(db.String(40), nullable=False, default="platform_summary")
    sent_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    window_hours = db.Column(db.Integer, nullable=False, default=6)
    recipient = db.Column(db.String(120))
    status = db.Column(db.String(20), nullable=False, default="sent")
    error = db.Column(db.Text)


class ChatMessage(db.Model):
    """One row per chat message, in a 'room' shared by a customer and a shop.

    Room naming: f"c{customer_id}-s{shop_id}" so the same two parties
    always land in the same thread regardless of which order prompted it.
    """
    id = db.Column(db.Integer, primary_key=True)
    room = db.Column(db.String(64), index=True, nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    shop_id = db.Column(db.Integer, db.ForeignKey("shop.id"), nullable=False)
    sender_role = db.Column(db.String(10), nullable=False)  # customer | seller
    sender_name = db.Column(db.String(120))
    body = db.Column(db.Text, nullable=False)
    msg_type = db.Column(db.String(16), default="text")  # text | voice | image
    reply_to_id = db.Column(db.Integer, nullable=True)
    is_read = db.Column(db.Boolean, default=False)
    is_edited = db.Column(db.Boolean, default=False)
    is_deleted = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    read_at = db.Column(db.DateTime, nullable=True)


class OTPCode(db.Model):
    """Short-lived, single-use verification codes for phone login/signup.

    Security properties:
    - Only a hash of the code is stored (never the plaintext code).
    - Each code expires after a few minutes (see otp.py OTP_TTL_SECONDS).
    - `consumed` flips to True the moment it's used - it can never be
      replayed even if someone else somehow saw the hash.
    - `attempts` caps how many wrong guesses are allowed before the code
      is locked out, to stop brute-forcing a 6-digit code.
    """
    id = db.Column(db.Integer, primary_key=True)
    # Stores both phone identifiers and email:<address> identifiers.
    phone = db.Column(db.String(160), index=True, nullable=False)
    code_hash = db.Column(db.String(255), nullable=False)
    purpose = db.Column(db.String(20), default="login")
    expires_at = db.Column(db.DateTime, nullable=False)
    attempts = db.Column(db.Integer, default=0)
    consumed = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class AppNotification(db.Model):
    """Real in-app notifications for the top-right bell."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    title = db.Column(db.String(120), nullable=False)
    body = db.Column(db.Text, default="")
    kind = db.Column(db.String(40), default="general")  # order | chat | system
    link = db.Column(db.String(255), default="")
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
