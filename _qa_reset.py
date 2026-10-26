"""Full code-based reset flow test (logged out client)."""
import re
import sqlite3
from nexacart import create_app
from werkzeug.security import generate_password_hash, check_password_hash

db = sqlite3.connect(r"instance\nexacart.db")
db.execute("DELETE FROM users WHERE username='_qadm2'")
db.execute("INSERT INTO users (username,email,full_name,password_hash,role,status,approved,created_at) "
           "VALUES ('_qadm2','_qadm2@x.local','QA2',?,'admin','active',1,datetime('now'))",
           (generate_password_hash("Old@Password1"),))
db.commit(); db.close()

app = create_app("default")
with app.app_context():
    cl = app.test_client()
    h = cl.get("/auth/forgot-password").get_data(as_text=True)
    tk = re.search(r'name="csrf_token" value="([^"]+)"', h).group(1)
    r = cl.post("/auth/forgot-password", data={"identifier": "_qadm2", "csrf_token": tk},
                follow_redirects=True)
    b = r.get_data(as_text=True)
    j = b.find("alert")
    seg = re.sub(r"<[^>]+>", " ", b[j:j+500])
    print("flash:", " ".join(seg.split()))
    m = re.search(r'\b(\d{6})\b', seg)
    code = m.group(1) if m else None
    print("1. code shown in dev mode:", code is not None, code)

    h = cl.get("/auth/reset-code").get_data(as_text=True)
    tk = re.search(r'name="csrf_token" value="([^"]+)"', h).group(1)
    r = cl.post("/auth/reset-code", data={"identifier": "_qadm2", "code": code, "csrf_token": tk},
                follow_redirects=False)
    print("2. code verify ->", r.status_code, r.headers.get("Location"))

    h = cl.get("/auth/reset-with-code").get_data(as_text=True)
    tk = re.search(r'name="csrf_token" value="([^"]+)"', h).group(1)
    r = cl.post("/auth/reset-with-code", data={"password": "New@Password9", "confirm_password": "New@Password9", "csrf_token": tk},
                follow_redirects=False)
    print("3. reset ->", r.status_code, r.headers.get("Location"))

    db = sqlite3.connect(r"instance\nexacart.db")
    hsh = db.execute("SELECT password_hash FROM users WHERE username='_qadm2'").fetchone()[0]
    print("4. new password works:", check_password_hash(hsh, "New@Password9"))
    db.execute("DELETE FROM users WHERE username='_qadm2'")
    db.execute("DELETE FROM password_reset_codes")
    db.commit(); db.close()
