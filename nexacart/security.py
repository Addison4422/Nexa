"""Security layer: password hashing, validation, CSRF, sessions, RBAC.

Design notes for the HCI project report
---------------------------------------
* Passwords are stored as salted PBKDF2-SHA256 digests (never plain text).
* The browser only receives an **opaque random token**; the database keeps
  only its SHA-256 digest, so a stolen database cannot be replayed.
* Authentication state lives **server side** (SQLite), which allows
  "sign out everywhere" and per-device revocation.
* Every state changing request is protected by a signed CSRF token.
* Role checks are applied on the **server**, not only hidden in the UI.
"""

from __future__ import annotations

import hmac
import re
import secrets
import time
from functools import wraps
from typing import Any, Callable, Iterable

from flask import (
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from . import models
from .i18n import t

# ---------------------------------------------------------------------
# Constants & patterns
# ---------------------------------------------------------------------
ROLES = models.ALL_ROLES

USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._]{2,24}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")
NAME_RE = re.compile(r"^[^\d\W][\w' -]{1,79}$", re.UNICODE)

ROLE_HOME_ENDPOINT = {
    "admin": "admin.dashboard",
    "seller": "seller.dashboard",
    "buyer": "buyer.dashboard",
}

CSRF_SESSION_KEY = "_csrf_token"

# Stable identifiers of the password rules. The wording is translated, the
# identifier is not, so the browser can check a rule in every language.
PASSWORD_RULES = (
    ("min_length", True),
    ("max_length", True),
    ("lowercase", True),
    ("uppercase", True),
    ("digit", True),
    ("symbol", False),
)


# ---------------------------------------------------------------------
# Password handling
# ---------------------------------------------------------------------
def hash_password(password: str) -> str:
    method = current_app.config["PASSWORD_HASH_METHOD"]
    return generate_password_hash(password, method=method)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return check_password_hash(password_hash, password)
    except (ValueError, TypeError):
        return False


def password_rule_state(password: str) -> list[dict]:
    """Return the state of every password rule for the checklist."""
    minimum = current_app.config["PASSWORD_MIN_LENGTH"]
    maximum = current_app.config["PASSWORD_MAX_LENGTH"]
    checks = {
        "min_length": len(password) >= minimum,
        "max_length": len(password) <= maximum,
        "lowercase": any(c.islower() for c in password),
        "uppercase": any(c.isupper() for c in password),
        "digit": any(c.isdigit() for c in password),
        "symbol": any(not c.isalnum() for c in password),
    }
    return [
        {"id": rule_id, "passed": checks[rule_id], "required": required}
        for rule_id, required in PASSWORD_RULES
    ]


def password_rule_label(rule_id: str) -> str:
    """The translated wording of a password rule."""
    minimum = current_app.config["PASSWORD_MIN_LENGTH"]
    maximum = current_app.config["PASSWORD_MAX_LENGTH"]
    if rule_id == "min_length":
        return t("rule.min_length", n=minimum)
    if rule_id == "max_length":
        return t("rule.max_length", n=maximum)
    return t(f"rule.{rule_id}")


def password_problems(password: str) -> list[str]:
    """Identifiers of the still-unsatisfied (and required) password rules."""
    return [
        rule["id"]
        for rule in password_rule_state(password)
        if rule["required"] and not rule["passed"]
    ]


# ---------------------------------------------------------------------
# Field validation (returns a cleaned value or an error message)
# ---------------------------------------------------------------------
def validate_username(value: str) -> tuple[str | None, str | None]:
    value = (value or "").strip()
    if not value:
        return None, t("err.username_required")
    if len(value) < 3:
        return None, t("err.username_short")
    if len(value) > 25:
        return None, t("err.username_long")
    if not USERNAME_RE.match(value):
        return None, t("err.username_format")
    if models.username_taken(value):
        return None, t("err.username_taken")
    return value, None


def validate_email(value: str, exclude_id: int | None = None) -> tuple[str | None, str | None]:
    value = (value or "").strip().lower()
    if not value:
        return None, t("err.email_required")
    if len(value) > 254:
        return None, t("err.email_long")
    if not EMAIL_RE.match(value):
        return None, t("err.email_format")
    if models.email_taken(value, exclude_id):
        return None, t("err.email_taken")
    return value, None


def validate_full_name(value: str) -> tuple[str | None, str | None]:
    value = (value or "").strip()
    if not value:
        return None, t("err.name_required")
    if len(value) < 2:
        return None, t("err.name_short")
    if len(value) > 80:
        return None, t("err.name_long")
    if not NAME_RE.match(value):
        return None, t("err.name_format")
    return value, None


def validate_password(password: str, confirm: str | None = None) -> tuple[str | None, str | None]:
    if not password:
        return None, t("err.password_required")
    problems = password_problems(password)
    if problems:
        wording = ", ".join(
            _lower_first(password_rule_label(rule_id)) for rule_id in problems
        )
        return None, t("err.password_rules", rules=wording)
    if confirm is not None and password != confirm:
        return None, t("err.password_mismatch")
    return password, None


def _lower_first(text: str) -> str:
    """Lower the first letter so a rule fits into a sentence."""
    return text[:1].lower() + text[1:] if text else text


# ---------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------
def client_ip() -> str | None:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr


def current_user():
    return getattr(g, "user", None)


def is_authenticated() -> bool:
    return current_user() is not None


def is_admin() -> bool:
    user = current_user()
    return bool(user and user["role"] == "admin")


def role_home(user) -> str:
    endpoint = ROLE_HOME_ENDPOINT.get(user["role"] if user else "", "main.index")
    return url_for(endpoint)


def safe_next_url(target: str | None) -> str | None:
    """Only allow same-site relative redirects (blocks open redirects)."""
    if not target:
        return None
    if target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return None


# ---------------------------------------------------------------------
# CSRF protection
# ---------------------------------------------------------------------
def generate_csrf_token() -> str:
    token = session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_SESSION_KEY] = token
    return token


def validate_csrf_token(token: str | None) -> bool:
    expected = session.get(CSRF_SESSION_KEY)
    if not expected or not token:
        return False
    return hmac.compare_digest(str(expected), str(token))


# ---------------------------------------------------------------------
# Server-side authentication sessions
# ---------------------------------------------------------------------
def issue_session_cookie(response, token: str, remember: bool):
    config = current_app.config
    max_age = config["SESSION_REMEMBER_TIMEOUT"] if remember else None
    response.set_cookie(
        config["AUTH_COOKIE_NAME"],
        token,
        httponly=config["SESSION_COOKIE_HTTPONLY"],
        secure=config["SESSION_COOKIE_SECURE"],
        samesite=config["SESSION_COOKIE_SAMESITE"],
        max_age=max_age,
        path="/",
    )
    return response


def clear_session_cookie(response):
    response.delete_cookie(
        current_app.config["AUTH_COOKIE_NAME"],
        path="/",
    )
    return response


def start_auth_session(user, remember: bool = False) -> str:
    """Create a brand new server-side session and return the raw token."""
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    config = current_app.config
    if remember:
        expires_at = now + config["SESSION_REMEMBER_TIMEOUT"]
    else:
        expires_at = now + config["SESSION_ABSOLUTE_TIMEOUT"]
    models.create_auth_session(
        models.hash_token(token),
        user["id"],
        expires_at,
        remember,
        client_ip(),
        (request.headers.get("User-Agent") or "")[:255],
    )
    return token


def end_auth_session(token_hash: str | None = None) -> None:
    if token_hash is None:
        token_hash = getattr(g, "session_token_hash", None)
    if token_hash:
        models.delete_auth_session(token_hash)


def load_current_user() -> None:
    """Populate ``g.user`` from the server-side session store."""
    g.user = None
    g.auth_session = None
    g.session_token_hash = None

    config = current_app.config
    token = request.cookies.get(config["AUTH_COOKIE_NAME"])
    if not token:
        return

    row = models.get_auth_session(models.hash_token(token))
    if row is None:
        return

    now = int(time.time())
    if row["expires_at"] <= now:
        models.delete_auth_session(row["token_hash"])
        return

    user = models.get_user_by_id(row["user_id"])
    if user is None or user["status"] != "active":
        models.delete_auth_session(row["token_hash"])
        return

    remember = bool(row["remember_me"])
    absolute_expiry = row["created_at"] + config["SESSION_ABSOLUTE_TIMEOUT"]
    idle_limit = config["SESSION_IDLE_TIMEOUT"]

    if not remember:
        if now - row["last_seen_at"] > idle_limit:
            models.delete_auth_session(row["token_hash"])
            return
        if now > absolute_expiry:
            models.delete_auth_session(row["token_hash"])
            return
        new_expiry = min(absolute_expiry, now + idle_limit)
    else:
        new_expiry = row["expires_at"]

    models.touch_auth_session(row["id"], now, new_expiry)
    g.user = user
    g.auth_session = row
    g.session_token_hash = row["token_hash"]


# ---------------------------------------------------------------------
# View decorators (role based access control)
# ---------------------------------------------------------------------
def login_required(view: Callable) -> Callable:
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not is_authenticated():
            flash(t("flash.sign_in_required"), "warning")
            target = request.full_path.rstrip("?") if request.method == "GET" else None
            return redirect(url_for("auth.login", next=target))
        return view(*args, **kwargs)

    return wrapped


def guest_only(view: Callable) -> Callable:
    @wraps(view)
    def wrapped(*args, **kwargs):
        if is_authenticated():
            flash(
                t("flash.already_signed_in", username=current_user()["username"]),
                "info",
            )
            return redirect(role_home(current_user()))
        return view(*args, **kwargs)

    return wrapped


def roles_required(*roles: str) -> Callable:
    """Allow only the listed roles; everyone else receives a 403 page."""
    allowed = tuple(roles)

    def decorator(view: Callable) -> Callable:
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if user is None:
                flash(t("flash.sign_in_required"), "warning")
                target = request.full_path.rstrip("?") if request.method == "GET" else None
                return redirect(url_for("auth.login", next=target))
            if user["role"] not in allowed:
                models.log_audit(
                    "access_denied",
                    user["id"],
                    user["username"],
                    f"{request.method} {request.path} requires {', '.join(allowed)}",
                    client_ip(),
                )
                return (
                    render_template(
                        "errors/403.html",
                        required_roles=allowed,
                        user_role=user["role"],
                    ),
                    403,
                )
            return view(*args, **kwargs)

        return wrapped

    return decorator


def admin_required(view: Callable) -> Callable:
    return roles_required("admin")(view)


# ---------------------------------------------------------------------
# Navigation helper
# ---------------------------------------------------------------------
def nav_items(user) -> list[dict[str, Any]]:
    """Navigation entries; ``label`` holds the translation key."""
    items: list[dict[str, Any]] = [
        {"label": "nav.weather", "endpoint": "weather.search", "icon": "sun"},
    ]
    if not user:
        return items
    role = user["role"]
    if role == "admin":
        items.append({"label": "nav.dashboard", "endpoint": "admin.dashboard", "icon": "gauge"})
        items.append({"label": "nav.users", "endpoint": "admin.users", "icon": "users"})
        items.append({"label": "nav.requests", "endpoint": "admin.pending_requests", "icon": "clock"})
        items.append({"label": "nav.activity", "endpoint": "admin.audit", "icon": "shield"})
        items.append({"label": "nav.weather_history", "endpoint": "weather.admin_history", "icon": "sun"})
        items.append({"label": "nav.promos", "endpoint": "admin.promos", "icon": "tag"})
    elif role == "seller":
        items.append({"label": "nav.dashboard", "endpoint": "seller.dashboard", "icon": "gauge"})
        items.append({"label": "nav.orders", "endpoint": "seller.orders", "icon": "cart"})
        items.append({"label": "nav.promos", "endpoint": "promo.manage", "icon": "tag"})
        items.append({"label": "nav.earnings", "endpoint": "seller.earnings", "icon": "currency"})
    else:
        items.append({"label": "nav.shop", "endpoint": "buyer.dashboard", "icon": "shop"})
        items.append({"label": "nav.offers", "endpoint": "promo.offers", "icon": "tag"})
        items.append({"label": "nav.transactions", "endpoint": "buyer.transactions", "icon": "list"})
    return items


def menu_items(user) -> list[dict[str, Any]]:
    """Secondary menu (behind the ⋯ button): secondary destinations."""
    if not user:
        return [{"label": "nav.about", "endpoint": "main.about", "icon": "info"}]
    items: list[dict[str, Any]] = []
    if user["role"] == "admin":
        items.append({"label": "nav.complaints", "endpoint": "admin.complaints", "icon": "alert"})
    elif user["role"] == "seller":
        items.append({"label": "nav.transactions", "endpoint": "seller.transactions", "icon": "list"})
        items.append({"label": "nav.complaints", "endpoint": "account.complaints", "icon": "alert"})
    else:
        items.append({"label": "nav.complaints", "endpoint": "account.complaints", "icon": "alert"})
        items.append({"label": "nav.favourites", "endpoint": "product.favorites", "icon": "heart"})
    items.append({"label": "nav.about", "endpoint": "main.about", "icon": "info"})
    items.append({"label": "nav.account", "endpoint": "account.profile", "icon": "user"})
    items.append({"label": "nav.settings", "endpoint": "account.settings", "icon": "settings"})
    return items


def header_badges(user) -> dict[str, int]:
    """Pending counts shown as red badges in the header."""
    from . import models

    if not user:
        return {}
    badges: dict[str, int] = {}
    notifications = len(models.list_notifications(user["id"], unacknowledged_only=True))
    if notifications:
        badges["bell"] = notifications
    if user["role"] == "admin":
        pending = (
            models.count_pending_approval()
            + models.count_pending_password_resets()
            + models.count_pending_payouts()
            + models.count_pending_complaints()
        )
        if pending:
            badges["requests"] = pending
    return badges


# Capability identifiers shown on the role dashboards.
PERMISSIONS: dict[str, tuple[str, ...]] = {
    "admin": ("admin_platform", "admin_security", "admin_catalogue"),
    "seller": ("seller_workspace", "seller_stockin", "seller_no_cart"),
    "buyer": ("buyer_catalogue", "buyer_cart", "buyer_no_stockin"),
}


def permissions_for(role: str) -> Iterable[str]:
    """Identifiers of the capabilities a role has."""
    return PERMISSIONS.get(role, ())
