import re
from nexacart import create_app

app = create_app("default")
with app.app_context():
    cl = app.test_client()
    h = cl.get("/auth/login").get_data(as_text=True)
    tk = re.search(r'name="csrf_token" value="([^"]+)"', h).group(1)
    r = cl.post("/auth/login", data={"identifier": "_es1", "password": "QA@Password1", "csrf_token": tk})
    print("login ->", r.headers.get("Location"))
    r = cl.get("/seller/products/53/edit")
    print("edit GET ->", r.status_code)
    tk = re.search(r'name="csrf_token" value="([^"]+)"', cl.get("/").get_data(as_text=True)).group(1)
    r = cl.post("/seller/products/53/edit", data={
        "name": "QA-Ed", "description": "Ed item", "category": "",
        "price": "50.00", "stock": "9", "discount": "30",
        "csrf_token": tk}, follow_redirects=False)
    print("edit POST ->", r.status_code, r.headers.get("Location"))
    if r.status_code == 200:
        b = r.get_data(as_text=True)
        j = b.find("field-error")
        print(b[j:j+200] if j > 0 else "no field error")
        j = b.find("alert-error")
        print(b[j:j+200] if j > 0 else "no flash error")
