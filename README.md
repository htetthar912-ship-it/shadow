# SHADOW - Marketplace + Food Delivery (Flask + HTML/CSS/JS)

A real, running prototype of the SHADOW app - customer marketplace/food
delivery + a separate seller dashboard - backed by a real SQLite database,
real accounts, phone-OTP login, Google Sign-In, live chat, live order
tracking, and a mandatory location gate, all over plain Python (Flask) +
HTML/Jinja + CSS + vanilla JS. No Flutter, no build step, no app-store SDK.

## Quick reference: every key this app can use

| Key | What it's for | Free / Paid | Where to get it |
|---|---|---|---|
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | "Continue with Google" login | Free | console.cloud.google.com/apis/credentials |
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` / `TWILIO_FROM_NUMBER` | Send OTP codes as a real SMS | Paid | twilio.com |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Rider pickup alerts | Free | Telegram's @BotFather |
| `OPENAI_API_KEY` | Voice ordering - speech to text | Paid | platform.openai.com/api-keys |
| `GEMINI_API_KEY` | Voice ordering - smarter multi-item parsing | Free tier | aistudio.google.com/apikey |

Full step-by-step for each is further down this file. **Maps need no key at
all** - every map in the app (home, address picker, nearby, shop pages, order
tracking) runs on free OpenStreetMap tiles + OSRM routing, no account or
billing required, ever. See "Map tiles" below for how the dark look is done
without a key, and how to add a real dark-styled provider's key if you want
one instead.

Copy `.env.example` to `.env`, fill in whichever of these you're ready to use, and
restart the app - anything left blank just degrades gracefully (see each
feature's section below for exactly what "not configured" looks like).

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env      # then edit .env - see "Google Sign-In" and "SMS OTP" below
python app.py
```

### Windows PostgreSQL driver note

If `.env` contains a PostgreSQL `DATABASE_URL` such as a Neon connection string, install the PostgreSQL driver in the same Python environment before starting the app:

```powershell
python -m pip install -r requirements.txt
# Or, if the other dependencies are already installed:
python -m pip install psycopg2-binary==2.9.10
```

If you are only testing locally and do not want to connect PostgreSQL yet, leave this line empty in `.env`:

```env
DATABASE_URL=
```

The app will then use the local `shadow.db` SQLite file. Do not use a PostgreSQL URL until `psycopg2-binary` is installed in the Python environment that runs `python app.py`.

Open **http://127.0.0.1:5000** in your browser.

**To open it from your phone** (same Wi-Fi as your computer): the server
already listens on `0.0.0.0`, so find your computer's local IP (Windows:
`ipconfig`, look for "IPv4 Address"; Mac/Linux: `ifconfig` or `ip addr`)
and visit `http://<that-ip>:5000` from your phone's browser. The layout
is fully responsive - phone-width below 900px, a proper desktop layout
with a top nav bar and wider grids above 900px.

**The marketplace starts completely empty** - no demo shops, no fake
products. Real sellers who register through `/register/seller` are the
only shops that will ever show up. (Demo/test data can still be turned
on for your own local testing - see "Demo data" below.)

**Delivery is free platform-wide** right now (`FREE_DELIVERY_MODE = True`
in `geo.py`) - every checkout shows "Free" for every delivery method,
matching the "Free Delivery" messaging shown throughout the app, instead
of quietly charging a distance-based fee. Flip that one flag to `False`
whenever you're ready to actually charge for delivery - the real
distance-based calculation is still there, just switched off.

The database is a single file, `shadow.db`, created automatically on
first run and seeded with demo shops/products/accounts. **If you edit
`models.py`** (add/rename a column), delete `shadow.db` and restart so
it gets recreated with the new schema - there's no migration tool wired
up yet (see "What's simplified" below).

**Demo logins:**
- Customer: phone `09123456789`, password `demo1234` (password tab) - or
  just use the phone-OTP tab with any phone number, since that path
  auto-creates an account.
- Seller: email `citymart@demo.shadow` (or `pizzaking@demo.shadow`, etc.
  - one per seeded shop), password `demo1234`.

## What's implemented

**Location gateway** - the customer app is unusable until location is
granted. On arrival, the browser's real Geolocation API is requested
automatically; if denied, a blocking screen explains it's required and
offers "Try Again". The coordinates are stored server-side in the Flask
session (`session['lat']`/`session['lng']`) for the rest of the visit.

**Real accounts & login**
- Phone + OTP (passwordless) - a 6-digit code is generated, hashed, and
  stored with a 5-minute expiry; verifying it logs you in (creating an
  account on the fly if the phone is new). See "SMS OTP" below for how
  the code actually reaches a phone.
- Google Sign-In (real OAuth 2.0 via Authlib) - see "Google Sign-In"
  below for the one-time setup.
- Email/phone + password - hashed with Werkzeug's PBKDF2, for sellers
  who prefer a traditional business login.

**Shopping**
- Home, Categories, Search (with filter chips), Shop & Product pages,
  Cart (grouped by shop), Checkout, Favorites, Order history, Profile.
- Shops are sorted by **real distance** from the customer's stored
  location (closest first) everywhere except a direct name search,
  which always surfaces the matching shop regardless of distance.
- **Delivery fee is calculated from real distance** (haversine formula)
  between the customer and the shop, per delivery method - not a flat
  fee. See `geo.py` to tune the Ks-per-km rates.
- **Payment screenshot upload** - choosing KBZ Pay or Wave Pay at
  checkout requires uploading a transfer screenshot before the order
  can be placed (Cash on Delivery / card need no screenshot).
- Sellers set every price themselves - there is no platform-side
  pricing logic anywhere; whatever a seller types in Add/Edit Product
  is exactly what customers are charged.

**Live tracking & real-time features (Socket.IO)**
- **Order tracking** page has a real Leaflet + OpenStreetMap map (free,
  no API key) with an animated rider marker, **and now updates live**:
  when a seller changes an order's status, the customer's status
  stepper updates instantly without a page refresh.
- **Real-time chat** between a customer and a shop owner, from a
  product/shop page ("Chat with Seller") or the Chats tab - persisted
  to the database, so history reloads correctly.
- **Loud new-order alert for sellers** - the moment a customer checks
  out, the seller's dashboard/orders page (if open) beeps, shows a
  toast, and fires a browser notification (if permitted) - no refresh
  needed.
- **Nearby** page: a live map (again free Leaflet/OSM) using the
  device's real GPS via `navigator.geolocation`, listing shops sorted
  by actual distance.

**Precise location**
- High-accuracy GPS (`enableHighAccuracy: true`) with a clear loading
  state, specific error messages (permission denied / unavailable /
  timeout / insecure origin), and a **manual map picker fallback** for
  laptops without GPS or when the browser blocks automatic location.
- The moment location is granted, it's **reverse-geocoded** (free, via
  OpenStreetMap's Nominatim - see `geocode.py`) into a real place name -
  e.g. granting location in Pyin Oo Lwin shows "Pyin Oo Lwin, Mandalay
  Region, Myanmar" as your current location, not just a generic country.
- **Important**: browsers only allow automatic geolocation on HTTPS or
  `localhost` - a plain `http://` address on your local network (like
  `http://10.x.x.x:5000`) will silently block it. Use the manual map
  picker in that case, or see "Testing on your phone" below for how to
  get HTTPS locally.

**Live tracking, upgraded to look like a real navigation app** - the
rider now follows the **actual road route** (free public OSRM routing,
no key - falls back to a straight line if that service is unreachable),
drawn as a highlighted purple/cyan path instead of a plain dashed line,
with a floating rider photo/name bubble on the map corner (like a video
-call bubble) and a **real tap-to-call** button (`tel:` link) instead
of a demo toast.

**Shop pages show just that one shop** - a small map on each shop page
now shows only that shop's pin and yours (not every shop in the city),
with the live distance - exactly the "show the shop I'm dealing with,
not everything" behavior. The full "show everything nearby" experience
stays on the dedicated `/nearby` page, which now also supports
**Google-Maps-style "Search this area"**: drag/pan the map and a button
appears to re-sort the shop list around wherever you panned to, instead
of only ever using your original GPS fix.

**Delivery address map, on the Home screen** - Home now shows a live
mini-map preview (tap it to open the full picker) plus a "Delivering
to" line with your confirmed street address. The full picker
(`/address`) is a real draggable-pin map: drop/drag the pin to your
exact door, and it's reverse-geocoded (free, Nominatim) into a
"No. X, Road, Quarter" style address as you move it. Once confirmed,
that pin - not just your coarse browsing location - is what checkout
prefills, what delivery-fee distance is measured from, and what gets
attached to the order for the rider's Google Maps link.

**Sold Out, live** - each seller product has an Available/Sold-Out
toggle. Flipping it instantly (Socket.IO, no refresh) shows a "Sold
Out" badge and disables Add to Cart on every customer screen currently
showing that product, and the server independently rejects adding a
sold-out item to the cart even if a stale page hasn't updated yet.

**Rider handoff (Telegram + Google Maps)** - the moment a seller marks
an order "Ready for Pickup", a message is sent to a Telegram chat (your
own phone, or a group with your riders) with the customer's name,
phone, address, full item list, and a one-tap Google Maps navigation
link - no Google Maps API key needed, it's a plain deep link. See
"Telegram rider alerts" below for the free 2-minute setup. A matching
"Navigate" button also appears directly on the seller's order card.

**Voice ordering ("Shadow AI")** - a press-and-hold mic button records
your voice (browser `MediaRecorder`), transcribes it, extracts the
product(s) and quantity you asked for, matches them against the real
catalog, and adds them to your cart - try "2 cheese burgers and a smart
watch". Typing works too, and works today with zero setup (skips
transcription). The mic itself needs an OpenAI key for transcription;
see "Voice ordering setup" below.

**Loud, persistent new-order alerts** - a seller's dashboard/orders page
shows a banner (not just a toast) with the order code/customer/total,
plays a repeating chime every ~2s for up to 30s (like a phone ringing,
not a single beep easy to miss), and fires a browser notification if
permitted - all until the seller views or dismisses it.

**Seller app** - registration (with logo/cover upload), dashboard,
add/edit/delete/duplicate product, availability toggle, order
management (Accept/Reject/Prepare/Ready/Complete - each one instantly
reflected on the customer's tracking page), sales dashboard.

**Security** (see the checklist further down for the full picture) -
hashed passwords, hashed+expiring+single-use OTP codes, CSRF protection
on every form and every state-changing `fetch()` call, server-side
session cookies, an upload extension allow-list, and all database
access going through the SQLAlchemy ORM.

## Map tiles (no key needed - here's how it works)

Every map in the app used to use a dark-tile provider (CartoDB) that
started requiring an API key - if you saw tiles covered in "API KEY
REQUIRED" watermark text, that's what happened. It's now switched to
**OpenStreetMap's standard tile server**, which is genuinely free
forever, no key, no account - the same reliable default Leaflet itself
ships with. To keep the app's dark look anyway, a CSS filter inverts
the tile colours (`.leaflet-dark-invert` in `style.css`) - a common,
zero-cost trick; markers, popups and buttons live in separate layers
so they're unaffected and still render in their normal colours.

If you'd rather use a real dark-styled map (crisper labels, more
detail) and are fine getting a free key:
1. Sign up at a provider with a real free tier - **MapTiler**
   (maptiler.com, 100k tile loads/month, no credit card) is a solid
   choice; Stadia Maps is another.
2. On their dashboard, find a dark map style and copy the **exact XYZ
   tile URL** they generate for you (it already has your key baked in,
   something like `https://api.maptiler.com/maps/.../{z}/{x}/{y}.png?key=...`).
3. Paste it into `.env` as `MAP_TILE_URL=...` (and their required
   attribution text as `MAP_TILE_ATTRIBUTION=...` - they'll show you
   the exact wording to use).
4. Restart the app. Every map switches to the real tiles automatically
   and the CSS invert trick turns itself off (since real dark tiles
   shouldn't be colour-inverted).

**Live rider tracking is real, not simulated, once shared**: on the
seller's Orders page, a "Share My Live Location" button appears once
an order is out for delivery. Tapping it streams the seller's actual
device GPS (browser `watchPosition`) over Socket.IO straight to that
one order's tracking page - the customer's map marker jumps to the
real reported position the moment it arrives. Until that button is
tapped, the map shows a simulated position moving along the real road
route instead, so there's always something reasonable on screen.

## Deploying for real (free database + free hosting)

Local SQLite (`shadow.db`) is a real, working database - it's just a
single file, which most free hosting platforms wipe out on every
restart/redeploy. For a real launch you want two separate free
services: a **database** that keeps your data permanently, and a
**host** that runs the app. Here's the whole path, step by step.

### Step 1 - Get a free, permanent PostgreSQL database (Neon)

Neon's free tier never expires and needs no credit card (Render's own
free Postgres add-on does expire after 90 days, so we're using a
separate provider for the database specifically).

1. Go to **neon.tech** and sign up (free, no card).
2. Create a new project - it creates a database automatically.
3. On the project dashboard, copy the **connection string** shown -
   it looks like `postgresql://user:password@ep-xxx.neon.tech/dbname?sslmode=require`.
4. Keep this - you'll paste it into Render as `DATABASE_URL` in Step 3.

(Supabase or Aiven work the same way if you'd rather use one of those -
just copy their connection string instead.)

### Step 2 - Push your code to GitHub

Render deploys straight from a GitHub repo.

1. Create a new repository at **github.com/new**.
2. In the project folder:
   ```bash
   git init
   git add .
   git commit -m "Shadow marketplace"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
   git push -u origin main
   ```
   (`.gitignore` already excludes `shadow.db`, `.env`, and `static/uploads/*`
   so you never accidentally commit secrets or local data.)

### Step 3 - Deploy to Render

1. Go to **render.com**, sign up free (no card), then **"New +" → "Web Service"**.
2. Connect your GitHub account and pick the repo you just pushed.
3. Render usually auto-detects Python. Set these explicitly if asked:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn --worker-class eventlet -w 1 app:app`
     (this exact command is also saved in the `Procfile` in your project)
4. Under **Environment**, add every variable from your `.env` file one by
   one - at minimum:
   ```
   SECRET_KEY=<a long random string - not the placeholder>
   DATABASE_URL=<the Neon connection string from Step 1>
   FORCE_HTTPS=true
   FLASK_DEBUG=false
   ```
   plus whichever of the optional keys (Google, Twilio, Telegram, OpenAI,
   Gemini) you're ready to use.
5. Click **"Create Web Service"**. First deploy takes a few minutes -
   watch the logs; you should see `Using worker: eventlet` and no errors.
6. Render gives you a live URL like `https://your-app.onrender.com` - open
   it. Tables are created automatically on first boot (same `db.create_all()`
   that runs locally), and the site starts completely empty, ready for
   real signups.

### Step 4 - Fix anything that points at localhost

- If you set up Google Sign-In, go back to Google Cloud Console and add
  a **second** authorized redirect URI: `https://your-app.onrender.com/auth/google/callback`
  (keep the `127.0.0.1` one too, for local dev).
- Nothing else in the app hardcodes `127.0.0.1` - routes, Socket.IO, and
  the map all use relative/dynamic URLs already.

### What to expect on Render's free tier

- The free web service **spins down after 15 minutes with no traffic**
  and takes 30-60 seconds to wake back up on the next visit - fine for
  a soft launch, noticeable if you want it always instantly responsive
  (Render's paid "Starter" tier removes this).
- Neon's free database **scales to zero compute when idle** too, with a
  similar short wake-up delay - your data itself is never at risk, only
  response time on the very first request after a quiet period.
- Both are genuinely free indefinitely at this scale - no surprise bill,
  no trial clock running out.

## Demo data (off by default)

Fresh installs start empty - no shops, no products, nothing to delete
before a real launch. If you want the old demo catalog (7 sample shops
with products) back for your own local testing/screenshots:

1. Add to `.env`: `SEED_DEMO_DATA=true`
2. Delete `shadow.db` if it already exists (so it reseeds)
3. Restart the app

Demo login when seeded: customer `09123456789` / `demo1234`; sellers use
e.g. `citymart@demo.shadow` / `demo1234` (one account per demo shop).

## Google Sign-In setup

The "Continue with Google" buttons are wired to real OAuth 2.0 - they
just need your own credentials (free, but tied to a Google account so
nobody can hand you working ones):

1. Go to https://console.cloud.google.com/apis/credentials
2. Create an OAuth 2.0 Client ID -> Application type **Web application**.
3. Under "Authorized redirect URIs" add exactly:
   `http://127.0.0.1:5000/auth/google/callback` (add your real domain's
   equivalent too once you deploy).
4. Copy the Client ID and Client Secret into `.env`:
   ```
   GOOGLE_CLIENT_ID=...
   GOOGLE_CLIENT_SECRET=...
   GOOGLE_REDIRECT_URI=http://127.0.0.1:5000/auth/google/callback
   ```
5. Restart `python app.py`. That's it - no code changes needed. Until
   these are set, the Google buttons show a friendly "not configured
   yet" message instead of crashing.

## SMS OTP setup

By default (`SMS_BACKEND=console` in `.env`), the OTP code is printed
to the terminal you ran `python app.py` in - good enough to click
through the whole login flow yourself, and the code is never exposed
anywhere a real user could see it (not in the page, not in the API
response).

To send a **real text message** to the phone:
1. Sign up for an SMS provider that reaches Myanmar numbers - Twilio
   (https://www.twilio.com) is the easiest to wire up; a local gateway
   may be cheaper at scale.
2. `pip install twilio`
3. Set in `.env`:
   ```
   SMS_BACKEND=twilio
   TWILIO_ACCOUNT_SID=...
   TWILIO_AUTH_TOKEN=...
   TWILIO_FROM_NUMBER=...
   ```
4. Restart the app. `otp.py` already has the Twilio branch ready - no
   other code changes needed.

## Telegram rider alerts setup

Free, no billing account, ~2 minutes:

1. In Telegram, message **@BotFather** -> `/newbot` -> follow the
   prompts. You'll get a token like `123456:ABC-DEF1234ghIkl-zyx57W2v1u`.
2. Send your new bot any message (e.g. "hi") so it knows about your chat.
3. Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a
   browser right after step 2, and read the `"chat":{"id": ...}` value
   from the response - that's your chat ID.
4. Add both to `.env`:
   ```
   TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
   TELEGRAM_CHAT_ID=123456789
   ```
5. Restart the app. Every "Ready for Pickup" from now on sends a real
   Telegram message with the address, phone, items, and a Google Maps
   link. Until configured, the same message just prints to the console.

## Voice ordering setup

The mic button needs **OpenAI's Whisper API** to turn speech into text -
this one isn't free:
1. `pip install openai`
2. Get a key at https://platform.openai.com/api-keys
3. Add to `.env`: `OPENAI_API_KEY=sk-...`

For smarter multi-item extraction ("2 burgers and a coke" as two
separate items instead of one), add a free **Gemini** key too:
1. `pip install google-generativeai`
2. Get a free key at https://aistudio.google.com/apikey (no credit card)
3. Add to `.env`: `GEMINI_API_KEY=...`

Without a Gemini key, a simpler built-in extractor handles one item per
sentence (e.g. "2 cheese burgers" works fine; "2 burgers and a coke"
only picks up the first). Without an OpenAI key, the mic button shows a
clear "not configured" message but **typing still works** in the same
Shadow AI page, since text skips the transcription step entirely.

## Testing on your phone (and why HTTPS matters)

The server listens on `0.0.0.0`, so from your phone (same Wi-Fi), visit
`http://<your-computer's-LAN-IP>:5000`. Two things to know:

- **Automatic location won't work over plain HTTP on a LAN address** -
  browsers only allow it on HTTPS or `localhost`. You'll land on the
  manual map picker instead, which works everywhere. For real automatic
  GPS while testing across devices, either deploy behind real HTTPS
  (e.g. a reverse proxy with Let's Encrypt) or tunnel through something
  like `ngrok http 5000`, which gives you a temporary HTTPS URL.
- **Voice recording (MediaRecorder/microphone) has the same HTTPS
  requirement** - same fix applies.

## Security checklist (what's real vs. what to still add)

| Concern | Status |
|---|---|
| Passwords | Hashed (PBKDF2 via Werkzeug), never stored in plain text |
| OTP codes | Hashed, single-use, 5-minute expiry, capped verification attempts |
| CSRF | Every form + every state-changing `fetch()` carries a token (Flask-WTF); a request without one is rejected (tested) |
| SQL injection | All queries go through the SQLAlchemy ORM |
| Session cookies | `HttpOnly` + `SameSite=Lax` set in `app.py` |
| File uploads | Extension allow-list + `secure_filename` + 8MB cap |
| Chat / order rooms | Server checks the logged-in session owns the room before letting a socket join it - not just trusting the client |
| Transport | Dev server only (`python app.py`). Before going live: put this behind HTTPS (e.g. Nginx + Let's Encrypt, or a host that terminates TLS for you) and run it with a production server (`gunicorn -k eventlet` for Flask-SocketIO, not the Werkzeug dev server) |
| Secrets | `.env` (never commit it - see `.gitignore`); set a long random `SECRET_KEY` before going live |
| Rate limiting | Not yet added - consider Flask-Limiter on `/auth/otp/request` and `/login` before launch, so someone can't spam OTP sends or brute-force passwords |
| Payment | Screenshot upload only - no real payment gateway is verifying anything server-side yet (see below) |
| Sold-out race condition | Server-side check on `/api/cart/add` (not just client UI) - confirmed with a test that a toggled-off product is rejected with a 409 even if the page hasn't refreshed |
| Room access (chat/orders/shop alerts) | Every Socket.IO room join is checked server-side against the logged-in session - a seller cannot join another shop's private order-alert room (tested) |

## What's still simplified (and where to extend it)

- **Database migrations**: schema changes require deleting `shadow.db`
  in development. Add Flask-Migrate (Alembic) before you have real data
  you can't afford to lose.
- **Payments**: KBZ Pay / Wave Pay only collect a screenshot as
  evidence - nothing calls a real payment gateway or verifies the
  transfer server-side. Integrate each provider's actual API (or at
  minimum have a human confirm the screenshot before marking an order
  paid) before handling real money.
- **Delivery/rider network**: "Ready for Pickup" just logs a line
  server-side (`app.py`, search for "Notifying nearby riders") - there's
  no real rider app or dispatch system. That's the next big piece to
  build if you want actual couriers.
- **Admin dashboard**: not built - would reuse the same models with its
  own auth and views.
- **Distance-based delivery fee**: straight-line (haversine) distance,
  not real road distance/ETA. A routing API (Google Directions, Mapbox,
  OSRM) would give a more accurate fee/ETA but needs a billing account.
- **Voice ordering matching**: fuzzy name matching (`difflib`), not a
  real product search index - works well for the seeded catalog, may
  need tuning (`geo.py`'s cutoff in `voice_ai.match_products`) as your
  real catalog grows and product names get more similar to each other.
- **Telegram alerts go to one fixed chat**, not a real rider-dispatch
  system that picks the nearest available rider - fine for one shop
  with one or two riders, not a multi-rider network.

## On "how much commission should I charge sellers?"

That's a business decision only you can make (it depends on your costs,
your delivery model, and what sellers in Myanmar will tolerate), but
for context, real marketplaces typically use one or a mix of these:

- **Per-order commission %**: Amazon charges roughly 8-45% depending on
  category (most fall in 8-17%); food delivery apps (Foodpanda, Grab,
  DoorDash, Uber Eats) commonly charge restaurants **15-30%** per order.
- **Delivery fee split**: some platforms charge the *customer* the
  delivery fee and take little/no commission from the seller, relying
  on delivery fees + a small service fee instead.
- **Flat monthly/listing fee**: instead of (or alongside) a %, some
  marketplaces charge sellers a fixed subscription to list products,
  which is easier for sellers to predict but riskier for you if few
  sellers sell much.
- **Tiered by category**: many marketplaces charge a lower % for
  high-value/low-margin goods (electronics) and a higher % for
  low-value/high-margin goods (food, small items).

A common starting point for a new local marketplace is **10-20% on
food orders and 5-12% on general retail**, undercutting the big
platforms slightly to attract sellers early, then adjusting once you
know your actual delivery/support costs per order. Worth validating
directly with a handful of sellers before locking in a number.

## Project structure

```
shadow_web/
├── app.py              # Routes (pages + JSON API), location gate, auth wiring
├── models.py            # SQLAlchemy models: User, Shop, Product, Order, OrderItem, ChatMessage, Favorite, OTPCode
├── extensions.py         # Shared db / socketio / csrf instances
├── constants.py           # Categories, delivery/payment options, status sequence
├── geo.py                  # Haversine distance + distance-based delivery fee
├── geocode.py               # Reverse geocoding (OpenStreetMap Nominatim, free)
├── otp.py                    # OTP generation/verification + pluggable SMS backend
├── google_auth.py              # Google OAuth (Authlib) setup
├── telegram_bot.py               # Telegram rider alerts + Google Maps deep link
├── voice_ai.py                     # Whisper transcription + Gemini/fallback item extraction + fuzzy product matching
├── sockets.py                       # Socket.IO handlers (chat, order status, new-order alerts, sold-out broadcasts)
├── seed.py                           # First-run demo data
├── requirements.txt
├── .env.example
├── static/
│   ├── img/logo.jpg          # Your uploaded Shadow logo, used everywhere
│   ├── css/style.css          # Full design system + responsive desktop breakpoint
│   ├── js/                     # app.js (shared + CSRF helper), auth.js, chat.js, nearby.js, seller_notify.js, tracking.js, checkout.js, seller.js, cart.js, search.js, availability.js, ai_assistant.js
│   └── uploads/                 # Seller logos/covers/products + payment screenshots land here
└── templates/
    ├── base.html                 # Layout, desktop nav, CSRF meta tag
    ├── partials/                  # bottom_nav.html (customer), seller_nav.html (seller)
    └── *.html                      # One template per screen
```
