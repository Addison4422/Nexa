"""Debug the currency persistence issue."""
import sys

sys.path.insert(0, ".")
from pathlib import Path
from tests.test_app import NexacartTestCase, csrf_token
from nexacart import create_app, models

instance = Path("instance")
for suffix in ("", "-wal", "-shm"):
    candidate = instance / ("nexacart_test.db" + suffix)
    if candidate.exists():
        candidate.unlink()

app = create_app("testing")
app.config["SERVER_NAME"] = None

with app.app_context():
    models.execute_db("DELETE FROM users")
    models.create_user(username="buyer_demo", email="b@x.local", full_name="B",
                       password_hash=NexacartTestCase.hash("Buyer@12345"), role="buyer")

c = app.test_client()
c.post("/auth/login", data={"identifier": "buyer_demo", "password": "Buyer@12345",
                            "csrf_token": csrf_token(c)})

with c.session_transaction() as sess:
    print("session after login:", dict(sess))

token = csrf_token(c, "/account/profile")
r = c.post("/account/settings", data={"action": "currency", "currency": "EUR", "csrf_token": token})
print("currency POST:", r.status_code)

with c.session_transaction() as sess:
    print("session after currency POST:", dict(sess))

r = c.get("/cart/")
with c.session_transaction() as sess:
    print("session after GET /cart:", dict(sess))
print("EUR on page:", "\u20ac" in r.get_data(as_text=True))
