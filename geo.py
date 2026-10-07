"""
Location helpers: distance calculation and distance-based delivery fees.

Nothing here calls Google Maps - it's plain latitude/longitude math
(the haversine formula), so it works with whatever coordinates the
browser's Geolocation API hands us, no API key or billing account
needed. If you later want turn-by-turn routing/ETAs instead of
straight-line distance, that's the point where a paid routing API
(Google Directions, Mapbox, OSRM) would slot in - see README.
"""

import math

from flask import session

# Delivery is free platform-wide right now (per your call - shops/promos
# throughout the app already say "Free Delivery", so checkout should
# actually charge nothing rather than quietly adding a distance-based
# fee). Flip this to False whenever you're ready to start charging for
# delivery - the real distance-based calculation below is left intact
# so switching back is a one-line change.
FREE_DELIVERY_MODE = True

# Ks per km on top of a flat base fee, per delivery method - only used
# when FREE_DELIVERY_MODE is False. Tune these to match your real
# courier costs.
DELIVERY_FEE_RULES = {
    "standard": {"base": 500, "per_km": 250},
    "express": {"base": 1000, "per_km": 400},
    "scheduled": {"base": 400, "per_km": 200},
    "pickup": {"base": 0, "per_km": 0},
}


def haversine_km(lat1, lng1, lat2, lng2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def customer_location():
    """The customer's current browsing location (used for sorting nearby
    shops) - the coarse GPS/manual-pin fix from the location gate."""
    lat, lng = session.get("lat"), session.get("lng")
    if lat is None or lng is None:
        return None
    return (lat, lng)


def delivery_location():
    """Where an order should actually be delivered to - the customer's
    confirmed address pin (see /address) when they've set one, since
    that's the real destination for fee calculation and rider
    navigation. Falls back to the coarse browsing location (e.g. a
    customer who hasn't set a specific delivery pin yet), then to
    nothing at all."""
    user_id = session.get("user_id")
    if user_id:
        from extensions import db  # deferred imports - avoid a circular import at module load
        from models import User
        user = db.session.get(User, user_id)
        if user and user.address_lat is not None and user.address_lng is not None:
            return (user.address_lat, user.address_lng)
    return customer_location()


def distance_to_shop(shop):
    loc = delivery_location()
    if not loc or not shop:
        return None
    return haversine_km(loc[0], loc[1], shop.lat, shop.lng)


def attach_live_distance(shops):
    """Sets a transient `.live_distance_km` attribute on each Shop
    instance for display/sorting - computed from the customer's stored
    GPS location when we have one, falling back to the shop's seeded
    `distance_km` otherwise. Not persisted (not a mapped column)."""
    loc = customer_location()
    for s in shops:
        if loc:
            s.live_distance_km = round(haversine_km(loc[0], loc[1], s.lat, s.lng), 1)
        else:
            s.live_distance_km = s.distance_km
    return shops


def calc_delivery_fee(shop, delivery_method):
    if FREE_DELIVERY_MODE:
        return 0
    rules = DELIVERY_FEE_RULES.get(delivery_method, DELIVERY_FEE_RULES["standard"])
    if delivery_method == "pickup" or not shop:
        return rules["base"]
    distance = distance_to_shop(shop)
    if distance is None:
        distance = shop.distance_km or 2.0  # sensible fallback if location isn't known yet
    return round(rules["base"] + rules["per_km"] * distance)


# Approximate bounding box for Myanmar (with small padding).
MYANMAR_LAT_MIN, MYANMAR_LAT_MAX = 9.4, 28.6
MYANMAR_LNG_MIN, MYANMAR_LNG_MAX = 92.1, 101.3


def is_in_myanmar(lat, lng) -> bool:
    try:
        lat = float(lat)
        lng = float(lng)
    except (TypeError, ValueError):
        return False
    return (
        MYANMAR_LAT_MIN <= lat <= MYANMAR_LAT_MAX
        and MYANMAR_LNG_MIN <= lng <= MYANMAR_LNG_MAX
    )


def myanmar_location_error(lat, lng):
    if is_in_myanmar(lat, lng):
        return None
    return (
        "Shadow is only available inside Myanmar. "
        "Your location appears to be outside the country "
        "(VPN or fake GPS). Turn off VPN / location spoofing "
        "and set your real Myanmar location."
    )
