"""Data-access layer for NEXACART.

Every function here uses parameterised SQL, so user supplied values can
never be injected into the database statements.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Iterable

from .db import execute_db, get_db, query_db
from .i18n import t

# ---------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------
ADMIN = "admin"
SELLER = "seller"
BUYER = "buyer"
ALL_ROLES = (ADMIN, SELLER, BUYER)

# The display names of the roles live in the translation catalogues
# (role.admin, role.seller, role.buyer) - not here.

PUBLIC_ROLES = (SELLER, BUYER)  # roles a visitor may register for


# ---------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------
def get_user_by_id(user_id: int):
    return query_db("SELECT * FROM users WHERE id = ?", (user_id,), one=True)


def get_user_by_identifier(identifier: str):
    """Look a user up by username OR e-mail (case-insensitive)."""
    if not identifier:
        return None
    return query_db(
        "SELECT * FROM users WHERE username = ? COLLATE NOCASE "
        "OR email = ? COLLATE NOCASE LIMIT 1",
        (identifier.strip(), identifier.strip()),
        one=True,
    )


def username_taken(username: str, exclude_id: int | None = None) -> bool:
    if exclude_id is None:
        row = query_db("SELECT id FROM users WHERE username = ? COLLATE NOCASE", (username,), one=True)
    else:
        row = query_db(
            "SELECT id FROM users WHERE username = ? COLLATE NOCASE AND id != ?",
            (username, exclude_id),
            one=True,
        )
    return row is not None


def email_taken(email: str, exclude_id: int | None = None) -> bool:
    if exclude_id is None:
        row = query_db("SELECT id FROM users WHERE email = ? COLLATE NOCASE", (email,), one=True)
    else:
        row = query_db(
            "SELECT id FROM users WHERE email = ? COLLATE NOCASE AND id != ?",
            (email, exclude_id),
            one=True,
        )
    return row is not None


def create_user(
    username: str,
    email: str,
    full_name: str,
    password_hash: str,
    role: str = BUYER,
    must_change_password: int = 0,
) -> int:
    cur = execute_db(
        "INSERT INTO users (username, email, full_name, password_hash, role, "
        "must_change_password) VALUES (?, ?, ?, ?, ?, ?)",
        (username, email, full_name, password_hash, role, must_change_password),
    )
    return int(cur.lastrowid)


def update_user_profile(user_id: int, full_name: str, email: str) -> None:
    execute_db(
        "UPDATE users SET full_name = ?, email = ?, updated_at = datetime('now') WHERE id = ?",
        (full_name, email, user_id),
    )


def update_user_password(user_id: int, password_hash: str) -> None:
    execute_db(
        "UPDATE users SET password_hash = ?, must_change_password = 0, failed_attempts = 0, "
        "locked_until = NULL, updated_at = datetime('now') WHERE id = ?",
        (password_hash, user_id),
    )


def update_user_role(user_id: int, role: str) -> None:
    execute_db(
        "UPDATE users SET role = ?, updated_at = datetime('now') WHERE id = ?",
        (role, user_id),
    )


def set_user_status(user_id: int, status: str) -> None:
    execute_db(
        "UPDATE users SET status = ?, updated_at = datetime('now') WHERE id = ?",
        (status, user_id),
    )


def record_login_success(user_id: int) -> None:
    execute_db(
        "UPDATE users SET last_login_at = datetime('now'), failed_attempts = 0, "
        "locked_until = NULL, updated_at = datetime('now') WHERE id = ?",
        (user_id,),
    )


def record_failed_attempt(user_id: int) -> None:
    execute_db(
        "UPDATE users SET failed_attempts = failed_attempts + 1, "
        "updated_at = datetime('now') WHERE id = ?",
        (user_id,),
    )


def lock_user(user_id: int, until_epoch: int) -> None:
    execute_db(
        "UPDATE users SET locked_until = ?, updated_at = datetime('now') WHERE id = ?",
        (until_epoch, user_id),
    )


def clear_lock(user_id: int) -> None:
    execute_db(
        "UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE id = ?",
        (user_id,),
    )


def list_users(search: str = "", role: str = "", page: int = 1, per_page: int = 10):
    """Return (rows, total_rows) for the administrator's user table."""
    where: list[str] = []
    params: list[Any] = []

    if search:
        where.append("(username LIKE ? OR email LIKE ? OR full_name LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like, like])
    if role in ALL_ROLES:
        where.append("role = ?")
        params.append(role)

    clause = f" WHERE {' AND '.join(where)}" if where else ""
    total = query_db(f"SELECT COUNT(*) AS c FROM users{clause}", tuple(params), one=True)["c"]

    offset = max(page - 1, 0) * per_page
    rows = query_db(
        f"SELECT * FROM users{clause} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
        tuple(params) + (per_page, offset),
    )
    return rows, total


def count_users_by_role() -> dict[str, int]:
    rows = query_db("SELECT role, COUNT(*) AS c FROM users GROUP BY role")
    counts = {role: 0 for role in ALL_ROLES}
    for row in rows:
        counts[row["role"]] = row["c"]
    return counts


def user_statistics() -> dict[str, Any]:
    total = query_db("SELECT COUNT(*) AS c FROM users", one=True)["c"]
    active = query_db(
        "SELECT COUNT(*) AS c FROM users WHERE status = 'active'", one=True
    )["c"]
    suspended = query_db(
        "SELECT COUNT(*) AS c FROM users WHERE status = 'suspended'", one=True
    )["c"]
    locked = query_db(
        "SELECT COUNT(*) AS c FROM users WHERE locked_until IS NOT NULL AND locked_until > ?",
        (int(time.time()),),
        one=True,
    )["c"]
    new_7d = query_db(
        "SELECT COUNT(*) AS c FROM users WHERE created_at >= datetime('now', '-7 days')",
        one=True,
    )["c"]
    return {
        "total": total,
        "active": active,
        "suspended": suspended,
        "locked": locked,
        "new_7d": new_7d,
        "by_role": count_users_by_role(),
    }


# ---------------------------------------------------------------------
# Authentication sessions (server side)
# ---------------------------------------------------------------------
def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_auth_session(
    token_hash: str,
    user_id: int,
    expires_at: int,
    remember_me: bool = False,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> int:
    now = int(time.time())
    cur = execute_db(
        "INSERT INTO auth_sessions (token_hash, user_id, created_at, last_seen_at, "
        "expires_at, remember_me, ip_address, user_agent) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (token_hash, user_id, now, now, expires_at, 1 if remember_me else 0, ip_address, user_agent),
    )
    return int(cur.lastrowid)


def get_auth_session(token_hash: str):
    return query_db(
        "SELECT * FROM auth_sessions WHERE token_hash = ?", (token_hash,), one=True
    )


def get_auth_session_by_id(session_id: int):
    return query_db("SELECT * FROM auth_sessions WHERE id = ?", (session_id,), one=True)


def touch_auth_session(session_id: int, last_seen_at: int, expires_at: int) -> None:
    execute_db(
        "UPDATE auth_sessions SET last_seen_at = ?, expires_at = ? WHERE id = ?",
        (last_seen_at, expires_at, session_id),
    )


def delete_auth_session(token_hash: str) -> None:
    execute_db("DELETE FROM auth_sessions WHERE token_hash = ?", (token_hash,))


def delete_user_sessions(user_id: int, keep_token_hash: str | None = None) -> int:
    if keep_token_hash:
        cur = execute_db(
            "DELETE FROM auth_sessions WHERE user_id = ? AND token_hash != ?",
            (user_id, keep_token_hash),
        )
    else:
        cur = execute_db("DELETE FROM auth_sessions WHERE user_id = ?", (user_id,))
    return cur.rowcount


def list_user_sessions(user_id: int):
    return query_db(
        "SELECT * FROM auth_sessions WHERE user_id = ? ORDER BY last_seen_at DESC",
        (user_id,),
    )


def list_all_sessions(limit: int = 100):
    return query_db(
        "SELECT s.*, u.username, u.role FROM auth_sessions s "
        "JOIN users u ON u.id = s.user_id ORDER BY s.last_seen_at DESC LIMIT ?",
        (limit,),
    )


def count_active_sessions() -> int:
    return query_db(
        "SELECT COUNT(*) AS c FROM auth_sessions WHERE expires_at > ?",
        (int(time.time()),),
        one=True,
    )["c"]


def purge_expired_sessions() -> int:
    cur = execute_db("DELETE FROM auth_sessions WHERE expires_at < ?", (int(time.time()),))
    return cur.rowcount


# ---------------------------------------------------------------------
# Login telemetry & audit trail
# ---------------------------------------------------------------------
def record_login_attempt(
    username: str, ip_address: str | None, successful: bool, reason: str | None = None
) -> None:
    execute_db(
        "INSERT INTO login_attempts (username, ip_address, successful, reason, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (username[:80], ip_address, 1 if successful else 0, reason, int(time.time())),
    )


def count_recent_failures(username: str, window_seconds: int) -> int:
    row = query_db(
        "SELECT COUNT(*) AS c FROM login_attempts WHERE username = ? COLLATE NOCASE "
        "AND successful = 0 AND created_at > ?",
        (username, int(time.time()) - window_seconds),
        one=True,
    )
    return row["c"]


def count_recent_ip_failures(ip_address: str, window_seconds: int) -> int:
    if not ip_address:
        return 0
    row = query_db(
        "SELECT COUNT(*) AS c FROM login_attempts WHERE ip_address = ? "
        "AND successful = 0 AND created_at > ?",
        (ip_address, int(time.time()) - window_seconds),
        one=True,
    )
    return row["c"]


def count_recent_failures_all(window_seconds: int) -> int:
    row = query_db(
        "SELECT COUNT(*) AS c FROM login_attempts WHERE successful = 0 AND created_at > ?",
        (int(time.time()) - window_seconds,),
        one=True,
    )
    return row["c"]


def count_recent_successes_all(window_seconds: int) -> int:
    row = query_db(
        "SELECT COUNT(*) AS c FROM login_attempts WHERE successful = 1 AND created_at > ?",
        (int(time.time()) - window_seconds,),
        one=True,
    )
    return row["c"]


def count_active_admin_users() -> int:
    row = query_db(
        "SELECT COUNT(*) AS c FROM users WHERE role = 'admin' AND status = 'active'",
        one=True,
    )
    return row["c"]


def log_audit(
    action: str,
    user_id: int | None = None,
    username: str | None = None,
    detail: str | None = None,
    ip_address: str | None = None,
) -> None:
    execute_db(
        "INSERT INTO audit_log (user_id, username, action, detail, ip_address, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, username, action, detail, ip_address, int(time.time())),
    )


def list_audit_log(limit: int = 50, offset: int = 0):
    return query_db(
        "SELECT * FROM audit_log ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
        (limit, offset),
    )


def count_audit_entries() -> int:
    return query_db("SELECT COUNT(*) AS c FROM audit_log", one=True)["c"]


def recent_audit_for_user(user_id: int, limit: int = 8):
    return query_db(
        "SELECT * FROM audit_log WHERE user_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
        (user_id, limit),
    )


def iter_audit_rows(limit: int = 200) -> Iterable[Any]:
    return query_db("SELECT * FROM audit_log ORDER BY created_at DESC, id DESC LIMIT ?", (limit,))


def db_is_empty() -> bool:
    return query_db("SELECT COUNT(*) AS c FROM users", one=True)["c"] == 0


def row_to_dict(row) -> dict[str, Any]:
    return dict(row) if row is not None else {}


def get_db_raw():
    return get_db()


# ---------------------------------------------------------------------
# Products (Stage 2: catalogue and inventory)
# ---------------------------------------------------------------------
def create_product(
    seller_id: int,
    name: str,
    description: str,
    price_cents: int,
    stock_quantity: int,
    image_path: str | None = None,
    category: str = "",
) -> int:
    cur = execute_db(
        "INSERT INTO products (seller_id, name, description, category, "
        "price_cents, stock_quantity, image_path) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (seller_id, name, description, category, price_cents, stock_quantity, image_path),
    )
    return int(cur.lastrowid)


def get_product(product_id: int):
    return query_db("SELECT * FROM products WHERE id = ?", (product_id,), one=True)


def list_products(active_only: bool = True, seller_id: int | None = None,
                  search: str = "", category: str = "", sort: str = "newest",
                  limit: int | None = None, offset: int = 0):
    """Catalogue query with search, category filter and sorting."""
    where: list[str] = []
    params: list[Any] = []
    if active_only:
        where.append("is_active = 1")
    if seller_id is not None:
        where.append("seller_id = ?")
        params.append(seller_id)
    if search:
        where.append("(name LIKE ? OR description LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like])
    if category:
        where.append("category = ?")
        params.append(category)
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    order = {
        "newest": "created_at DESC, id DESC",
        "price_asc": "price_cents ASC",
        "price_desc": "price_cents DESC",
        "name": "name COLLATE NOCASE ASC",
    }.get(sort, "created_at DESC, id DESC")
    sql = ("SELECT p.*, u.username AS seller_username, "
           "u.business_name AS seller_business, u.country AS seller_country, "
           "(SELECT pc.code FROM promo_codes pc "
           "  WHERE pc.created_by = p.seller_id AND pc.kind = 'discount' "
           "  AND pc.used = 0 AND pc.expires_at > datetime('now') "
           "  ORDER BY pc.percent DESC LIMIT 1) AS seller_promo_code, "
           "(SELECT MAX(pc2.percent) FROM promo_codes pc2 "
           "  WHERE pc2.created_by = p.seller_id AND pc2.kind = 'discount' "
           "  AND pc2.used = 0 AND pc2.expires_at > datetime('now')) AS seller_promo_percent "
           "FROM products p JOIN users u ON u.id = p.seller_id")
    if clause:
        sql += clause
    sql += f" ORDER BY {order}"
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])
    return query_db(sql, tuple(params))


def list_categories() -> list[str]:
    rows = query_db(
        "SELECT DISTINCT category FROM products WHERE category != '' AND is_active = 1 "
        "ORDER BY category COLLATE NOCASE"
    )
    return [row["category"] for row in rows]


def count_products(active_only: bool = True, search: str = "", category: str = "") -> int:
    where: list[str] = []
    params: list[Any] = []
    if active_only:
        where.append("is_active = 1")
    if search:
        where.append("(name LIKE ? OR description LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like])
    if category:
        where.append("category = ?")
        params.append(category)
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    return query_db(f"SELECT COUNT(*) AS c FROM products{clause}", tuple(params), one=True)["c"]


def update_product(
    product_id: int,
    name: str | None = None,
    description: str | None = None,
    price_cents: int | None = None,
    stock_quantity: int | None = None,
    image_path: str | None = None,
    is_active: bool | None = None,
    category: str | None = None,
) -> None:
    fields: list[str] = []
    params: list[Any] = []
    if name is not None:
        fields.append("name = ?"); params.append(name)
    if description is not None:
        fields.append("description = ?"); params.append(description)
    if category is not None:
        fields.append("category = ?"); params.append(category)
    if price_cents is not None:
        fields.append("price_cents = ?"); params.append(price_cents)
    if stock_quantity is not None:
        fields.append("stock_quantity = ?"); params.append(stock_quantity)
    if image_path is not None:
        fields.append("image_path = ?"); params.append(image_path)
    if is_active is not None:
        fields.append("is_active = ?"); params.append(1 if is_active else 0)
    if not fields:
        return
    fields.append("updated_at = datetime('now')")
    params.append(product_id)
    execute_db(
        f"UPDATE products SET {', '.join(fields)} WHERE id = ?", tuple(params)
    )


def delete_product(product_id: int) -> None:
    execute_db("DELETE FROM products WHERE id = ?", (product_id,))


def adjust_stock(product_id: int, delta: int) -> int | None:
    """Atomically add (positive) or remove (negative) stock.

    Returns the new stock quantity, or None if the product does not exist or
    the stock would drop below zero.
    """
    db = get_db()
    with db:
        row = db.execute(
            "SELECT stock_quantity FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        if row is None:
            return None
        new_stock = row["stock_quantity"] + delta
        if new_stock < 0:
            return None
        db.execute(
            "UPDATE products SET stock_quantity = ?, updated_at = datetime('now') "
            "WHERE id = ?",
            (new_stock, product_id),
        )
    return new_stock


def reserve_stock(product_id: int, quantity: int) -> bool:
    """Decrease stock by ``quantity`` only if enough units are available.

    Atomic check-and-decrement so concurrent buyers cannot oversell.
    """
    cur = db = get_db()
    cur = db.execute(
        "UPDATE products SET stock_quantity = stock_quantity - ?, "
        "updated_at = datetime('now') WHERE id = ? AND stock_quantity >= ?",
        (quantity, product_id, quantity),
    )
    db.commit()
    return cur.rowcount == 1


def release_stock(product_id: int, quantity: int) -> None:
    db = get_db()
    db.execute(
        "UPDATE products SET stock_quantity = stock_quantity + ?, "
        "updated_at = datetime('now') WHERE id = ?",
        (quantity, product_id),
    )
    db.commit()


# ---------------------------------------------------------------------
# Shopping cart (Stage 2: persistent, server side, buyer scoped)
# ---------------------------------------------------------------------
def cart_count(user_id: int) -> int:
    row = query_db(
        "SELECT COALESCE(SUM(quantity), 0) AS c FROM cart_items WHERE user_id = ?",
        (user_id,), one=True,
    )
    return int(row["c"])


def get_cart(user_id: int) -> list[dict[str, Any]]:
    """Cart lines joined with their product, ready for templates."""
    return query_db(
        "SELECT c.id AS cart_id, c.quantity, c.created_at, c.updated_at, "
        "p.id AS product_id, p.name, p.description, p.price_cents, p.discount_percent, "
        "p.seller_id, p.stock_quantity, p.image_path, p.is_active, "
        "u.username AS seller_username, u.business_name AS seller_business "
        "FROM cart_items c JOIN products p ON p.id = c.product_id "
        "JOIN users u ON u.id = p.seller_id "
        "WHERE c.user_id = ? ORDER BY c.created_at DESC",
        (user_id,),
    )


def add_to_cart(user_id: int, product_id: int, quantity: int) -> tuple[bool, str | None]:
    """Add ``quantity`` of ``product_id`` to the buyer's cart.

    Returns (ok, message). Fails when the product is missing, inactive,
    out of stock or when the requested quantity exceeds available stock
    (taking already-carted units into account).
    """
    product = get_product(product_id)
    if product is None:
        return False, "cart.err.product_not_found"
    if not product["is_active"]:
        return False, "cart.err.product_inactive"
    if product["stock_quantity"] <= 0:
        return False, "cart.err.out_of_stock"

    row = query_db(
        "SELECT quantity FROM cart_items WHERE user_id = ? AND product_id = ?",
        (user_id, product_id), one=True,
    )
    already = int(row["quantity"]) if row else 0
    wanted = already + int(quantity)
    if wanted > int(product["stock_quantity"]):
        return False, "cart.err.stock_limit"

    if row:
        execute_db(
            "UPDATE cart_items SET quantity = ?, updated_at = datetime('now') "
            "WHERE user_id = ? AND product_id = ?",
            (wanted, user_id, product_id),
        )
    else:
        execute_db(
            "INSERT INTO cart_items (user_id, product_id, quantity) "
            "VALUES (?, ?, ?)", (user_id, product_id, int(quantity)),
        )
    log_audit(
        "cart_added", user_id, None,
        f"product={product_id} quantity={quantity}",
    )
    return True, None


def update_cart_quantity(user_id: int, cart_id: int, quantity: int) -> tuple[bool, str | None]:
    row = query_db(
        "SELECT c.quantity, c.product_id, p.stock_quantity "
        "FROM cart_items c JOIN products p ON p.id = c.product_id "
        "WHERE c.id = ? AND c.user_id = ?", (cart_id, user_id), one=True,
    )
    if row is None:
        return False, "cart.err.cart_item_not_found"
    if int(quantity) < 1:
        return False, "cart.err.quantity_invalid"
    if int(quantity) > int(row["stock_quantity"]):
        return False, "cart.err.stock_limit"
    execute_db(
        "UPDATE cart_items SET quantity = ?, updated_at = datetime('now') "
        "WHERE id = ? AND user_id = ?", (int(quantity), cart_id, user_id),
    )
    return True, None


def remove_cart_item(user_id: int, cart_id: int) -> bool:
    cur = execute_db(
        "DELETE FROM cart_items WHERE id = ? AND user_id = ?", (cart_id, user_id),
    )
    return cur.rowcount == 1


def clear_cart(user_id: int) -> int:
    cur = execute_db("DELETE FROM cart_items WHERE user_id = ?", (user_id,))
    return cur.rowcount


# ---------------------------------------------------------------------
# Orders and payments (Stage 2: checkout, Flutterwave integration)
# ---------------------------------------------------------------------
def create_order(
    buyer_id: int,
    reference: str,
    currency: str,
    amount_cents: int,
    lines: list[dict[str, Any]],
    payment_method: str = "card",
    commission_relief_percent: int = 0,
) -> int:
    cur = execute_db(
        "INSERT INTO orders (buyer_id, reference, currency, amount_cents, payment_method, "
        "commission_relief_percent) VALUES (?, ?, ?, ?, ?, ?)",
        (buyer_id, reference, currency, amount_cents, payment_method,
         commission_relief_percent),
    )
    order_id = int(cur.lastrowid)
    for line in lines:
        execute_db(
            "INSERT INTO order_items (order_id, product_id, name, price_cents, "
            "currency, quantity, subtotal_cents) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                order_id,
                line["product_id"],
                line["name"],
                line["price_cents"],
                line["currency"],
                line["quantity"],
                line["subtotal_cents"],
            ),
        )
    return order_id


def get_order_by_reference(reference: str):
    return query_db(
        "SELECT * FROM orders WHERE reference = ?", (reference,), one=True
    )


def get_order(order_id: int):
    return query_db("SELECT * FROM orders WHERE id = ?", (order_id,), one=True)


def list_orders(buyer_id: int):
    return query_db(
        "SELECT * FROM orders WHERE buyer_id = ? ORDER BY created_at DESC, id DESC",
        (buyer_id,),
    )


def mark_order_paid(reference: str, flutterwave_tx_id: str | None = None) -> bool:
    cur = execute_db(
        "UPDATE orders SET status = 'paid', paid_at = datetime('now'), "
        "flutterwave_tx_id = ?, updated_at = datetime('now') "
        "WHERE reference = ? AND status != 'paid'",
        (flutterwave_tx_id, reference),
    )
    return cur.rowcount == 1


def order_lines(order_id: int) -> list[dict[str, Any]]:
    return query_db(
        "SELECT * FROM order_items WHERE order_id = ? ORDER BY id", (order_id,)
    )


def list_orders_paged(buyer_id: int, limit: int = 5, offset: int = 0):
    """Most recent orders of a buyer with their item count."""
    return query_db(
        "SELECT o.*, COUNT(oi.id) AS item_count, "
        "COALESCE(SUM(oi.quantity), 0) AS total_quantity "
        "FROM orders o LEFT JOIN order_items oi ON oi.order_id = o.id "
        "WHERE o.buyer_id = ? "
        "GROUP BY o.id ORDER BY o.created_at DESC, o.id DESC LIMIT ? OFFSET ?",
        (buyer_id, limit, offset),
    )


def count_orders(buyer_id: int) -> int:
    row = query_db(
        "SELECT COUNT(*) AS c FROM orders WHERE buyer_id = ?", (buyer_id,), one=True
    )
    return int(row["c"])


def buyer_order_stats(buyer_id: int) -> dict[str, Any]:
    """Lifetime shopping figures for the buyer's advanced settings page."""
    row = query_db(
        "SELECT COUNT(*) AS orders, "
        "COALESCE(SUM(CASE WHEN status = 'paid' THEN amount_cents ELSE 0 END), 0) AS spent, "
        "SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending "
        "FROM orders WHERE buyer_id = ?",
        (buyer_id,), one=True,
    )
    items = query_db(
        "SELECT COALESCE(SUM(oi.quantity), 0) AS c FROM order_items oi "
        "JOIN orders o ON o.id = oi.order_id WHERE o.buyer_id = ?",
        (buyer_id,), one=True,
    )
    return {
        "orders": int(row["orders"]),
        "spent_cents": int(row["spent"]),
        "pending": int(row["pending"] or 0),
        "items": int(items["c"]),
    }


def seller_transactions(seller_id: int | None = None):
    """Receipts: every paid order containing this seller's products.

    With ``None`` the platform-wide view is returned (administrator).
    """
    query = (
        "SELECT o.id AS order_id, o.reference, o.created_at, o.paid_at, "
        "o.status, u.full_name AS buyer_name, u.username AS buyer_username, "
        "u.email AS buyer_email, "
        "GROUP_CONCAT(oi.name || ' x' || oi.quantity, '; ') AS items, "
        "SUM(oi.quantity) AS total_quantity, "
        "SUM(oi.subtotal_cents) AS amount_cents "
        "FROM order_items oi "
        "JOIN products p ON p.id = oi.product_id "
        "JOIN orders o ON o.id = oi.order_id "
        "JOIN users u ON u.id = o.buyer_id "
        "WHERE o.status = 'paid'"
    )
    params: list = []
    if seller_id is not None:
        query += " AND p.seller_id = ?"
        params.append(seller_id)
    query += " GROUP BY o.id ORDER BY COALESCE(o.paid_at, o.created_at) DESC, o.id DESC"
    return query_db(query, tuple(params))


def notify_sellers_of_sale(order_id: int) -> None:
    """Send each seller a receipt notification for a newly paid order."""
    order = get_order(order_id)
    if order is None or order["status"] != "paid":
        return
    rows = query_db(
        "SELECT DISTINCT p.seller_id FROM order_items oi "
        "JOIN products p ON p.id = oi.product_id WHERE oi.order_id = ?",
        (order_id,),
    )
    for row in rows:
        create_notification(
            row["seller_id"],
            "sale_receipt",
            _sale_receipt_text(order_id, row["seller_id"]),
        )


def _sale_receipt_text(order_id: int, seller_id: int) -> str:
    from .i18n import t

    lines = query_db(
        "SELECT oi.name, oi.quantity, oi.subtotal_cents FROM order_items oi "
        "JOIN products p ON p.id = oi.product_id "
        "WHERE oi.order_id = ? AND p.seller_id = ?",
        (order_id, seller_id),
    )
    items_text = "; ".join(f"{l['name']} x{l['quantity']}" for l in lines)
    total = sum(int(l["subtotal_cents"]) for l in lines)
    order = get_order(order_id)
    buyer_row = get_user_by_id(order["buyer_id"])
    paid_at = (order["paid_at"] or order["created_at"] or "")[:16]
    return t(
        "notify.sale_receipt",
        buyer=buyer_row["username"],
        items=items_text,
        total=f"{total / 100:.2f}",
        when=paid_at,
        reference=order["reference"],
    )


# ---------------------------------------------------------------------
# Fulfillment (Stage 3): shipped / delivered
# ---------------------------------------------------------------------
def set_fulfillment(order_id: int, status: str, note: str = "") -> bool:
    if status not in ("shipped", "delivered"):
        return False
    execute_db(
        "UPDATE orders SET fulfillment_status = ?, fulfillment_note = ?, "
        "fulfilled_at = datetime('now'), updated_at = datetime('now') "
        "WHERE id = ? AND status = 'paid'",
        (status, note, order_id),
    )
    order = get_order(order_id)
    if order is None:
        return False
    # Notify the buyer that their order moved along.
    create_notification(
        order["buyer_id"],
        "order_fulfillment",
        t("notify.order_fulfillment",
          reference=order["reference"], status=t(f"fulfillment.{status}")),
    )
    return True


def seller_order_lines(seller_id: int):
    """Paid orders containing this seller's products, with fulfillment state."""
    return query_db(
        "SELECT o.id AS order_id, o.reference, o.paid_at, o.fulfillment_status, "
        "o.fulfillment_note, u.username AS buyer_username, "
        "GROUP_CONCAT(oi.name || ' x' || oi.quantity, '; ') AS items, "
        "SUM(oi.subtotal_cents) AS amount_cents "
        "FROM order_items oi "
        "JOIN products p ON p.id = oi.product_id "
        "JOIN orders o ON o.id = oi.order_id "
        "JOIN users u ON u.id = o.buyer_id "
        "WHERE p.seller_id = ? AND o.status = 'paid' "
        "GROUP BY o.id ORDER BY o.paid_at DESC, o.id DESC",
        (seller_id,),
    )


def order_belongs_to_seller(order_id: int, seller_id: int) -> bool:
    row = query_db(
        "SELECT 1 FROM order_items oi JOIN products p ON p.id = oi.product_id "
        "WHERE oi.order_id = ? AND p.seller_id = ? LIMIT 1",
        (order_id, seller_id), one=True,
    )
    return row is not None


# ---------------------------------------------------------------------
# Reviews (Stage 3): verified buyers only
# ---------------------------------------------------------------------
def buyer_purchased(buyer_id: int, product_id: int) -> bool:
    row = query_db(
        "SELECT 1 FROM order_items oi JOIN orders o ON o.id = oi.order_id "
        "WHERE o.buyer_id = ? AND oi.product_id = ? AND o.status = 'paid' LIMIT 1",
        (buyer_id, product_id), one=True,
    )
    return row is not None


def add_review(product_id: int, buyer_id: int, rating: int, comment: str) -> bool:
    if not (1 <= int(rating) <= 5):
        return False
    if not buyer_purchased(buyer_id, product_id):
        return False
    execute_db(
        "INSERT INTO reviews (product_id, buyer_id, rating, comment) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT (product_id, buyer_id) "
        "DO UPDATE SET rating = excluded.rating, comment = excluded.comment, "
        "created_at = datetime('now')",
        (product_id, buyer_id, int(rating), comment[:500]),
    )
    return True


def product_reviews(product_id: int):
    return query_db(
        "SELECT r.*, u.username, u.full_name FROM reviews r "
        "JOIN users u ON u.id = r.buyer_id "
        "WHERE r.product_id = ? ORDER BY r.created_at DESC, r.id DESC",
        (product_id,),
    )


def product_rating(product_id: int) -> dict[str, Any]:
    row = query_db(
        "SELECT AVG(rating) AS avg, COUNT(*) AS count FROM reviews WHERE product_id = ?",
        (product_id,), one=True,
    )
    return {
        "average": round(float(row["avg"]), 1) if row["avg"] is not None else None,
        "count": int(row["count"]),
    }


# ---------------------------------------------------------------------
# Seller earnings & payouts (Stage 3)
# ---------------------------------------------------------------------
def seller_earnings(seller_id: int, fee_percent: int = 10) -> dict[str, Any]:
    """Balance after the platform fee (minus commission-relief promos), plus totals."""
    rows = query_db(
        "SELECT oi.subtotal_cents AS line_total, "
        "COALESCE(o.commission_relief_percent, 0) AS relief "
        "FROM order_items oi "
        "JOIN products p ON p.id = oi.product_id "
        "JOIN orders o ON o.id = oi.order_id "
        "WHERE p.seller_id = ? AND o.status = 'paid'",
        (seller_id,),
    )
    gross = 0
    fee = 0
    for row in rows:
        line_total = int(row["line_total"])
        gross += line_total
        effective_fee = max(0, fee_percent - int(row["relief"]))
        fee += line_total * effective_fee // 100
    paid_out_row = query_db(
        "SELECT COALESCE(SUM(amount_cents), 0) AS paid FROM payouts "
        "WHERE seller_id = ? AND status = 'paid'",
        (seller_id,), one=True,
    )
    pending_row = query_db(
        "SELECT COALESCE(SUM(amount_cents), 0) AS pending FROM payouts "
        "WHERE seller_id = ? AND status = 'requested'",
        (seller_id,), one=True,
    )
    return {
        "gross_cents": gross,
        "fee_cents": fee,
        "net_cents": gross - fee,
        "paid_out_cents": int(paid_out_row["paid"]),
        "pending_payout_cents": int(pending_row["pending"]),
        "available_cents": gross - fee - int(paid_out_row["paid"]) - int(pending_row["pending"]),
    }


def request_payout(seller_id: int, amount_cents: int, available_cents: int) -> bool:
    """Ask for a payout; validated against the available balance."""
    if amount_cents <= 0 or amount_cents > available_cents:
        return False
    execute_db(
        "INSERT INTO payouts (seller_id, amount_cents) VALUES (?, ?)",
        (seller_id, amount_cents),
    )
    return True


def seller_payouts(seller_id: int):
    return query_db(
        "SELECT * FROM payouts WHERE seller_id = ? ORDER BY requested_at DESC, id DESC",
        (seller_id,),
    )


def all_payouts():
    """Administrator view: every payout request with seller info."""
    return query_db(
        "SELECT pa.*, u.username, u.full_name FROM payouts pa "
        "JOIN users u ON u.id = pa.seller_id "
        "ORDER BY pa.status = 'requested' DESC, pa.requested_at DESC, pa.id DESC"
    )


def process_payout(payout_id: int, admin_id: int, status: str, note: str = "") -> bool:
    if status not in ("paid", "rejected"):
        return False
    cur = execute_db(
        "UPDATE payouts SET status = ?, note = ?, processed_at = datetime('now'), "
        "processed_by = ? WHERE id = ? AND status = 'requested'",
        (status, note, admin_id, payout_id),
    )
    if cur.rowcount != 1:
        return False
    payout = query_db("SELECT * FROM payouts WHERE id = ?", (payout_id,), one=True)
    if payout is not None:
        create_notification(
            payout["seller_id"],
            "payout_update",
            t("notify.payout_update", amount=f"{payout['amount_cents'] / 100:.2f}",
              status=t(f"payouts.{status}")),
        )
    return True


def seller_top_products(seller_id: int | None = None, limit: int = 5):
    """Best-selling products by units sold in paid orders."""
    query = (
        "SELECT p.id, p.name, SUM(oi.quantity) AS units_sold, "
        "SUM(oi.subtotal_cents) AS revenue_cents "
        "FROM order_items oi "
        "JOIN products p ON p.id = oi.product_id "
        "JOIN orders o ON o.id = oi.order_id "
        "WHERE o.status = 'paid'"
    )
    params: list = []
    if seller_id is not None:
        query += " AND p.seller_id = ?"
        params.append(seller_id)
    query += " GROUP BY p.id ORDER BY units_sold DESC, revenue_cents DESC LIMIT ?"
    params.append(limit)
    return query_db(query, tuple(params))


def seller_sales_stats(seller_id: int | None = None) -> dict[str, Any]:
    """Sales figures computed from paid orders for the seller's dashboard.

    With ``seller_id`` the figures cover one seller; with ``None`` the whole
    platform (administrator view).
    """
    if seller_id is not None:
        row = query_db(
            "SELECT COUNT(DISTINCT o.id) AS orders, "
            "COALESCE(SUM(oi.quantity), 0) AS units_sold, "
            "COALESCE(SUM(oi.subtotal_cents), 0) AS revenue_cents "
            "FROM order_items oi "
            "JOIN products p ON p.id = oi.product_id "
            "JOIN orders o ON o.id = oi.order_id "
            "WHERE p.seller_id = ? AND o.status = 'paid'",
            (seller_id,), one=True,
        )
    else:
        row = query_db(
            "SELECT COUNT(DISTINCT o.id) AS orders, "
            "COALESCE(SUM(oi.quantity), 0) AS units_sold, "
            "COALESCE(SUM(oi.subtotal_cents), 0) AS revenue_cents "
            "FROM order_items oi "
            "JOIN orders o ON o.id = oi.order_id WHERE o.status = 'paid'",
            one=True,
        )
    return {
        "orders": int(row["orders"]),
        "units_sold": int(row["units_sold"]),
        "revenue_cents": int(row["revenue_cents"]),
    }


def low_stock_products(seller_id: int | None = None, threshold: int = 5):
    """Products with stock at or below the threshold, lowest first."""
    if seller_id is not None:
        return query_db(
            "SELECT * FROM products WHERE seller_id = ? AND stock_quantity <= ? "
            "ORDER BY stock_quantity ASC LIMIT 10",
            (seller_id, threshold),
        )
    return query_db(
        "SELECT * FROM products WHERE stock_quantity <= ? "
        "ORDER BY stock_quantity ASC LIMIT 10",
        (threshold,),
    )


# ---------------------------------------------------------------------
# Password reset tokens (Stage 2: forgot password)
# ---------------------------------------------------------------------
def create_password_reset(user_id: int, token_hash: str, expires_at: int) -> int:
    cur = execute_db(
        "INSERT INTO password_resets (user_id, token_hash, expires_at, created_at) "
        "VALUES (?, ?, ?, ?)",
        (user_id, token_hash, expires_at, int(time.time())),
    )
    return int(cur.lastrowid)


def peek_password_reset(token_hash: str) -> int | None:
    """Return the user id for a valid, unused token WITHOUT consuming it."""
    row = query_db(
        "SELECT user_id FROM password_resets WHERE token_hash = ? AND used_at IS NULL "
        "AND expires_at > ?", (token_hash, int(time.time())), one=True,
    )
    return int(row["user_id"]) if row is not None else None


def consume_password_reset(token_hash: str) -> int | None:
    """Return the user id of a valid, unused token and mark it used."""
    row = query_db(
        "SELECT * FROM password_resets WHERE token_hash = ? AND used_at IS NULL "
        "AND expires_at > ?", (token_hash, int(time.time())), one=True,
    )
    if row is None:
        return None
    execute_db(
        "UPDATE password_resets SET used_at = ? WHERE id = ?",
        (int(time.time()), row["id"]),
    )
    return int(row["user_id"])


def pending_password_resets():
    """Users with an unused, unexpired password reset token."""
    return query_db(
        "SELECT DISTINCT u.*, pr.created_at AS requested_at, pr.expires_at "
        "FROM password_resets pr JOIN users u ON u.id = pr.user_id "
        "WHERE pr.used_at IS NULL AND pr.expires_at > ? "
        "ORDER BY pr.created_at DESC",
        (int(time.time()),),
    )


def count_pending_password_resets() -> int:
    return query_db(
        "SELECT COUNT(DISTINCT user_id) AS c FROM password_resets "
        "WHERE used_at IS NULL AND expires_at > ?",
        (int(time.time()),), one=True,
    )["c"]


def count_pending_payouts() -> int:
    return query_db(
        "SELECT COUNT(*) AS c FROM payouts WHERE status = 'requested'", one=True,
    )["c"]


# ---------------------------------------------------------------------
# Complaints (Stage 3): preset categories, admin resolution
# ---------------------------------------------------------------------
COMPLAINT_CATEGORIES = (
    "app_not_working",
    "payment_problem",
    "seller_not_responding",
    "wrong_item",
    "item_not_delivered",
    "damaged_item",
    "refund_request",
    "buyer_not_responding",
    "inappropriate_behavior",
    "other",
)


def create_complaint(reporter_id: int, category: str, detail: str) -> int:
    cur = execute_db(
        "INSERT INTO complaints (reporter_id, category, detail) VALUES (?, ?, ?)",
        (reporter_id, category, detail[:1000]),
    )
    return int(cur.lastrowid)


def my_complaints(reporter_id: int):
    return query_db(
        "SELECT * FROM complaints WHERE reporter_id = ? "
        "ORDER BY created_at DESC, id DESC",
        (reporter_id,),
    )


def all_complaints():
    return query_db(
        "SELECT c.*, u.username AS reporter_username, u.role AS reporter_role "
        "FROM complaints c JOIN users u ON u.id = c.reporter_id "
        "ORDER BY c.status = 'pending' DESC, c.created_at DESC, c.id DESC"
    )


def resolve_complaint(complaint_id: int, admin_id: int, feedback: str) -> bool:
    cur = execute_db(
        "UPDATE complaints SET status = 'resolved', feedback = ?, "
        "resolved_at = datetime('now'), resolved_by = ? WHERE id = ? AND status = 'pending'",
        (feedback[:1000], admin_id, complaint_id),
    )
    if cur.rowcount != 1:
        return False
    complaint = query_db("SELECT * FROM complaints WHERE id = ?", (complaint_id,), one=True)
    if complaint is not None:
        create_notification(
            complaint["reporter_id"],
            "complaint_resolved",
            t("notify.complaint_resolved", category=t(f"complaint.{complaint['category']}")),
        )
    return True


def count_pending_complaints() -> int:
    return query_db(
        "SELECT COUNT(*) AS c FROM complaints WHERE status = 'pending'", one=True,
    )["c"]


def pending_complaints():
    return query_db(
        "SELECT c.*, u.username AS reporter_username, u.role AS reporter_role "
        "FROM complaints c JOIN users u ON u.id = c.reporter_id "
        "WHERE c.status = 'pending' "
        "ORDER BY c.created_at DESC, c.id DESC",
    )


# ---------------------------------------------------------------------
# Platform transaction overview (administrator)
# ---------------------------------------------------------------------
def platform_transactions(limit: int = 50):
    """Paid orders with buyer, sellers involved and the platform commission."""
    return query_db(
        "SELECT o.id, o.reference, o.amount_cents, o.payment_method, o.created_at, "
        "o.paid_at, o.status, u.username AS buyer_username, "
        "GROUP_CONCAT(DISTINCT p.seller_id) AS seller_ids "
        "FROM orders o JOIN users u ON u.id = o.buyer_id "
        "LEFT JOIN order_items oi ON oi.order_id = o.id "
        "LEFT JOIN products p ON p.id = oi.product_id "
        "WHERE o.status = 'paid' "
        "GROUP BY o.id ORDER BY o.paid_at DESC, o.id DESC LIMIT ?",
        (limit,),
    )


def platform_transaction_stats(fee_percent: int = 10) -> dict[str, Any]:
    """Gross volume, platform commission, order count."""
    row = query_db(
        "SELECT COUNT(*) AS orders, COALESCE(SUM(amount_cents), 0) AS volume "
        "FROM orders WHERE status = 'paid'",
        one=True,
    )
    volume = int(row["volume"])
    return {
        "orders": int(row["orders"]),
        "volume_cents": volume,
        "commission_cents": volume * fee_percent // 100,
    }


def create_admin_password_reset(user_id: int) -> str | None:
    """Create a fresh reset token for a user (admin action).

    Returns the raw token so the administrator can hand it over; only the
    hash is stored.
    """
    import secrets as _secrets

    delete_password_resets_for_user(user_id)
    token = _secrets.token_urlsafe(32)
    create_password_reset(user_id, hash_token(token), int(time.time()) + 60 * 60)
    return token


def delete_password_resets_for_user(user_id: int) -> None:
    execute_db("DELETE FROM password_resets WHERE user_id = ?", (user_id,))


# ---------------------------------------------------------------------
# Business profile & admin approval
# ---------------------------------------------------------------------
def update_business_profile(
    user_id: int,
    business_name: str,
    business_description: str,
    country: str,
    phone_number: str,
) -> None:
    execute_db(
        "UPDATE users SET business_name = ?, business_description = ?, "
        "country = ?, phone_number = ?, updated_at = datetime('now') WHERE id = ?",
        (business_name, business_description, country, phone_number, user_id),
    )


def set_user_approved(user_id: int, approved: bool) -> None:
    execute_db(
        "UPDATE users SET approved = ?, updated_at = datetime('now') WHERE id = ?",
        (1 if approved else 0, user_id),
    )


def list_pending_approval():
    """Registered accounts awaiting administrator approval."""
    return query_db(
        "SELECT * FROM users WHERE approved = 0 AND status = 'active' "
        "ORDER BY created_at DESC"
    )


def count_pending_approval() -> int:
    return query_db(
        "SELECT COUNT(*) AS c FROM users WHERE approved = 0 AND status = 'active'",
        one=True,
    )["c"]


# ---------------------------------------------------------------------
# In-app notifications (role changes, approvals) with acknowledgement
# ---------------------------------------------------------------------
def create_notification(user_id: int, kind: str, message: str) -> int:
    cur = execute_db(
        "INSERT INTO notifications (user_id, kind, message) VALUES (?, ?, ?)",
        (user_id, kind, message),
    )
    return int(cur.lastrowid)


def list_notifications(user_id: int, unacknowledged_only: bool = False):
    sql = "SELECT * FROM notifications WHERE user_id = ?"
    if unacknowledged_only:
        sql += " AND acknowledged = 0"
    return query_db(sql + " ORDER BY created_at DESC, id DESC", (user_id,))


def get_notification(user_id: int, notification_id: int):
    return query_db(
        "SELECT * FROM notifications WHERE id = ? AND user_id = ?",
        (notification_id, user_id), one=True,
    )


def acknowledge_notification(user_id: int, notification_id: int) -> bool:
    cur = execute_db(
        "UPDATE notifications SET acknowledged = 1 "
        "WHERE id = ? AND user_id = ?",
        (notification_id, user_id),
    )
    return cur.rowcount == 1


# ---------------------------------------------------------------------
# Stage 3: Weather search history
# ---------------------------------------------------------------------
def log_weather_search(query_type: str, query_value: str,
                       city_label: str = "", status: str = "ok") -> None:
    """Record one weather lookup. No personal data is stored."""
    execute_db(
        "INSERT INTO weather_searches (query_type, query_value, city_label, status) "
        "VALUES (?, ?, ?, ?)",
        (query_type, query_value[:200], city_label[:120], status),
    )


def list_weather_searches(limit: int = 50, offset: int = 0):
    return query_db(
        "SELECT * FROM weather_searches ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
        (limit, offset),
    )


def count_weather_searches(status: str | None = None) -> int:
    if status:
        return query_db(
            "SELECT COUNT(*) AS c FROM weather_searches WHERE status = ?",
            (status,), one=True,
        )["c"]
    return query_db("SELECT COUNT(*) AS c FROM weather_searches", one=True)["c"]


def weather_stats(limit_days: int = 7) -> dict:
    """Aggregate usage statistics for the administrator dashboard."""
    top = query_db(
        "SELECT city_label, COUNT(*) AS c FROM weather_searches "
        "WHERE city_label != '' GROUP BY city_label COLLATE NOCASE "
        "ORDER BY c DESC LIMIT 5"
    )
    by_status = query_db(
        "SELECT status, COUNT(*) AS c FROM weather_searches GROUP BY status ORDER BY c DESC"
    )
    by_day = query_db(
        "SELECT date(created_at) AS day, COUNT(*) AS c FROM weather_searches "
        "WHERE created_at >= datetime('now', ?) "
        "GROUP BY date(created_at) ORDER BY day",
        (f"-{limit_days} days",),
    )
    return {
        "total": count_weather_searches(),
        "ok": count_weather_searches("ok"),
        "failed": count_weather_searches() - count_weather_searches("ok"),
        "top_cities": [dict(r) for r in top],
        "by_status": [dict(r) for r in by_status],
        "by_day": [dict(r) for r in by_day],
    }


def clear_weather_history() -> None:
    execute_db("DELETE FROM weather_searches")

# ---------------------------------------------------------------------
# Stage 4: promotions (buyer savings codes, admin commission offers,
# and seller product discounts)
# ---------------------------------------------------------------------
PROMO_MAX_PERCENT = 50
DISCOUNT_MAX_PERCENT = 90


def create_promo(code: str, kind: str, percent: int, created_by: int,
                 target_user_id: int | None, expires_at: str) -> int:
    cur = execute_db(
        "INSERT INTO promo_codes (code, kind, percent, created_by, target_user_id, expires_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (code.upper(), kind, percent, created_by, target_user_id, expires_at),
    )
    return int(cur.lastrowid)


def find_promo(code: str, include_used: bool = False):
    """Return a promo row for ``code`` (live only unless include_used)."""
    sql = "SELECT * FROM promo_codes WHERE code = ?"
    if not include_used:
        sql += " AND used = 0 AND expires_at > datetime('now')"
    return query_db(sql, (code.strip().upper(),), one=True)


def update_promo(promo_id: int, created_by: int | None, percent: int,
                 expires_at: str) -> bool:
    """Update percent/expiry of a live promo. Sellers may only touch their
    own codes (``created_by``); admins pass ``created_by=None``."""
    row = query_db("SELECT * FROM promo_codes WHERE id = ?", (promo_id,), one=True)
    if row is None or row["used"]:
        return False
    if created_by is not None and row["created_by"] != created_by:
        return False
    execute_db(
        "UPDATE promo_codes SET percent = ?, expires_at = ? WHERE id = ?",
        (percent, expires_at, promo_id),
    )
    return True


def find_promo_by_id(promo_id: int):
    return query_db(
        "SELECT * FROM promo_codes WHERE id = ? AND used = 0 "
        "AND expires_at > datetime('now')",
        (promo_id,), one=True,
    )


def promo_visible_to(promo, user_id: int | None) -> bool:
    """Is this promo meant for this account (or everyone)?"""
    if promo is None:
        return False
    return promo["target_user_id"] is None or promo["target_user_id"] == user_id


def mark_promo_used(promo_id: int, user_id: int) -> None:
    execute_db(
        "UPDATE promo_codes SET used = 1, used_by = ?, used_at = datetime('now') "
        "WHERE id = ?",
        (user_id, promo_id),
    )


def list_promos(created_by: int | None = None, kind: str | None = None):
    """Promos joined with creator + target usernames, newest first."""
    where: list[str] = []
    params: list[Any] = []
    if created_by is not None:
        where.append("p.created_by = ?")
        params.append(created_by)
    if kind is not None:
        where.append("p.kind = ?")
        params.append(kind)
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    return query_db(
        "SELECT p.*, u.username AS creator_username, "
        "t.username AS target_username "
        "FROM promo_codes p "
        "JOIN users u ON u.id = p.created_by "
        "LEFT JOIN users t ON t.id = p.target_user_id"
        f"{clause} ORDER BY p.created_at DESC, p.id DESC",
        tuple(params),
    )


def active_promos_for_user(user_id: int | None):
    """Live promos this user is allowed to see (targeted to them or global)."""
    return query_db(
        "SELECT p.*, u.username AS creator_username FROM promo_codes p "
        "JOIN users u ON u.id = p.created_by "
        "WHERE p.used = 0 AND p.expires_at > datetime('now') "
        "AND (p.target_user_id IS NULL OR p.target_user_id = ?) "
        "ORDER BY p.created_at DESC",
        (user_id,),
    )


def active_admin_promos():
    """Live commission promos created by administrators (for admin page)."""
    return query_db(
        "SELECT p.*, u.username AS creator_username, "
        "t.username AS target_username "
        "FROM promo_codes p "
        "JOIN users u ON u.id = p.created_by "
        "LEFT JOIN users t ON t.id = p.target_user_id "
        "WHERE p.kind = 'commission' "
        "ORDER BY (p.used = 0 AND p.expires_at > datetime('now')) DESC, "
        "p.created_at DESC, p.id DESC",
    )


def promo_active_row(promo) -> bool:
    if promo is None:
        return False
    row = query_db(
        "SELECT (datetime('now') < expires_at) AS live FROM promo_codes WHERE id = ?",
        (promo["id"],), one=True,
    )
    return bool(row and row["live"] and not promo["used"])


def delete_promo(promo_id: int, created_by: int | None = None) -> bool:
    if created_by is None:
        cur = execute_db("DELETE FROM promo_codes WHERE id = ?", (promo_id,))
    else:
        cur = execute_db(
            "DELETE FROM promo_codes WHERE id = ? AND created_by = ?",
            (promo_id, created_by),
        )
    return cur.rowcount > 0


def set_product_discount(product_id: int, percent: int) -> None:
    percent = max(0, min(DISCOUNT_MAX_PERCENT, int(percent)))
    execute_db(
        "UPDATE products SET discount_percent = ?, updated_at = datetime('now') "
        "WHERE id = ?",
        (percent, product_id),
    )


def list_discounted_products(limit: int = 12):
    """Active products whose seller set a discount percent, for the offers page."""
    return query_db(
        "SELECT p.*, u.username AS seller_username, u.business_name AS seller_business "
        "FROM products p JOIN users u ON u.id = p.seller_id "
        "WHERE p.is_active = 1 AND p.discount_percent > 0 "
        "ORDER BY p.discount_percent DESC, p.created_at DESC LIMIT ?",
        (limit,),
    )


def is_favorite(user_id: int, product_id: int) -> bool:
    return query_db(
        "SELECT 1 AS x FROM favorites WHERE user_id = ? AND product_id = ?",
        (user_id, product_id), one=True,
    ) is not None


def toggle_favorite(user_id: int, product_id: int) -> bool:
    """Add or remove a favorite; returns True when it is now a favorite."""
    if is_favorite(user_id, product_id):
        execute_db(
            "DELETE FROM favorites WHERE user_id = ? AND product_id = ?",
            (user_id, product_id),
        )
        return False
    execute_db(
        "INSERT INTO favorites (user_id, product_id) VALUES (?, ?)",
        (user_id, product_id),
    )
    return True


def list_favorites(user_id: int):
    """The buyer's favorited products, newest first."""
    return query_db(
        "SELECT p.*, f.created_at AS favorited_at, "
        "u.username AS seller_username, u.business_name AS seller_business "
        "FROM favorites f "
        "JOIN products p ON p.id = f.product_id "
        "JOIN users u ON u.id = p.seller_id "
        "WHERE f.user_id = ? ORDER BY f.created_at DESC, f.id DESC",
        (user_id,),
    )


def favorite_ids(user_id: int) -> set[int]:
    rows = query_db("SELECT product_id FROM favorites WHERE user_id = ?", (user_id,))
    return {int(row["product_id"]) for row in rows}


def count_favorites(user_id: int) -> int:
    return query_db(
        "SELECT COUNT(*) AS c FROM favorites WHERE user_id = ?",
        (user_id,), one=True,
    )["c"]


def live_seller_promo(seller_id: int):
    """The live discount code a seller currently offers on their products."""
    return query_db(
        "SELECT code, percent, expires_at FROM promo_codes "
        "WHERE created_by = ? AND kind = 'discount' AND used = 0 "
        "AND expires_at > datetime('now') "
        "ORDER BY percent DESC LIMIT 1",
        (seller_id,), one=True,
    )

# ---------------------------------------------------------------------
# Stage 5: code-based password reset (6-digit code sent by email)
# ---------------------------------------------------------------------
def create_password_code(user_id: int, code_hash: str, minutes: int = 10) -> None:
    execute_db(
        "INSERT INTO password_reset_codes (user_id, code_hash, expires_at, attempts) "
        "VALUES (?, ?, datetime('now', ?), 0)",
        (user_id, code_hash, f"+{minutes} minutes"),
    )


def find_password_code(user):
    return query_db(
        "SELECT * FROM password_reset_codes WHERE user_id = ? AND used = 0 "
        "AND expires_at > datetime('now') AND attempts < 5 "
        "ORDER BY id DESC LIMIT 1",
        (user["id"],), one=True,
    )


def register_code_attempt(code_row_id: int) -> None:
    execute_db(
        "UPDATE password_reset_codes SET attempts = attempts + 1 WHERE id = ?",
        (code_row_id,),
    )


def consume_password_code(code_row_id: int) -> None:
    execute_db(
        "UPDATE password_reset_codes SET used = 1 WHERE id = ?",
        (code_row_id,),
    )


def purge_password_codes(user_id: int) -> None:
    execute_db("DELETE FROM password_reset_codes WHERE user_id = ?", (user_id,))
