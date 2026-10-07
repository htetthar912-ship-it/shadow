import os
import tempfile

fd, path = tempfile.mkstemp(prefix="shadow-commerce-", suffix=".db")
os.close(fd)
os.environ["DATABASE_URL"] = "sqlite:///" + path
os.environ["ADMIN1_USERNAME"] = "smokeadmin1"
os.environ["ADMIN2_USERNAME"] = "smokeadmin2"
os.environ["ADMIN1_EMAIL"] = "smokeadmin1@gmail.com"
os.environ["ADMIN2_EMAIL"] = "smokeadmin2@gmail.com"
os.environ["ADMIN1_PASSWORD"] = "SmokeTest123"
os.environ["ADMIN2_PASSWORD"] = "SmokeTest456"
os.environ["FLASK_ENV"] = "development"

import commerce_bot
assert commerce_bot.validate_product_input("Rice", 1000, 5, 10)[0]
assert not commerce_bot.validate_product_input("", 1000, 5, 10)[0]
assert not commerce_bot.validate_product_input("Rice", -1, 5, 10)[0]
assert commerce_bot.valid_status_transition("Order Placed", "Seller Confirmed", ["Order Placed", "Seller Confirmed"])
assert not commerce_bot.valid_status_transition("Order Placed", "Delivered", ["Order Placed", "Seller Confirmed"])

import app as application
from models import CommerceSecurityEvent
with application.app.app_context():
    assert CommerceSecurityEvent.__tablename__ in application.sa_inspect(application.db.engine).get_table_names()
    event = commerce_bot.log_event(application.db, None, "smoke_test", "no secret data", "127.0.0.1")
    application.db.session.commit()
    assert event.id is not None
    assert application.app.url_map.bind("/").match("/admin/commerce-security")[0] == "admin_commerce_security"

print("commerce smoke test: PASS")
os.unlink(path)
