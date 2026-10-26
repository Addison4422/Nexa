import re
from nexacart import create_app
from nexacart import models

app = create_app("testing")
app.config["TESTING"] = True

CSRF = re.compile(r'name="csrf_token" value="([^"]+)"')
def tok(client, url="/auth/login"):
    html = client.get(url).get_data(as_text=True)
    m = CSRF.search(html)
    return m.group(1) if m else ""

with app.app_context():
    from datetime import datetime, timezone, timedelta
    sid = models.create_user(username="r5_seller", email="r5_seller@x.com",
                             full_name="R4 Seller", password_hash="x", role="seller")
    models.set_user_approved(sid, True)
    bid = models.create_user(username="r5_buyer", email="r5_buyer@x.com",
                             full_name="R4 Buyer", password_hash="x", role="buyer")
    models.set_user_approved(bid, True)
    from werkzeug.security import generate_password_hash
    models.execute_db("UPDATE users SET password_hash=? WHERE id IN (?,?)",
                      (generate_password_hash("Pass@12345"), sid, bid))
    pid = models.create_product(seller_id=sid, name="R4 Item", description="d",
                                category="c", price_cents=1000, stock_quantity=5,
                                image_path=None)
    exp = (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    models.create_promo(code="4567", kind="discount", percent=10,
                        created_by=sid, target_user_id=None, expires_at=exp)
    models.set_product_discount(pid, 10)
    aid = models.get_user_by_identifier("admin")["id"]
    models.set_user_approved(aid, True)

client = app.test_client()
def login(ident):
    r = client.post("/auth/login",
                    data={"identifier": ident, "password": "Pass@12345",
                          "csrf_token": tok(client)},
                    follow_redirects=False)
    return r

r = login("r5_seller@x.com")
print("seller login:", r.status_code)
r = client.post(f"/seller/products/{pid}/edit",
                data={"name": "R4 Item v2", "description": "d2", "category": "c",
                      "price": "10.00", "stock": "5", "discount": "10",
                      "existing_image": "1", "csrf_token": tok(client, f"/seller/products/{pid}/edit")},
                follow_redirects=True)
print("edit product:", r.status_code)
r = client.get("/seller/products")
print("product list after edit:", r.status_code)

r = login("r5_buyer@x.com")
print("buyer login:", r.status_code)
r = client.post(f"/products/{pid}/favorite", headers={"X-CSRF-Token": tok(client, "/products")})
print("fav toggle OOS:", r.status_code, r.get_data(as_text=True)[:120])
r = client.get("/products")
print("catalogue:", r.status_code)

for method in ("mtn_momo", "airtel_money", "card"):
    r = client.post("/checkout/pay", data={"payment_method": method,
                                           "csrf_token": tok(client, "/checkout")}, follow_redirects=False)
    print(method, "->", r.status_code, r.headers.get("Location", ""))
