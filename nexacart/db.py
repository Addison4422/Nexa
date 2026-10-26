"""SQLite connection handling, schema initialisation and CLI commands."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import click
from flask import current_app, g

SCHEMA_FILE = Path(__file__).with_name("schema.sql")


def get_db() -> sqlite3.Connection:
    """Return the request-scoped SQLite connection (open it once)."""
    if "db" not in g:
        database = current_app.config["DATABASE"]
        Path(database).parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(database, timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA journal_mode = WAL")
    return g.db


def close_db(exc: BaseException | None = None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    """Create every table if it does not exist yet, then migrate."""
    db = get_db()
    db.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
    _migrate(db)
    db.commit()


# ---------------------------------------------------------------------
# Lightweight migrations: add columns/tables that older databases miss.
# SQLite cannot add a column conditionally, so check before altering.
# ---------------------------------------------------------------------
def _migrate(db: sqlite3.Connection) -> None:
    existing = {row[1] for row in db.execute("PRAGMA table_info(users)")}
    additions = {
        "business_name": "TEXT NOT NULL DEFAULT ''",
        "business_description": "TEXT NOT NULL DEFAULT ''",
        "country": "TEXT NOT NULL DEFAULT ''",
        "phone_number": "TEXT NOT NULL DEFAULT ''",
        "approved": "INTEGER NOT NULL DEFAULT 1",
    }
    for column, definition in additions.items():
        if column not in existing:
            db.execute(f"ALTER TABLE users ADD COLUMN {column} {definition}")
    db.execute(
        """CREATE TABLE IF NOT EXISTS notifications (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            kind       TEXT    NOT NULL,
            message    TEXT    NOT NULL,
            acknowledged INTEGER NOT NULL DEFAULT 0,
            created_at TEXT    NOT NULL DEFAULT (datetime('now'))
        )"""
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_notifications_user "
        "ON notifications (user_id, acknowledged)"
    )
    # Product categories (Stage 3).
    product_columns = {row[1] for row in db.execute("PRAGMA table_info(products)")}
    if "category" not in product_columns:
        db.execute("ALTER TABLE products ADD COLUMN category TEXT NOT NULL DEFAULT ''")
    if "fulfillment_status" not in product_columns:
        db.execute(
            "ALTER TABLE products ADD COLUMN fulfillment_status TEXT NOT NULL DEFAULT ''"
        )
    order_columns = {row[1] for row in db.execute("PRAGMA table_info(orders)")}
    if "fulfillment_status" not in order_columns:
        db.execute(
            "ALTER TABLE orders ADD COLUMN fulfillment_status TEXT NOT NULL DEFAULT 'processing'"
        )
    if "commission_relief_percent" not in order_columns:
        db.execute(
            "ALTER TABLE orders ADD COLUMN commission_relief_percent INTEGER NOT NULL DEFAULT 0"
        )
    if "fulfilled_at" not in order_columns:
        db.execute("ALTER TABLE orders ADD COLUMN fulfilled_at TEXT")
    if "fulfillment_note" not in order_columns:
        db.execute("ALTER TABLE orders ADD COLUMN fulfillment_note TEXT NOT NULL DEFAULT ''")
    if "payment_method" not in order_columns:
        db.execute(
            "ALTER TABLE orders ADD COLUMN payment_method TEXT NOT NULL DEFAULT 'card'"
        )
    db.execute(
        """CREATE TABLE IF NOT EXISTS reviews (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            buyer_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            rating     INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
            comment    TEXT    NOT NULL DEFAULT '',
            created_at TEXT    NOT NULL DEFAULT (datetime('now')),
            UNIQUE (product_id, buyer_id)
        )"""
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_reviews_product ON reviews (product_id)"
    )
    # Seller payouts & platform fee (Stage 3).
    db.execute(
        """CREATE TABLE IF NOT EXISTS favorites (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            created_at TEXT    NOT NULL DEFAULT (datetime('now')),
            UNIQUE (user_id, product_id)
        )"""
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_favorites_user ON favorites (user_id)"
    )
    # 6-digit password reset codes (emailed to the account owner).
    db.execute(
        """CREATE TABLE IF NOT EXISTS password_reset_codes (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            code_hash  TEXT    NOT NULL,
            attempts   INTEGER NOT NULL DEFAULT 0,
            used       INTEGER NOT NULL DEFAULT 0,
            expires_at TEXT    NOT NULL,
            created_at TEXT    NOT NULL DEFAULT (datetime('now'))
        )"""
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_prc_user ON password_reset_codes (user_id)"
    )
    if "complaints" not in {row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    )}:
        db.execute(
            """CREATE TABLE complaints (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                reporter_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                category     TEXT    NOT NULL,
                detail       TEXT    NOT NULL DEFAULT '',
                status       TEXT    NOT NULL DEFAULT 'pending'
                             CHECK (status IN ('pending', 'resolved')),
                feedback     TEXT    NOT NULL DEFAULT '',
                created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
                resolved_at  TEXT,
                resolved_by  INTEGER REFERENCES users(id) ON DELETE SET NULL
            )"""
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_complaints_status ON complaints (status)"
        )
    if "payouts" not in {row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    )}:
        db.execute(
            """CREATE TABLE payouts (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                seller_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
                status     TEXT    NOT NULL DEFAULT 'requested'
                           CHECK (status IN ('requested', 'paid', 'rejected')),
                note       TEXT    NOT NULL DEFAULT '',
                requested_at TEXT  NOT NULL DEFAULT (datetime('now')),
                processed_at TEXT,
                processed_by INTEGER REFERENCES users(id) ON DELETE SET NULL
            )"""
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_payouts_seller ON payouts (seller_id, status)"
        )
    # Promotions (Stage 4): buyer savings codes and admin commission offers.
    # kind = 'discount'  -> percent off the order total (any buyer can use it)
    # kind = 'commission'-> admin gives an extra percent off, targeted to one
    #                       account or to everyone. Reduced platform fee is
    #                       tracked so the seller is not the one paying.
    db.execute(
        """CREATE TABLE IF NOT EXISTS promo_codes (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            code          TEXT    NOT NULL UNIQUE,
            kind          TEXT    NOT NULL DEFAULT 'discount'
                          CHECK (kind IN ('discount', 'commission')),
            percent       INTEGER NOT NULL CHECK (percent BETWEEN 1 AND 50),
            created_by    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            target_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            expires_at    TEXT    NOT NULL,
            used          INTEGER NOT NULL DEFAULT 0,
            used_by       INTEGER REFERENCES users(id) ON DELETE SET NULL,
            used_at       TEXT,
            created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
        )"""
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_promo_code ON promo_codes (code)"
    )
    # Seller-run product discounts: a percent off a single product.
    product_cols = {row[1] for row in db.execute("PRAGMA table_info(products)")}
    if "discount_percent" not in product_cols:
        db.execute(
            "ALTER TABLE products ADD COLUMN discount_percent INTEGER NOT NULL DEFAULT 0"
        )


def query_db(query: str, args: tuple = (), one: bool = False):
    """Run a parameterised SELECT and return rows (or a single row)."""
    cur = get_db().execute(query, args)
    rows = cur.fetchall()
    cur.close()
    if one:
        return rows[0] if rows else None
    return rows


def execute_db(query: str, args: tuple = ()) -> sqlite3.Cursor:
    """Run a parameterised write statement and commit it."""
    db = get_db()
    cur = db.execute(query, args)
    db.commit()
    return cur


# ---------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------
@click.command("init-db")
def init_db_command() -> None:
    """Create the database schema (idempotent)."""
    init_db()
    click.echo("NEXACART: database schema is up to date.")


@click.command("create-admin")
@click.option("--username", prompt=True, help="Administrator username")
@click.option("--email", prompt=True, help="Administrator email address")
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True,
              help="Administrator password")
@click.option("--name", default="Platform Administrator", help="Administrator full name")
def create_admin_command(username: str, email: str, password: str, name: str) -> None:
    """Create (or promote) an administrator account."""
    from . import security
    from .models import create_user, get_user_by_identifier, update_user_role

    existing = get_user_by_identifier(username)
    if existing:
        update_user_role(existing["id"], "admin")
        from .models import update_user_password
        update_user_password(existing["id"], security.hash_password(password))
        click.echo(f"User '{username}' already exists - promoted to administrator and password reset.")
        return

    create_user(
        username=username.strip(),
        email=email.strip(),
        full_name=name.strip(),
        password_hash=security.hash_password(password),
        role="admin",
        must_change_password=1,
    )
    click.echo(f"Administrator '{username}' created. A password change is required at first sign-in.")


@click.command("seed-demo")
def seed_demo_command() -> None:
    """Create demo seller/buyer accounts for demonstration purposes."""
    from . import security
    from .models import create_user, get_user_by_identifier

    demo = [
        ("seller_demo", "seller@nexacart.local", "Demo Seller", "seller", "Seller@12345"),
        ("buyer_demo", "buyer@nexacart.local", "Demo Buyer", "buyer", "Buyer@12345"),
    ]
    for username, email, full_name, role, password in demo:
        if get_user_by_identifier(username):
            click.echo(f"'{username}' already exists - skipped.")
            continue
        create_user(
            username=username,
            email=email,
            full_name=full_name,
            password_hash=security.hash_password(password),
            role=role,
            must_change_password=0,
        )
        click.echo(f"Created {role}: {username} / {password}")


def init_app(app) -> None:
    """Register database teardown and CLI commands with the Flask app."""
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    app.cli.add_command(create_admin_command)
    app.cli.add_command(seed_demo_command)

    with app.app_context():
        init_db()
