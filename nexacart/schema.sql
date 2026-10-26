-- =====================================================================
-- NEXACART  |  User Management & Authentication
-- Database schema (SQLite 3, portable SQL only)
-- ---------------------------------------------------------------------
-- The tables for products, inventory and the cart are intentionally NOT
-- created yet. The schema is designed so they can be added later
-- without rewriting the authentication layer.
-- =====================================================================

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------
-- users: one row per registered person, one role per account.
-- Passwords are NEVER stored in plain text (password_hash holds a
-- salted PBKDF2-SHA256 digest produced by Werkzeug).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    username             TEXT    NOT NULL UNIQUE,
    email                TEXT    NOT NULL UNIQUE,
    full_name            TEXT    NOT NULL,
    password_hash        TEXT    NOT NULL,
    role                 TEXT    NOT NULL DEFAULT 'buyer'
                               CHECK (role IN ('admin', 'seller', 'buyer')),
    status               TEXT    NOT NULL DEFAULT 'active'
                               CHECK (status IN ('active', 'suspended')),
    must_change_password INTEGER NOT NULL DEFAULT 0,
    failed_attempts      INTEGER NOT NULL DEFAULT 0,
    locked_until         INTEGER,
    created_at           TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at           TEXT    NOT NULL DEFAULT (datetime('now')),
    last_login_at        TEXT,
    business_name        TEXT    NOT NULL DEFAULT '',
    business_description TEXT    NOT NULL DEFAULT '',
    country              TEXT    NOT NULL DEFAULT '',
    phone_number         TEXT    NOT NULL DEFAULT '',
    approved             INTEGER NOT NULL DEFAULT 1
);

-- Case-insensitive uniqueness for username / email (SQLite: NOCASE
-- collation is applied by the unique indexes below).
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_nocase
    ON users (username COLLATE NOCASE);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_nocase
    ON users (email COLLATE NOCASE);

-- ---------------------------------------------------------------------
-- auth_sessions: server-side session store.
-- The browser only ever receives an opaque random token; only its
-- SHA-256 digest is stored here, so a database leak cannot be replayed
-- as a live session.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS auth_sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash   TEXT    NOT NULL UNIQUE,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at   INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL,
    expires_at   INTEGER NOT NULL,
    remember_me  INTEGER NOT NULL DEFAULT 0,
    ip_address   TEXT,
    user_agent   TEXT
);

CREATE INDEX IF NOT EXISTS idx_auth_sessions_user   ON auth_sessions (user_id);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires ON auth_sessions (expires_at);

-- ---------------------------------------------------------------------
-- login_attempts: security telemetry used for the account lockout
-- rule and for the administrator's security overview.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS login_attempts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username   TEXT    NOT NULL,
    ip_address TEXT,
    successful INTEGER NOT NULL DEFAULT 0,
    reason     TEXT,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_login_attempts_user ON login_attempts (username, created_at);
CREATE INDEX IF NOT EXISTS idx_login_attempts_ip   ON login_attempts (ip_address, created_at);

-- ---------------------------------------------------------------------
-- audit_log: immutable trail of security-relevant events.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    username   TEXT,
    action     TEXT    NOT NULL,
    detail     TEXT,
    ip_address TEXT,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_log_created ON audit_log (created_at DESC);

-- =====================================================================
-- NEXACART Stage 2: Product inventory and shopping cart
-- =====================================================================

-- ---------------------------------------------------------------------
-- products: the catalogue. One row per item for sale.
-- price_cents stores the amount in the platform base currency (USD) so
-- every currency conversion is a pure display step.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS products (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name           TEXT    NOT NULL,
    description    TEXT,
    category       TEXT    NOT NULL DEFAULT '',
    price_cents    INTEGER NOT NULL DEFAULT 0 CHECK (price_cents >= 0),
    stock_quantity INTEGER NOT NULL DEFAULT 0 CHECK (stock_quantity >= 0),
    image_path     TEXT,
    is_active      INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_products_seller   ON products (seller_id);
CREATE INDEX IF NOT EXISTS idx_products_active   ON products (is_active);
CREATE INDEX IF NOT EXISTS idx_products_created  ON products (created_at DESC);

-- ---------------------------------------------------------------------
-- cart_items: one row per (buyer, product). Persistent server side so
-- the cart survives page changes and browser restarts (Stage 2 requirement).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cart_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    product_id   INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    quantity     INTEGER NOT NULL DEFAULT 1 CHECK (quantity >= 1),
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, product_id)
);

CREATE INDEX IF NOT EXISTS idx_cart_items_user   ON cart_items (user_id);
CREATE INDEX IF NOT EXISTS idx_cart_items_product ON cart_items (product_id);

-- ---------------------------------------------------------------------
-- orders: simulated purchases awaiting payment.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS orders (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    buyer_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reference         TEXT    NOT NULL UNIQUE,
    currency          TEXT    NOT NULL DEFAULT 'USD',
    amount_cents      INTEGER NOT NULL DEFAULT 0 CHECK (amount_cents >= 0),
    payment_method    TEXT    NOT NULL DEFAULT 'card'
                      CHECK (payment_method IN ('card', 'mtn_momo', 'airtel_money')),
    status            TEXT    NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending', 'paid', 'failed', 'refunded')),
    paid_at           TEXT,
    flutterwave_tx_id TEXT,
    fulfillment_status TEXT   NOT NULL DEFAULT 'processing'
                       CHECK (fulfillment_status IN ('processing', 'shipped', 'delivered')),
    fulfilled_at      TEXT,
    fulfillment_note  TEXT    NOT NULL DEFAULT '',
    created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_orders_buyer   ON orders (buyer_id);
CREATE INDEX IF NOT EXISTS idx_orders_status  ON orders (status);

-- ---------------------------------------------------------------------
-- order_items: snapshot of what was bought (prices can change later).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS order_items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id      INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id    INTEGER NOT NULL REFERENCES products(id),
    name          TEXT    NOT NULL,
    price_cents   INTEGER NOT NULL,
    currency      TEXT    NOT NULL,
    quantity      INTEGER NOT NULL CHECK (quantity >= 1),
    subtotal_cents INTEGER NOT NULL CHECK (subtotal_cents >= 0),
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------
-- password_resets: one-time tokens for the forgot password flow.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS password_resets (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT    NOT NULL UNIQUE,
    expires_at INTEGER NOT NULL,
    used_at    INTEGER,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_password_resets_token  ON password_resets (token_hash);
CREATE INDEX IF NOT EXISTS idx_password_resets_expires ON password_resets (expires_at);

-- ---------------------------------------------------------------------
-- notifications: in-app messages the user must acknowledge.
-- Used for role-change and approval events so they pop up on next login
-- or in the header of an active session.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notifications (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind         TEXT    NOT NULL,
    message      TEXT    NOT NULL,
    acknowledged INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_notifications_user
    ON notifications (user_id, acknowledged);

-- ---------------------------------------------------------------------
-- reviews: one per (product, buyer) — only buyers who purchased can rate.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reviews (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    buyer_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    rating     INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment    TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (product_id, buyer_id)
);

CREATE INDEX IF NOT EXISTS idx_reviews_product ON reviews (product_id);

-- ---------------------------------------------------------------------
-- payouts: seller earnings withdrawal requests.
-- Each sale keeps a platform fee (see PLATFORM_FEE_PERCENT); the seller's
-- balance is what remains after fees. Admins process payout requests.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS payouts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    status       TEXT    NOT NULL DEFAULT 'requested'
                 CHECK (status IN ('requested', 'paid', 'rejected')),
    note         TEXT    NOT NULL DEFAULT '',
    requested_at TEXT    NOT NULL DEFAULT (datetime('now')),
    processed_at TEXT,
    processed_by INTEGER REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_payouts_seller ON payouts (seller_id, status);

-- ---------------------------------------------------------------------
-- complaints: preset categories users report to the admin.
-- Admin marks them Done with feedback; the reporter sees the result.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS complaints (
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
);

CREATE INDEX IF NOT EXISTS idx_complaints_status ON complaints (status);
-- =====================================================================
-- NEXACART Stage 3: Weather information (OpenWeather API)
-- =====================================================================

-- ---------------------------------------------------------------------
-- weather_searches: one row per weather lookup, for administrator
-- review. Privacy: no user ids are stored — only the search input
-- (city or coordinates), how it was searched, whether it succeeded,
-- and when. Public feature, so visitors need no account.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS weather_searches (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    query_type   TEXT    NOT NULL CHECK (query_type IN ('city', 'coords')),
    query_value  TEXT    NOT NULL,
    city_label   TEXT    NOT NULL DEFAULT '',
    status       TEXT    NOT NULL DEFAULT 'ok'
                 CHECK (status IN ('ok', 'not_found', 'invalid', 'api_error', 'network_error')),
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_weather_searches_created ON weather_searches (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_weather_searches_status ON weather_searches (status);
