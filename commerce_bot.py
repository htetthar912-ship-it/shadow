"""Server-side Shop/Seller/Product/Order security guard."""
from datetime import datetime


def log_event(db, actor_id, kind, details, ip=None):
    from models import CommerceSecurityEvent
    event = CommerceSecurityEvent(actor_id=actor_id, kind=kind, details=str(details)[:1000], ip_address=ip)
    db.session.add(event)
    return event


def seller_owns_shop(user, shop):
    return bool(user and shop and shop.owner_id == user.id and user.role == "seller")


def seller_owns_product(user, product):
    return bool(user and product and user.role == "seller" and user.shop and product.shop_id == user.shop.id)


def validate_product_input(name, price, stock, discount):
    if not (name or "").strip() or len(name.strip()) > 150: return False, "Product name is invalid."
    if price < 0 or price > 100_000_000: return False, "Product price is invalid."
    if stock < 0 or stock > 10_000_000: return False, "Product stock is invalid."
    if discount < 0 or discount > 100: return False, "Discount must be between 0 and 100."
    return True, None


def validate_cart(grouped):
    if not grouped:
        return False, "Your cart is empty."
    for group in grouped:
        if not group.get("shop") or not group.get("lines"):
            return False, "The cart contains an invalid shop or product."
        for line in group["lines"]:
            product, qty = line["product"], line["qty"]
            if not isinstance(qty, int) or qty < 1 or qty > 999 or product.status != "available" or qty > (product.stock or 0):
                return False, f"{product.name} is unavailable or the requested quantity is too high."
    return True, None


def valid_status_transition(current, new, sequence):
    if current in ("Delivered", "Cancelled"):
        return False
    if new == "Cancelled":
        return True
    try: return sequence[sequence.index(current) + 1] == new
    except (ValueError, IndexError): return False
