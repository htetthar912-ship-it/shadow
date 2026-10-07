"""
"Log in with Google" via OAuth 2.0 / OpenID Connect (Authlib).

This is real, standard Google Sign-In - not a mock. To make it work you
need your own Google OAuth credentials (free, but tied to your Google
Cloud project so nobody can generate them on your behalf):

1. Go to https://console.cloud.google.com/apis/credentials
2. Create an OAuth 2.0 Client ID, type "Web application".
3. Under "Authorized redirect URIs" add:
       http://127.0.0.1:5000/auth/google/callback   (for local testing)
       https://yourdomain.com/auth/google/callback   (for production)
4. Copy the Client ID and Client Secret into your .env file:
       GOOGLE_CLIENT_ID=...
       GOOGLE_CLIENT_SECRET=...
5. Restart the app. The "Continue with Google" buttons will start
   working immediately - no code changes needed.

Until those env vars are set, the Google buttons show a friendly
message instead of crashing (see the `google_enabled()` check used in
app.py / templates).
"""

import os
from authlib.integrations.flask_client import OAuth

oauth = OAuth()


def init_google_oauth(app):
    oauth.init_app(app)
    if google_enabled():
        oauth.register(
            name="google",
            client_id=os.environ["GOOGLE_CLIENT_ID"],
            client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )
    return oauth


def google_enabled() -> bool:
    return bool(os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"))
