"""Static app configuration - categories, delivery/payment options, the
order-status sequence, and the demo notification feed. Unlike models.py
this isn't user data, so plain Python constants are fine here."""

CATEGORIES = [
    {"slug": "food-drinks", "name": "Food & Drinks", "icon": "restaurant", "color": "#ff8a5c"},
    {"slug": "groceries", "name": "Groceries", "icon": "local_grocery_store", "color": "#8b7bff"},
    {"slug": "fruits-veggies", "name": "Fruits & Vegetables", "icon": "nutrition", "color": "#3ddc84"},
    {"slug": "meat-fish", "name": "Meat & Fish", "icon": "set_meal", "color": "#ff6161"},
    {"slug": "bakery", "name": "Bakery", "icon": "bakery_dining", "color": "#f4b942"},
    {"slug": "beverages", "name": "Beverages", "icon": "local_cafe", "color": "#4fc3f7"},
    {"slug": "beauty-health", "name": "Beauty & Health", "icon": "spa", "color": "#f472b6"},
    {"slug": "baby-kids", "name": "Baby & Kids", "icon": "child_care", "color": "#ffb74d"},
    {"slug": "fashion", "name": "Fashion", "icon": "checkroom", "color": "#ba68c8"},
    {"slug": "electronics", "name": "Electronics", "icon": "devices", "color": "#4fc3f7"},
    {"slug": "home-living", "name": "Home & Living", "icon": "chair", "color": "#a1887f"},
    {"slug": "appliances", "name": "Appliances", "icon": "kitchen", "color": "#90a4ae"},
    {"slug": "books-stationery", "name": "Books & Stationery", "icon": "menu_book", "color": "#7986cb"},
    {"slug": "sports-outdoors", "name": "Sports & Outdoors", "icon": "sports_soccer", "color": "#66bb6a"},
    {"slug": "automotive", "name": "Automotive", "icon": "directions_car", "color": "#78909c"},
    {"slug": "pet-supplies", "name": "Pet Supplies", "icon": "pets", "color": "#ffa726"},
    {"slug": "toys-games", "name": "Toys & Games", "icon": "toys", "color": "#ec407a"},
    {"slug": "more", "name": "More", "icon": "apps", "color": "#5c6bc0"},
]

DELIVERY_METHODS = [
    {"id": "standard", "name": "Standard Delivery", "eta": "10-30 min", "fee": 800},
    {"id": "express", "name": "Express Delivery", "eta": "30-60 min", "fee": 1800},
    {"id": "scheduled", "name": "Scheduled Delivery", "eta": "Choose a time", "fee": 500},
    {"id": "pickup", "name": "Store Pickup", "eta": "Ready in 15 min", "fee": 0},
]

PAYMENT_METHODS = [
    {"id": "kbz", "name": "KBZ Pay", "icon": "account_balance_wallet"},
    {"id": "wave", "name": "Wave Pay", "icon": "account_balance_wallet"},
    {"id": "card", "name": "Visa / Mastercard", "icon": "credit_card"},
    {"id": "cod", "name": "Cash on Delivery", "icon": "payments"},
]

STATUS_SEQUENCE = [
    "Order Placed", "Seller Confirmed", "Preparing", "Ready for Pickup",
    "Rider Assigned", "Picked Up", "On the Way", "Delivered",
]

NOTIFICATIONS = [
    {"icon": "check_circle", "title": "Order confirmed", "body": "Your order was accepted by the shop.", "time": "2 min ago"},
    {"icon": "two_wheeler", "title": "Rider assigned", "body": "A rider is on the way to pick up your order.", "time": "25 min ago"},
    {"icon": "local_offer", "title": "Flash Deal", "body": "Up to 25% off Electronics - ends soon!", "time": "1 hr ago"},
    {"icon": "sell", "title": "New promotion", "body": "Free delivery on orders over 5,000 Ks this week.", "time": "3 hr ago"},
]
