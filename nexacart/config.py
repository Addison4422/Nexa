"""Application configuration objects for NEXACART."""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
INSTANCE_DIR = BASE_DIR / "instance"


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class DefaultConfig:
    """Local development / coursework configuration."""

    # --- core -------------------------------------------------------
    SECRET_KEY = os.environ.get("NEXACART_SECRET_KEY", "nexacart-dev-secret-key-change-me")
    SECRET_KEY_FILE = str(INSTANCE_DIR / "secret_key")
    DATABASE = str(INSTANCE_DIR / "nexacart.db")

    # --- session / cookie hardening ---------------------------------
    # Flask's own signed cookie carries the CSRF token only.
    SESSION_COOKIE_NAME = "nexacart_csrf"
    # The opaque authentication token is stored server side.
    AUTH_COOKIE_NAME = "nexacart_session"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _env_flag("NEXACART_HTTPS", False)

    # Signed cookie that only carries the CSRF token.
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 30

    # --- session lifetimes (seconds) --------------------------------
    SESSION_IDLE_TIMEOUT = 30 * 60           # 30 minutes of inactivity
    SESSION_ABSOLUTE_TIMEOUT = 12 * 60 * 60  # 12 hours maximum
    SESSION_REMEMBER_TIMEOUT = 30 * 24 * 60 * 60  # "remember me" = 30 days

    # --- authentication policy --------------------------------------
    MAX_LOGIN_ATTEMPTS = 5
    LOCKOUT_DURATION = 15 * 60        # 15 minutes
    IP_MAX_ATTEMPTS = 20              # per IP inside the window below
    IP_ATTEMPT_WINDOW = 15 * 60
    PASSWORD_MIN_LENGTH = 8
    PASSWORD_MAX_LENGTH = 128
    PASSWORD_HASH_METHOD = "pbkdf2:sha256:600000"

    # --- UI ---------------------------------------------------------
    ITEMS_PER_PAGE = 10
    APP_NAME = "NEXACART"
    APP_VERSION = "2.0.0"

    # --- uploads (product images) -----------------------------------
    UPLOAD_FOLDER = str(INSTANCE_DIR / "uploads" / "products")
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024          # 2 MB per upload
    ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

    # --- marketplace economics ---------------------------------------
    # Platform commission on each sale, as a percentage of the order
    # subtotal. Sellers keep the rest; their balance is paid out on
    # request and processed by an administrator.
    PLATFORM_FEE_PERCENT = 10

    # --- email (password reset codes) --------------------------------
    # Configure via environment so credentials never live in the source.
    SMTP_HOST = os.environ.get("SMTP_HOST", "")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
    SMTP_USER = os.environ.get("SMTP_USER", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    SMTP_FROM = os.environ.get("SMTP_FROM", "")
    ADMIN_NOTIFY_EMAIL = "princeabkanneh@gmail.com"

    # --- currencies (10 major currencies including RWF) -------------
    # Rates are illustrative, expressed against the platform base
    # currency (USD). Conversions are a pure display step: prices are
    # stored in USD cents.
    BASE_CURRENCY = "USD"
    CURRENCIES: dict[str, dict[str, str | float]] = {
        "USD": {"symbol": "$",   "name": "US Dollar",            "rate": 1.0},
        "EUR": {"symbol": "€",   "name": "Euro",                 "rate": 0.92},
        "GBP": {"symbol": "£",   "name": "British Pound",        "rate": 0.79},
        "KES": {"symbol": "KSh", "name": "Kenyan Shilling",      "rate": 129.50},
        "UGX": {"symbol": "USh", "name": "Ugandan Shilling",     "rate": 3650.0},
        "TZS": {"symbol": "TSh", "name": "Tanzanian Shilling",   "rate": 2600.0},
        "ZAR": {"symbol": "R",   "name": "South African Rand",   "rate": 18.50},
        "NGN": {"symbol": "₦",   "name": "Nigerian Naira",       "rate": 1500.0},
        "GHS": {"symbol": "GH₵", "name": "Ghanaian Cedi",        "rate": 14.50},
        "RWF": {"symbol": "FRw", "name": "Rwandan Franc",        "rate": 1350.0},
    }
    CURRENCY_SESSION_KEY = "nexacart_currency"

    # --- weather (Stage 3: OpenWeather API) --------------------------
    # Set OPENWEATHER_API_KEY in the environment for live data. Without
    # a key the weather feature runs on clearly-labelled sample data.
    OPENWEATHER_API_KEY = os.environ.get("OPENWEATHER_API_KEY", "")

    # --- Flutterwave (bonus: payment module) ------------------------
    # Set these in the environment for real transactions. When the secret
    # key is missing the service falls back to a simulated payment flow so
    # the checkout can still be demonstrated end to end.
    FLUTTERWAVE_PUBLIC_KEY = os.environ.get(
        "FLUTTERWAVE_PUBLIC_KEY", "FLWPUBK_TEST-d5d4370dcc3dd09abce9f230e3b36029-X"
    )
    FLUTTERWAVE_SECRET_KEY = os.environ.get("FLUTTERWAVE_SECRET_KEY", "")
    FLUTTERWAVE_ENCRYPTION_KEY = os.environ.get("FLUTTERWAVE_ENCRYPTION_KEY", "")
    FLUTTERWAVE_BASE_URL = os.environ.get(
        "FLUTTERWAVE_BASE_URL", "https://api.flutterwave.com/v3"
    )
    FLUTTERWAVE_SANDBOX = _env_flag("FLUTTERWAVE_SANDBOX", True)

    # --- localisation ------------------------------------------------
    DEFAULT_LOCALE = "en"
    SUPPORTED_LOCALES = ("en", "fr", "ar")

    # --- first-run administrator ------------------------------------
    SEED_ADMIN_USERNAME = os.environ.get("NEXACART_ADMIN_USERNAME", "admin")
    SEED_ADMIN_EMAIL = os.environ.get("NEXACART_ADMIN_EMAIL", "admin@nexacart.local")
    SEED_ADMIN_PASSWORD = os.environ.get("NEXACART_ADMIN_PASSWORD", "Admin@12345")
    SEED_ADMIN_NAME = "Platform Administrator"


class TestingConfig(DefaultConfig):
    TESTING = True
    DATABASE = str(INSTANCE_DIR / "nexacart_test.db")
    WTF_CSRF_ENABLED = False
    SEED_ADMIN_PASSWORD = "Admin@12345"
    # Keep the test suite fast; production uses the stronger default above.
    PASSWORD_HASH_METHOD = "pbkdf2:sha256:10000"


class ProductionConfig(DefaultConfig):
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True
    PREFERRED_URL_SCHEME = "https"


CONFIG_MAP = {
    "default": DefaultConfig,
    "development": DefaultConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
