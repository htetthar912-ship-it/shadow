# Shadow App ကို Online တင်ရန် အဆင့်လိုက် Setup Guide

ဒီလမ်းညွှန်က **Neon PostgreSQL + Render Web Service** ကို အသုံးပြုပြီး Shadow App ကို online တင်ရန် ရေးထားတာပါ။ အရင်ဆုံး မဖြစ်မနေလိုတဲ့အပိုင်းကိုလုပ်ပြီး app အလုပ်လုပ်သွားမှ SMS၊ Google Login၊ Telegram နှင့် Voice Order တို့ကို တစ်ခုချင်းထည့်ပါ။

## အရေးကြီးသော လုံခြုံရေးသတိပေးချက်

`DATABASE_URL`, `SECRET_KEY`, `TWILIO_AUTH_TOKEN`, `GOOGLE_CLIENT_SECRET`, `TELEGRAM_BOT_TOKEN`, `OPENAI_API_KEY` တို့ကို chat၊ screenshot၊ GitHub၊ `.env.example` သို့မဟုတ် frontend ထဲ မတင်ရပါ။ အကယ်၍ credential တစ်ခုကို အများမြင်နိုင်တဲ့နေရာမှာ ထည့်ထားပြီးသားဆိုရင် password/token ကို revoke သို့မဟုတ် rotate လုပ်ပြီး အသစ်ထုတ်ပါ။

---

## အပိုင်း A — မဖြစ်မနေလိုသောအရာ ၃ ခု

### အဆင့် ၁ — Project ဖိုင်ကို GitHub သို့တင်ပါ

1. [GitHub](https://github.com) တွင် account ဝင်ပါ။
2. **New repository** ကိုနှိပ်ပါ။
3. Repository name ကို `shadow-app` လို့ပေးပါ။
4. Repository ကို Private ထားပါ။
5. ZIP ဖိုင်ကို ဖြည်ပြီး project folder ထဲက ဖိုင်အားလုံး upload လုပ်ပါ။
6. `.env` ဖိုင်ကို မတင်ပါနှင့်။ `.env.example` သာတင်နိုင်ပါတယ်။
7. `requirements.txt`, `Procfile`, `app.py` တို့ repository root ထဲမှာ ရှိရပါမယ်။

### အဆင့် ၂ — Neon Database ဖွင့်ပါ

1. [Neon Console](https://console.neon.tech) ကိုဝင်ပါ။
2. GitHub သို့မဟုတ် email ဖြင့် account ဖွင့်ပါ။
3. **Create project** ကိုနှိပ်ပါ။
4. Project name ကို `shadow-app-production` လို့ပေးပါ။
5. Region ကို app server နဲ့နီးတဲ့ region ရွေးပါ။
6. Database name၊ role၊ password ကို default အတိုင်းထားနိုင်ပါတယ်။
7. Project dashboard ထဲက **Connect** ကိုနှိပ်ပါ။
8. Branch, database, role ရွေးပါ။
9. **Pooled connection** ကိုရွေးထားပါ။ Connection string က hostname ထဲမှာ `-pooler` ပါတတ်ပါတယ်။
10. `postgresql://...` နဲ့စတဲ့ connection string ကို copy လုပ်ပါ။
11. အဲဒါက သင့် `DATABASE_URL` ဖြစ်ပါတယ်။

Neon connection string ကို ဒီလိုမျိုး ရပါမယ်။ ဥပမာပဲဖြစ်ပြီး ဒီအတိုင်းမသုံးပါနှင့်။

```env
DATABASE_URL=postgresql://USER:PASSWORD@HOST-pooler.neon.tech/DATABASE?sslmode=require&channel_binding=require
```

Neon official guide: [Connect from any application](https://neon.com/docs/connect/connect-from-any-app)

### အဆင့် ၃ — Secret Key အသစ်ထုတ်ပါ

ကိုယ့်ကွန်ပျူတာမှာ terminal ဖွင့်ပြီး—

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

ထွက်လာတဲ့စာကို copy လုပ်ထားပါ။ အဲဒါက `SECRET_KEY` ဖြစ်ပါတယ်။

### အဆင့် ၄ — Render တွင် App တင်ပါ

1. [Render Dashboard](https://dashboard.render.com) ကိုဝင်ပါ။
2. GitHub နဲ့ login ဝင်ပါ။
3. **New + → Web Service** ကိုနှိပ်ပါ။
4. သင့် `shadow-app` repository ကိုရွေးပါ။
5. အောက်ပါအတိုင်းဖြည့်ပါ။

| Render setting | ထည့်ရမည့်တန်ဖိုး |
|---|---|
| Runtime | Python 3 |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `gunicorn --worker-class eventlet -w 1 app:app` |
| Region | သင့် user များနီးသည့် region |
| Branch | `main` |

6. **Create Web Service** ကိုနှိပ်ပါ။
7. Deploy စတင်ပြီး Render URL ရလာပါမယ်။ ဥပမာ—

```text
https://shadow-app-xxxx.onrender.com
```

Render official Flask guide: [Deploy a Flask App on Render](https://render.com/docs/deploy-flask)

### အဆင့် ၅ — Render Environment Variables ထည့်ပါ

Render service ထဲမှာ **Environment → Add Environment Variable** ကိုသွားပြီး အောက်ပါ ၃ ခုထည့်ပါ။

```env
DATABASE_URL=Neon မှ copy လုပ်ထားသော postgresql URL
SECRET_KEY=အဆင့် ၃ မှ ထုတ်ထားသော random secret
FORCE_HTTPS=true
```

ထို့နောက် **Save, rebuild, and deploy** ကိုရွေးပါ။ Render က variable ထည့်ပြီး deploy ပြန်လုပ်ပေးပါမယ်။

Render official environment-variable guide: [Environment Variables and Secrets](https://render.com/docs/configure-environment-variables)

### အဆင့် ၆ — Database စတင်ဖန်တီးခြင်း

App က ပထမဆုံး run တဲ့အချိန် database tables တွေကို ဖန်တီးပေးပါတယ်။ Deploy ပြီးတဲ့အခါ—

1. Render ရဲ့ **Logs** ကိုဖွင့်ပါ။
2. Database connection error မရှိတာ စစ်ပါ။
3. Website URL ကိုဖွင့်ပါ။
4. Admin login ဝင်ပါ။
5. Customer account ဖွင့်ပါ။
6. Seller account ဖွင့်ပြီး product တင်ပါ။

> အရေးကြီးသည် — production database ကို မဖျက်ပါနှင့်။ `models.py` ပြောင်းတဲ့အခါ migration system မသုံးရသေးသောကြောင့် database backup မလုပ်ဘဲ table ဖျက်ခြင်းမလုပ်ပါနှင့်။

---

## အပိုင်း B — Deploy ပြီးနောက် မဖြစ်မနေစမ်းရန်

### Customer flow

1. Customer account ဖွင့်ပါ။
2. Browser က Location permission တောင်းရင် **Allow** နှိပ်ပါ။
3. Nearby map ထဲမှာ ကိုယ့် location marker ပေါ်မပေါ်စစ်ပါ။
4. Seller shop ဝင်ပါ။
5. Product ကို cart ထဲထည့်ပါ။
6. Order တင်ပါ။

### Seller flow

1. Seller account ဖွင့်ပါ။
2. Shop name နှင့် product တင်ပါ။
3. Customer account နဲ့ order တင်ပါ။
4. Seller page မှာ new-order notification နှင့် sound တက်မတက်စစ်ပါ။
5. **Accept** နှိပ်ပါ။
6. Customer ဘက်မှာ `Seller Confirmed` notification တက်မတက်စစ်ပါ။
7. `Preparing → Ready → Delivered` ကို အဆင့်လိုက် စမ်းပါ။

### Support flow

1. Customer နဲ့ Help & Support ကိုဖွင့်ပါ။
2. `order`, `payment`, `ပစ္စည်းဘယ်မှာရောက်ပြီလဲ` စသည့်စာပို့ပါ။
3. Bot က ချက်ချင်းစာပြန်မပြန်စစ်ပါ။
4. Admin account နဲ့ support chat ထဲဝင်ပါ။
5. Header မှာ `Admin online · bot paused` ပြမပြစစ်ပါ။
6. Admin ထွက်သွားပြီး customer ထပ်စာပို့လျှင် bot ပြန်စာပြန်မပြန်စစ်ပါ။

---

## အပိုင်း C — Real Phone OTP ထည့်လိုပါက

ဒီအပိုင်းက optional ဖြစ်ပါတယ်။ လက်ရှိ `SMS_BACKEND=console` ဆိုရင် OTP code ကို server logs ထဲမှာပဲ ပြပါတယ်။ Real SMS အတွက် Twilio သုံးနိုင်ပါတယ်။

1. [Twilio Console](https://console.twilio.com) ကိုဝင်ပါ။
2. Account ဖွင့်ပြီး phone/email verification ပြီးအောင်လုပ်ပါ။
3. Console home မှာ **Account SID** ကို copy လုပ်ပါ။
4. Auth Token ကို copy လုပ်ပါ။
5. **Products & Services → Phone Numbers → Buy a number** သို့သွားပါ။
6. SMS ပို့နိုင်သော phone number တစ်ခုဝယ်ပါ။
7. အောက်ပါ environment variables ထည့်ပါ။

```env
SMS_BACKEND=twilio
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_FROM_NUMBER=+xxxxxxxxxxx
```

8. Project dependency ထဲမှာ `twilio` မပါသေးရင် `requirements.txt` မှာ ထည့်ပြီး deploy ပြန်လုပ်ပါ။
9. ကိုယ့်ဖုန်းနံပါတ်နဲ့ OTP စမ်းပါ။
10. Twilio trial account ဖြစ်ရင် recipient number ကို verify လုပ်ထားရနိုင်ပါတယ်။

Twilio official guide: [Send SMS messages](https://www.twilio.com/docs/messaging/tutorials/how-to-send-sms-messages)

---

## အပိုင်း D — Google Login ထည့်လိုပါက

1. [Google Cloud Console Credentials](https://console.cloud.google.com/apis/credentials) ကိုဝင်ပါ။
2. Project အသစ်ဖန်တီးပါ သို့မဟုတ် ရှိပြီးသား project ရွေးပါ။
3. **OAuth consent screen** ထဲဝင်ပါ။
4. App name, support email, developer email ဖြည့်ပါ။
5. Test mode သုံးရင် စမ်းသုံးမည့် Google account ကို **Test users** ထဲထည့်ပါ။
6. **Credentials → Create Credentials → OAuth client ID** ကိုနှိပ်ပါ။
7. Application type ကို **Web application** ရွေးပါ။
8. Authorized redirect URI မှာ Render URL အပြည့်ထည့်ပါ။

```text
https://YOUR-RENDER-DOMAIN.onrender.com/auth/google/callback
```

9. Client ID နဲ့ Client Secret ကို copy လုပ်ပါ။
10. Render Environment Variables ထဲမှာ ထည့်ပါ။

```env
GOOGLE_CLIENT_ID=xxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=xxxx
```

11. Save and deploy လုပ်ပါ။
12. Login page မှာ Google button စမ်းပါ။

> Redirect URI က code ထဲက URL နဲ့ **စာလုံးအကြီးအသေး၊ https၊ path အားလုံး အတိအကျတူရပါမယ်**။

Google official guide: [OAuth 2.0 for Web Server Applications](https://developers.google.com/identity/protocols/oauth2/web-server)

---

## အပိုင်း E — Telegram Rider Alert ထည့်လိုပါက

1. Telegram app ထဲမှာ `@BotFather` ကိုရှာပါ။
2. `/newbot` ပို့ပါ။
3. Bot name နဲ့ username ပေးပါ။
4. BotFather ပေးတဲ့ bot token ကို copy လုပ်ပါ။
5. Bot ကို ကိုယ့် Telegram account သို့မဟုတ် rider group ထဲထည့်ပါ။
6. Bot ထံ `/start` ပို့ပါ။
7. Chat ID ရယူပြီး environment variables ထဲထည့်ပါ။

```env
TELEGRAM_BOT_TOKEN=အသစ်ထုတ်ထားသော bot token
TELEGRAM_CHAT_ID=သင့် chat id
```

8. Seller က order ကို `Ready for Pickup` လုပ်ပြီး Telegram message ရမရ စမ်းပါ။

> Bot token ကို public မတင်ပါနှင့်။ အရင် token ပေါက်ကြားထားရင် BotFather မှ `/revoke` လုပ်ပြီး အသစ်ထုတ်ပါ။

---

## အပိုင်း F — Voice Order ထည့်လိုပါက

1. [OpenAI Platform](https://platform.openai.com/api-keys) ကိုဝင်ပါ။
2. Account ဖွင့်ပြီး billing/usage setting စစ်ပါ။
3. **API Keys → Create new secret key** ကိုနှိပ်ပါ။
4. Key ကို တစ်ကြိမ်ပဲပြသောကြောင့် လုံခြုံစွာ copy လုပ်ပါ။
5. Render Environment Variables မှာ ထည့်ပါ။

```env
OPENAI_API_KEY=sk-xxxxxxxx
```

6. Deploy ပြန်လုပ်ပါ။
7. App ထဲက microphone ခလုတ်ကိုနှိပ်ပြီး microphone permission Allow လုပ်ပါ။
8. အသံဖြင့် product order စမ်းပါ။

---

## အပိုင်း G — Images မပျောက်အောင်လုပ်ခြင်း

လက်ရှိ seller logo, product image, payment screenshot တွေကို `static/uploads` ထဲမှာ သိမ်းထားပါတယ်။ Hosting server တချို့မှာ redeploy/restart လုပ်တဲ့အခါ local file ပျောက်နိုင်ပါတယ်။ Production မှာ အောက်က persistent storage တစ်ခု ထည့်သင့်ပါတယ်။

- Cloudinary
- Amazon S3
- Supabase Storage
- Cloudflare R2

ဒီအပိုင်းက app အဓိက run ဖို့ မဖြစ်မနေမဟုတ်သော်လည်း seller တကယ်အသုံးပြုမယ့်အခါ **အရေးကြီးပါတယ်**။

---

## အဆုံးသတ် checklist

### အနည်းဆုံး online ဖြစ်ရန်

- [ ] GitHub private repository
- [ ] Neon PostgreSQL project
- [ ] `DATABASE_URL`
- [ ] Random `SECRET_KEY`
- [ ] Render Web Service
- [ ] `FORCE_HTTPS=true`
- [ ] `pip install -r requirements.txt`
- [ ] `gunicorn --worker-class eventlet -w 1 app:app`
- [ ] Location Allow စမ်းပြီးသား
- [ ] Customer → Seller order flow စမ်းပြီးသား

### Feature အပြည့်သုံးရန်

- [ ] Twilio real OTP
- [ ] Google Login
- [ ] Telegram rider alert
- [ ] OpenAI voice order
- [ ] Persistent image/file storage
- [ ] Admin default password ပြောင်းပြီးသား
- [ ] Database backup ပြုလုပ်ပြီးသား

ဒီအဆင့်များပြီးရင် app က online production အတွက် အခြေခံအဆင်သင့်ဖြစ်ပါပြီ။
