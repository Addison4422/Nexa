"""Reproduce the reported bugs: currency change, product area, logout, account."""
import sys
import traceback

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
    models.execute_db("DELETE FROM products")
    for u, p, role in (
        ("admin", "Admin@12345", "admin"),
        ("seller_demo", "Seller@12345", "seller"),
        ("buyer_demo", "Buyer@12345", "buyer"),
    ):
        models.create_user(username=u, email=f"{u}@x.local", full_name=u.title(),
                           password_hash=NexacartTestCase.hash(p), role=role)
    sid = models.get_user_by_identifier("seller_demo")["id"]
    models.create_product(seller_id=sid, name="Widget", description="x",
                          price_cents=1500, stock_quantity=5)

def check(client, label, method, url, data=None):
    try:
        r = method(url, data=data) if data else method(url)
        body = r.get_data(as_text=True)
        status = r.status_code
        marker = ""
        if status == 500:
            marker = body[:200].replace("\n", " ")
        print(f"{label}: {status} {marker}")
        return r
    except Exception:
        print(f"{label}: EXCEPTION")
        traceback.print_exc()
        return None

# --- BUYER ---
c = app.test_client()
token = csrf_token(c)
check(c, "buyer login", c.post, "/auth/login",
      {"identifier": "buyer_demo", "password": "Buyer@12345", "csrf_token": token})
r = check(c, "buyer GET profile", c.get, "/account/profile")
# currency change from the header form (posts to /account/settings)
token = csrf_token(c, "/account/profile")
r = check(c, "buyer currency change", c.post, "/account/settings",
          {"action": "currency", "currency": "EUR", "csrf_token": token})
r = check(c, "buyer GET settings", c.get, "/account/settings")
r = check(c, "buyer GET security", c.get, "/account/security")
token = csrf_token(c, "/account/profile")
r = check(c, "buyer logout", c.post, "/auth/logout", {"csrf_token": token})
r = check(c, "buyer GET / after logout", c.get, "/")

# --- SELLER ---
s = app.test_client()
token = csrf_token(s)
check(s, "seller login", s.post, "/auth/login",
      {"identifier": "seller_demo", "password": "Seller@12345", "csrf_token": token})
check(s, "seller dash", s.get, "/seller/")
r = check(s, "seller products page", s.get, "/seller/products")
check(s, "seller currency change", s.post, "/account/settings",
      {"action": "currency", "currency": "GBP", "csrf_token": csrf_token(s, "/account/profile")})
check(s, "seller profile", s.get, "/account/profile")

# --- ADMIN ---
a = app.test_client()
token = csrf_token(a)
check(a, "admin login", a.post, "/auth/login",
      {"identifier": "admin", "password": "Admin@12345", "csrf_token": token})
check(a, "admin dash", a.get, "/admin/")
check(a, "admin seller products", a.get, "/seller/products")

# buyer cart redirect (url_for fix in buyer.py)
c2 = app.test_client()
token = csrf_token(c2)
c2.post("/auth/login", data={"identifier": "buyer_demo", "password": "Buyer@12345", "csrf_token": token})
r = c2.get("/buyer/cart")
print("buyer /buyer/cart redirect:", r.status_code, r.headers.get("Location", ""))
r = c2.get("/cart/", follow_redirects=True)
print("cart after redirect:", r.status_code, "Shopping cart" in r.get_data(as_text=True))

# full currency flow: change then verify prices render in EUR
token = csrf_token(c2, "/cart/")
c2.post("/account/settings", data={"action": "currency", "currency": "EUR", "csrf_token": token})
r = c2.get("/cart/")
print("cart in EUR:", r.status_code, chr(8364) in r.get_data(as_text=True))

# logout then land home
token = csrf_token(c2, "/account/profile")
r = c2.post("/auth/logout", data={"csrf_token": token}, follow_redirects=True)
print("logout lands home:", r.status_code)
