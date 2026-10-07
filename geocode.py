"""
Reverse geocoding: turns (lat, lng) into a human-readable place name like
"Pyin Oo Lwin, Mandalay Region, Myanmar".

Uses OpenStreetMap's free Nominatim service - no API key, no billing
account, unlike Google's Geocoding API. Its usage policy
(https://operations.osmfoundation.org/policies/nominatim/) asks for:
  - a real User-Agent identifying your app (set below)
  - no more than ~1 request/second
which is exactly what a "look up the place name once when the customer
turns on location" feature needs - we're not geocoding in a tight loop.

If the request fails (offline, Nominatim down, rate-limited) we just
fall back to a generic label instead of raising - location still works
for distance/fee calculations either way, this is purely for display.
"""

import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "ShadowMarketplaceApp/1.0 (contact: set-a-real-contact-in-geocode.py)"


def reverse_geocode(lat: float, lng: float) -> str:
    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={"format": "jsonv2", "lat": lat, "lon": lng, "zoom": 14, "addressdetails": 1},
            headers={"User-Agent": USER_AGENT},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        addr = data.get("address", {})

        # Prefer the most specific place name Nominatim gives us, then
        # fall back progressively to broader ones.
        place = (
            addr.get("town") or addr.get("city") or addr.get("village")
            or addr.get("suburb") or addr.get("county") or addr.get("state_district")
        )
        state = addr.get("state")
        country = addr.get("country")

        parts = [p for p in (place, state, country) if p]
        if parts:
            return ", ".join(dict.fromkeys(parts))  # dict.fromkeys dedupes while keeping order
        return data.get("display_name", f"{lat:.4f}, {lng:.4f}")
    except Exception:
        return f"Near {lat:.4f}, {lng:.4f}"


def reverse_geocode_street(lat: float, lng: float) -> str:
    """Turns a dropped pin into a street-level address like
    "No. 12, Bo Aung Kyaw Street, Botahtaung" - matching the "House
    number, Road, Ward/Quarter" format asked for. Falls back to
    progressively broader parts as they're missing, and finally to the
    coarse `reverse_geocode()` place name if nothing street-level came
    back at all (e.g. a pin dropped in the middle of a field)."""
    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={"format": "jsonv2", "lat": lat, "lon": lng, "zoom": 18, "addressdetails": 1},
            headers={"User-Agent": USER_AGENT},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        addr = data.get("address", {})

        house_number = addr.get("house_number")
        road = addr.get("road") or addr.get("pedestrian") or addr.get("footway")
        quarter = (
            addr.get("suburb") or addr.get("quarter") or addr.get("neighbourhood")
            or addr.get("city_district")
        )
        town = addr.get("town") or addr.get("city") or addr.get("village")

        pieces = []
        if house_number and road:
            pieces.append(f"No. {house_number}, {road}")
        elif road:
            pieces.append(road)
        if quarter:
            pieces.append(quarter)
        if town and town != quarter:
            pieces.append(town)

        if pieces:
            return ", ".join(pieces)
        return data.get("display_name") or reverse_geocode(lat, lng)
    except Exception:
        return reverse_geocode(lat, lng)
