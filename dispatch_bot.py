"""
Dispatch Bot — when a customer places an order, notify nearby available
riders (within ~3 miles of the shop). First rider to accept gets the job;
everyone else's offers are auto-cancelled.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import List, Optional, Tuple

# 3 miles ≈ 4.828 km
MAX_OFFER_RADIUS_KM = 4.83

BOT_NAME = "Dispatch Bot"


def haversine_km(lat1, lng1, lat2, lng2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return r * 2 * math.asin(math.sqrt(min(1.0, a)))


def driver_coords(user, profile) -> Optional[Tuple[float, float]]:
    """Best known position for a rider (live pin > profile pin > address)."""
    if profile is not None:
        lat = getattr(profile, "last_lat", None)
        lng = getattr(profile, "last_lng", None)
        if lat is not None and lng is not None:
            return float(lat), float(lng)
    if user is not None:
        lat = getattr(user, "address_lat", None)
        lng = getattr(user, "address_lng", None)
        if lat is not None and lng is not None:
            return float(lat), float(lng)
    return None


def find_nearby_drivers(db, User, TaxiProfile, shop_lat: float, shop_lng: float, radius_km: float = MAX_OFFER_RADIUS_KM):
    """Return list of dicts: {user, profile, distance_km} sorted nearest first."""
    profiles = (
        TaxiProfile.query.filter_by(is_available=True)
        .all()
    )
    found = []
    for prof in profiles:
        user = db.session.get(User, prof.owner_id)
        if not user or user.role != "taxi" or getattr(user, "is_banned", False):
            continue
        coords = driver_coords(user, prof)
        if not coords:
            continue
        d = haversine_km(shop_lat, shop_lng, coords[0], coords[1])
        if d <= radius_km:
            found.append({"user": user, "profile": prof, "distance_km": round(d, 2)})
    found.sort(key=lambda x: x["distance_km"])
    return found


def build_offer_message(order, shop, distance_shop_to_customer_km: float, rider_to_shop_km: float) -> str:
    shop_name = shop.name if shop else "Shop"
    dest = (order.address or "Customer location")[:120]
    return (
        f"🚚 {BOT_NAME}\n"
        f"New delivery request\n"
        f"From: {shop_name}\n"
        f"To: {dest}\n"
        f"You → shop: ~{rider_to_shop_km:.1f} km\n"
        f"Shop → customer: ~{distance_shop_to_customer_km:.1f} km\n"
        f"Order {order.code} · {order.total:,.0f} Ks\n"
        f"Accept to take this delivery?"
    )


def create_offers_for_order(db, models, order, shop) -> List:
    """
    Create pending DeliveryOffer rows for nearby riders.
    Returns list of (offer, driver_user, distance_km).
    """
    Order = models["Order"]
    User = models["User"]
    TaxiProfile = models["TaxiProfile"]
    DeliveryOffer = models["DeliveryOffer"]

    if not shop or shop.lat is None or shop.lng is None:
        return []
    if order.driver_id:
        return []  # already assigned

    # Cancel any previous pending offers for this order
    DeliveryOffer.query.filter_by(order_id=order.id, status="pending").update(
        {"status": "cancelled", "resolved_at": datetime.utcnow()}
    )

    cust_lat = order.delivery_lat if order.delivery_lat is not None else shop.lat
    cust_lng = order.delivery_lng if order.delivery_lng is not None else shop.lng
    shop_to_cust = haversine_km(shop.lat, shop.lng, cust_lat, cust_lng)

    nearby = find_nearby_drivers(db, User, TaxiProfile, shop.lat, shop.lng)
    created = []
    for item in nearby:
        user = item["user"]
        offer = DeliveryOffer(
            order_id=order.id,
            driver_id=user.id,
            status="pending",
            distance_km=item["distance_km"],
            shop_to_customer_km=round(shop_to_cust, 2),
            message=build_offer_message(order, shop, shop_to_cust, item["distance_km"]),
        )
        db.session.add(offer)
        created.append((offer, user, item["distance_km"]))
    return created


def accept_offer(db, models, offer_id: int, driver_id: int):
    """
    Driver accepts. Assign order, cancel sibling offers.
    Returns (ok, error_message, order).
    """
    DeliveryOffer = models["DeliveryOffer"]
    Order = models["Order"]
    User = models["User"]

    offer = db.session.get(DeliveryOffer, offer_id)
    if not offer or offer.driver_id != driver_id:
        return False, "Offer not found.", None, []
    if offer.status != "pending":
        return False, "This offer is no longer available.", None, []

    order = db.session.get(Order, offer.order_id)
    if not order:
        return False, "Order not found.", None, []
    if order.driver_id and order.driver_id != driver_id:
        return False, "Another rider already took this order.", None, []
    if order.status in ("Delivered", "Cancelled"):
        return False, "Order is already closed.", None, []

    driver = db.session.get(User, driver_id)
    if not driver:
        return False, "Driver not found.", None, []

    # Assign
    order.driver_id = driver.id
    order.rider_name = driver.full_name or "Rider"
    order.rider_phone = driver.phone or ""
    if order.status in ("Order Placed", "Seller Confirmed", "Preparing", "Ready for Pickup"):
        order.status = "Rider Assigned"

    offer.status = "accepted"
    offer.resolved_at = datetime.utcnow()

    # Auto-cancel / "delete" other riders' offers
    others = DeliveryOffer.query.filter(
        DeliveryOffer.order_id == order.id,
        DeliveryOffer.id != offer.id,
        DeliveryOffer.status == "pending",
    ).all()
    cancelled_driver_ids = []
    for o in others:
        o.status = "cancelled"
        o.resolved_at = datetime.utcnow()
        cancelled_driver_ids.append(o.driver_id)

    db.session.commit()
    return True, "", order, cancelled_driver_ids


def decline_offer(db, models, offer_id: int, driver_id: int):
    DeliveryOffer = models["DeliveryOffer"]
    offer = db.session.get(DeliveryOffer, offer_id)
    if not offer or offer.driver_id != driver_id:
        return False, "Offer not found."
    if offer.status != "pending":
        return False, "Already closed."
    offer.status = "declined"
    offer.resolved_at = datetime.utcnow()
    db.session.commit()
    return True, ""
