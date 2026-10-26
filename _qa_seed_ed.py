import sqlite3
from werkzeug.security import generate_password_hash

db = sqlite3.connect(r"instance\nexacart.db")
db.execute("DELETE FROM users WHERE username='_es1'")
db.execute("INSERT INTO users (username,email,full_name,password_hash,role,status,approved,created_at) "
           "VALUES ('_es1','_es1@x.local','Ed Seller',?,'seller','active',1,datetime('now'))",
           (generate_password_hash("QA@Password1"),))
db.commit()
s = db.execute("SELECT id FROM users WHERE username='_es1'").fetchone()[0]
db.execute("DELETE FROM products WHERE name='QA-Ed'")
db.execute("INSERT INTO products (seller_id,name,description,price_cents,stock_quantity,discount_percent,created_at) "
           "VALUES (?,'QA-Ed','Ed item',5000,9,10,datetime('now'))", (s,))
db.commit()
print(db.execute("SELECT id,name,discount_percent FROM products WHERE name='QA-Ed'").fetchall())
db.close()
