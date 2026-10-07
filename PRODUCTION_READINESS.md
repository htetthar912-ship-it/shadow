# Shadow — Public link production readiness

## Checklist (must before public users)

| # | Item | Status in code | You must set |
|---|------|----------------|--------------|
| 1 | Admin passwords | Env-only in production; weak defaults rejected | `ADMIN1_*` / `ADMIN2_*` |
| 2 | SECRET_KEY | Fails startup if default in production | Long random `SECRET_KEY` |
| 3 | Database | Supports `DATABASE_URL` Postgres | Prefer Postgres on Railway/Render |
| 4 | SMS OTP | Console backend **blocked** in production | `SMS_BACKEND=twilio` + Twilio keys |
| 5 | File uploads | Local disk + optional S3 | `S3_BUCKET` + keys for durable files |
| 6 | HTTPS / GPS | Cookie Secure when `FORCE_HTTPS` | Deploy on HTTPS URL |
| 7 | DEBUG | Forced False in production | `FLASK_ENV=production` |
| 8 | Rate limit | In-memory on login + OTP | Multi-instance → use Redis later |
| 9 | Socket.IO CORS | `SOCKETIO_CORS_ORIGINS` / `PUBLIC_BASE_URL` | Set your public origin |
| 10 | Redis | Optional `REDIS_URL` for Socket.IO queue | Needed for multi-worker scale |
| 11 | CSRF | Flask-WTF enabled | Keep tokens on forms/fetch |

## Public link ready?

**Not yet (NO)** until you configure env: SECRET_KEY, Postgres, Twilio SMS, HTTPS, admin creds.

With those set: **YES for a soft launch** (single instance). Multi-region scale still wants Redis + S3.

## Top 3 priorities

1. **Real SMS (Twilio)** — without it users cannot complete phone OTP register/login in production.
2. **SECRET_KEY + ADMIN env + Postgres** — security and data durability.
3. **HTTPS public URL** — required for live GPS (`watchPosition`) and secure cookies.
