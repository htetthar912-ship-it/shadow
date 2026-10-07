"""
Seeds the SQLite database with demo shops/products/accounts the first
time the app runs (so the marketplace isn't empty before any real
seller signs up). Safe to run repeatedly - it checks first and does
nothing if data already exists.
"""

from extensions import db
from models import User, Shop, Product


# Realistic demo shops centered on Pyin Oo Lwin (Maymyo), Mandalay Region.
# Coordinates are clustered around the Purcell Clock Tower / downtown
# (approx 22.03455, 96.45875) and nearby well-known areas so the map
# shows real roads, buildings and shops from OpenStreetMap tiles.
DEMO_SHOPS = [
    dict(name="Pizza King", category="Food & Drinks", is_restaurant=True, emoji="🍕",
         rating=4.4, rating_count=612, distance_km=0.4, delivery_min=20, free_delivery=True,
         is_verified=True, description="Wood-fired pizza and Italian classics, made fresh to order.",
         lat=22.03580, lng=96.45960,  # near Clock Tower / main road
         products=[
             dict(name="Margherita Pizza", category="Food & Drinks", emoji="🍕", price=3800,
                  rating=4.6, is_food=True, free_delivery=True,
                  description="Classic tomato, mozzarella and basil on a wood-fired crust."),
             dict(name="Chicken Biryani", category="Food & Drinks", emoji="🍛", price=3500,
                  rating=4.5, is_food=True, description="Fragrant basmati rice with spiced chicken."),
         ]),
    dict(name="City Mart", category="Groceries", is_restaurant=False, emoji="🛒",
         rating=4.6, rating_count=1830, distance_km=0.6, delivery_min=25, free_delivery=True,
         is_verified=True, description="Your everyday supermarket - groceries, snacks and household needs.",
         lat=22.03390, lng=96.45780,  # near Central Market area
         products=[
             dict(name="Fresh Milk (1L)", category="Groceries", emoji="🥛", price=2200, rating=4.6,
                  reviews_count=120, free_delivery=True, description="Full-cream fresh milk, 1 litre."),
             dict(name="Fresh Milk (200ml)", category="Groceries", emoji="🥛", price=550, rating=4.5,
                  reviews_count=89, description="Full-cream fresh milk, single serving."),
             dict(name="Jasmine Rice 5kg", category="Groceries", emoji="🍚", price=8500, rating=4.7,
                  reviews_count=310, free_delivery=True, description="Premium jasmine rice, 5kg bag."),
             dict(name="Sourdough Bread Loaf", category="Bakery", emoji="🍞", price=3200, rating=4.5,
                  reviews_count=41, description="Freshly baked sourdough, 500g loaf."),
             dict(name="Baby Diapers (Size M, 30pcs)", category="Baby & Kids", emoji="🍼", price=12500,
                  rating=4.5, reviews_count=71, description="Soft and absorbent diapers for everyday use."),
         ]),
    dict(name="Burger Zone", category="Food & Drinks", is_restaurant=True, emoji="🍔",
         rating=4.3, rating_count=401, distance_km=0.8, delivery_min=22, free_delivery=True,
         is_verified=False, description="Juicy flame-grilled burgers and crispy fries.",
         lat=22.03640, lng=96.46120,  # slightly east of center
         products=[
             dict(name="Cheese Burger Combo", category="Food & Drinks", emoji="🍔", price=4200,
                  old_price=5200, discount_pct=20, rating=4.4, is_food=True, free_delivery=True,
                  description="Beef patty, cheddar, fries and a soft drink."),
         ]),
    dict(name="Ocean Store", category="Groceries", is_restaurant=False, emoji="🐟",
         rating=4.5, rating_count=298, distance_km=1.1, delivery_min=28, free_delivery=True,
         is_verified=True, description="Fresh seafood and daily grocery essentials.",
         lat=22.03250, lng=96.45590,  # southwest of clock tower
         products=[
             dict(name="Fresh Bananas (1kg)", category="Fruits & Vegetables", emoji="🍌", price=2500,
                  rating=4.3, reviews_count=64, description="Sweet ripe bananas, sold by the kilogram."),
             dict(name="Grilled Chicken Breast (500g)", category="Meat & Fish", emoji="🍗", price=6200,
                  rating=4.4, reviews_count=88, description="Boneless chicken breast, cleaned and ready to cook."),
             dict(name="Fresh Salmon Fillet (300g)", category="Meat & Fish", emoji="🐟", price=9800,
                  old_price=11500, discount_pct=15, rating=4.6, reviews_count=52,
                  description="Norwegian salmon fillet, chilled."),
         ]),
    dict(name="Healthy Life", category="Beauty & Health", is_restaurant=False, emoji="🌿",
         rating=4.7, rating_count=176, distance_km=0.9, delivery_min=20, free_delivery=False,
         is_verified=True, description="Organic groceries, supplements and wellness products.",
         lat=22.03720, lng=96.45680,  # north of center
         products=[
             dict(name="Roasted Coffee Beans (250g)", category="Beverages", emoji="☕", price=7200,
                  rating=4.8, reviews_count=97, description="Single-origin Shan hill coffee, medium roast."),
             dict(name="Vitamin C Serum", category="Beauty & Health", emoji="🧴", price=15900,
                  old_price=19900, discount_pct=20, rating=4.6, reviews_count=133,
                  description="Brightening facial serum, 30ml."),
         ]),
    dict(name="Shadow Electronics", category="Electronics", is_restaurant=False, emoji="🎧",
         rating=4.5, rating_count=522, distance_km=1.4, delivery_min=35, free_delivery=True,
         is_verified=True, description="Phones, audio gear and accessories at fair prices.",
         lat=22.03080, lng=96.46250,  # toward railway / south-east
         products=[
             dict(name="Wireless Noise-Cancelling Headphones", category="Electronics", emoji="🎧",
                  price=149000, old_price=189000, discount_pct=21, rating=4.7, reviews_count=402,
                  free_delivery=True, description="Over-ear ANC headphones with 30-hour battery life."),
             dict(name="Smart Watch Pro", category="Electronics", emoji="⌚", price=249000, rating=4.5,
                  reviews_count=178, free_delivery=True,
                  description="Fitness tracking, heart-rate monitor and notifications."),
         ]),
    dict(name="Urban Thread", category="Fashion", is_restaurant=False, emoji="👕",
         rating=4.2, rating_count=244, distance_km=0.7, delivery_min=25, free_delivery=False,
         is_verified=False, description="Everyday streetwear and accessories.",
         lat=22.03410, lng=96.46080,  # close to main road / clock tower
         products=[
             dict(name="Classic Sneakers", category="Fashion", emoji="👟", price=45000, old_price=60000,
                  discount_pct=25, rating=4.2, reviews_count=96, description="Everyday canvas sneakers, unisex sizing."),
             dict(name="Cotton Hoodie", category="Fashion", emoji="👕", price=32000, rating=4.1,
                  reviews_count=54, description="Soft brushed-cotton hoodie, available in 4 colours."),
         ]),
    dict(name="Kandawgyi Cafe", category="Food & Drinks", is_restaurant=True, emoji="☕",
         rating=4.6, rating_count=389, distance_km=1.8, delivery_min=30, free_delivery=True,
         is_verified=True, description="Garden cafe near the National Botanical Gardens - coffee, cakes and light meals.",
         lat=22.02150, lng=96.46880,  # near Kandawgyi Gardens area
         products=[
             dict(name="Strawberry Smoothie", category="Beverages", emoji="🍓", price=2800,
                  rating=4.7, is_food=True, free_delivery=True,
                  description="Fresh local strawberries blended with yogurt."),
             dict(name="Garden Club Sandwich", category="Food & Drinks", emoji="🥪", price=4200,
                  rating=4.5, is_food=True, description="Toasted sandwich with chicken, egg and salad."),
         ]),
]


def seed_if_empty():
    """Demo shops/products are OFF by default - a fresh database starts
    completely empty, ready for real sellers to register through
    /register/seller with nothing fake mixed in.

    To turn the demo catalog back on for your own local testing, set
    SEED_DEMO_DATA=true in .env and delete shadow.db so it reseeds."""
    import os
    if os.environ.get("SEED_DEMO_DATA", "").lower() not in ("1", "true", "yes"):
        return
    if Shop.query.first():
        return  # already seeded

    for shop_data in DEMO_SHOPS:
        products = shop_data.pop("products")
        owner = User(
            role="seller", full_name=f"{shop_data['name']} Owner",
            phone=None, email=f"{shop_data['name'].lower().replace(' ', '')}@demo.shadow",
        )
        owner.set_password("demo1234")
        db.session.add(owner)
        db.session.flush()  # get owner.id

        shop = Shop(owner_id=owner.id, **shop_data)
        db.session.add(shop)
        db.session.flush()  # get shop.id

        for p in products:
            db.session.add(Product(shop_id=shop.id, **p))

    # A demo customer so /login has something real to authenticate against.
    demo_customer = User(role="customer", full_name="Demo User", phone="09123456789",
                          email="demo@shadow.app", location_text="Pyin Oo Lwin, Mandalay Region, Myanmar")
    demo_customer.set_password("demo1234")
    db.session.add(demo_customer)

    db.session.commit()
    print("[SHADOW] Seeded demo shops, products and accounts "
          "(demo login: 09123456789 / demo1234).")
