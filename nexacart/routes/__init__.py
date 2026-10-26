"""Blueprint registry for NEXACART."""

from __future__ import annotations

from .account import account_bp
from .admin import admin_bp
from .auth import auth_bp
from .buyer import buyer_bp
from .cart import cart_bp
from .checkout import checkout_bp
from .main import main_bp
from .notify import notify_bp
from .product import product_bp
from .promo import promo_bp
from .seller import seller_bp
from .weather import weather_bp

ALL_BLUEPRINTS = (
    main_bp,
    notify_bp,
    auth_bp,
    account_bp,
    admin_bp,
    seller_bp,
    buyer_bp,
    product_bp,
    promo_bp,
    cart_bp,
    checkout_bp,
    weather_bp,
)

__all__ = [
    "account_bp",
    "admin_bp",
    "auth_bp",
    "buyer_bp",
    "cart_bp",
    "checkout_bp",
    "main_bp",
    "notify_bp",
    "product_bp",
    "promo_bp",
    "seller_bp",
    "weather_bp",
    "ALL_BLUEPRINTS",
]
