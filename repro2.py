import re
from nexacart import create_app
app = create_app("testing")
CSRF = re.compile(r'name="csrf_token" value="([^"]+)"')
client = app.test_client()
def tok(url="/auth/login"):
    html = client.get(url).get_data(as_text=True)
    m = CSRF.search(html)
    return m.group(1) if m else ""
def login(ident):
    return client.post("/auth/login", data={"identifier": ident, "password": "Pass@12345",
                                            "csrf_token": tok()}, follow_redirects=False)
client.post("/auth/logout", data={"csrf_token": tok("/buyer")})
r = login("r5_buyer@x.com")
print("buyer login:", r.status_code, r.headers.get("Location"))
r = client.post("/products/2/favorite", headers={"X-CSRF-Token": tok("/products")})
print("fav OOS prod2:", r.status_code, r.get_data(as_text=True)[:120])
r = client.get("/products")
print("catalogue:", r.status_code)
r = client.get("/checkout/")
print("checkout page:", r.status_code)
for method in ("mtn_momo", "airtel_money", "card"):
    r = client.post("/checkout/pay", data={"payment_method": method,
                                           "csrf_token": tok("/checkout")},
                    follow_redirects=False)
    print(method, "->", r.status_code, r.headers.get("Location", ""))
