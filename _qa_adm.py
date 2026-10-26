import re
import sqlite3
from nexacart import create_app
from werkzeug.security import generate_password_hash

db = sqlite3.connect(r"instance\nexacart.db")
db.execute("DELETE FROM users WHERE username='_qaadm'")
db.execute("INSERT INTO users (username,email,full_name,password_hash,role,status,approved,created_at) "
           "VALUES ('_qaadm','_qaadm@x.local','QA',?,'admin','active',1,datetime('now'))",
           (generate_password_hash("QA@Password1"),))
db.commit(); db.close()

app = create_app("default")
with app.app_context():
    cl = app.test_client()
    h = cl.get("/auth/login").get_data(as_text=True)
    tk = re.search(r'name="csrf_token" value="([^"]+)"', h).group(1)
    cl.post("/auth/login", data={"identifier": "_qaadm", "password": "QA@Password1", "csrf_token": tk})
    for path in ("/admin/", "/admin/requests", "/admin/promos", "/admin/users",
                 "/weather/admin/history", "/admin/complaints"):
        r = cl.get(path)
        print(path, "->", r.status_code)
    # admin forgot-password flow
    r = cl.post("/auth/forgot-password", data={"identifier": "_qaadm"})
    print("forgot ->", r.status_code, r.headers.get("Location"))
    r = cl.get("/auth/forgot-password")  # guest_only: logged in can't access
    print("forgot GET while logged in ->", r.status_code)

db = sqlite3.connect(r"instance\nexacart.db")
db.execute("DELETE FROM users WHERE username='_qaadm'")
db.commit(); db.close()
