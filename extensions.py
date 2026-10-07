"""
Shared Flask extension instances.

Kept in their own module (instead of inside app.py) so that models.py,
otp.py, google_auth.py etc. can import `db` / `socketio` without a
circular import back into app.py.
"""

from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
from flask_wtf import CSRFProtect

db = SQLAlchemy()
socketio = SocketIO(cors_allowed_origins="*", async_mode="threading")
csrf = CSRFProtect()
