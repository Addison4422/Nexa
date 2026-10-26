import re
from nexacart import create_app
app = create_app("testing")
CSRF = re.compile(r'name="csrf_token" value="([^"]+)"')
client = app.test_client()
def tok(url="/auth/login"):
    html = client.get(url).get_data(as_text=True)
    m = CSRF.search(html)
    return m.group(1) if m else ""
# add to cart as buyer (already logged in from repro run session? new client anyway)
client.post("/auth/login", data={"identifier": "r5_buyer@x.com", "password": "Pass@12345",
                                 "csrf_token": tok()})
r = client.post("/cart/add", data={"product_id": "2", "quantity": "1",
                                   "csrf_token": tok("/products")})
print("cart add:", r.status_code, r.get_data(as_text=True)[:100])
for method in ("mtn_momo", "airtel_money", "card"):
    r = client.post("/checkout/pay", data={"payment_method": method,
                                           "csrf_token": tok("/checkout")},
                    follow_redirects=False)
    print(method, "->", r.status_code, r.headers.get("Location", ""))
