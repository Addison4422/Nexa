"""NEXACART - Human-Computer Interaction project.

User management, authentication, role based access control and a
multi-language interface (English, French, Arabic).
Application factory lives here; the blueprint for each role lives in
``nexacart.routes``.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from flask import (
    Flask,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from .config import CONFIG_MAP, INSTANCE_DIR
from .db import init_app as init_db_app
from .i18n import (
    available_locales,
    detect_locale,
    format_datetime,
    format_epoch,
    format_number,
    get_locale,
    is_rtl,
    locale_direction,
    t,
    time_ago,
)
from .routes import ALL_BLUEPRINTS
from . import models, security, utils

__all__ = ["create_app"]


def create_app(config_name: str | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)

    name = config_name or os.environ.get("NEXACART_ENV", "default")
    config_class = CONFIG_MAP.get(name, CONFIG_MAP["default"])
    app.config.from_object(config_class)
    app.config["NEXACART_ENV"] = name

    Path(INSTANCE_DIR).mkdir(parents=True, exist_ok=True)
    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    app.config["SECRET_KEY"] = _resolve_secret_key(app)

    _register_blueprints(app)
    _register_database(app)
    _register_request_hooks(app)
    _register_template_helpers(app)
    _register_error_handlers(app)

    return app


# ---------------------------------------------------------------------
def _resolve_secret_key(app: Flask) -> str:
    """Use the environment key, otherwise keep a generated one on disk.

    A stable key is required so that sessions and CSRF tokens survive a
    restart of the development server.
    """
    env_key = os.environ.get("NEXACART_SECRET_KEY")
    if env_key:
        return env_key

    key_file = Path(app.config["SECRET_KEY_FILE"])
    if key_file.exists():
        stored = key_file.read_text(encoding="utf-8").strip()
        if stored:
            return stored

    key_file.parent.mkdir(parents=True, exist_ok=True)
    generated = secrets.token_hex(32)
    key_file.write_text(generated, encoding="utf-8")
    app.logger.warning(
        "NEXACART: generated a new SECRET_KEY in %s. Set NEXACART_SECRET_KEY "
        "before deploying to production.",
        key_file,
    )
    return generated


# ---------------------------------------------------------------------
def _register_blueprints(app: Flask) -> None:
    for blueprint in ALL_BLUEPRINTS:
        app.register_blueprint(blueprint)


def _register_database(app: Flask) -> None:
    init_db_app(app)
    with app.app_context():
        from .db import init_db

        init_db()
        if models.db_is_empty():
            models.create_user(
                username=app.config["SEED_ADMIN_USERNAME"],
                email=app.config["SEED_ADMIN_EMAIL"],
                full_name=app.config["SEED_ADMIN_NAME"],
                password_hash=security.hash_password(app.config["SEED_ADMIN_PASSWORD"]),
                role="admin",
                must_change_password=1,
            )
            app.logger.warning(
                "NEXACART: first-run administrator created - username '%s' / password '%s'. "
                "The password must be changed at first sign-in.",
                app.config["SEED_ADMIN_USERNAME"],
                app.config["SEED_ADMIN_PASSWORD"],
            )


# ---------------------------------------------------------------------
def _register_request_hooks(app: Flask) -> None:
    @app.before_request
    def _load_user():
        security.load_current_user()

    @app.before_request
    def _resolve_locale():
        """Pick the language of the request (session first, browser second)."""
        stored = session.get("locale")
        if stored:
            g.locale = stored
            return
        detected = detect_locale(request.headers.get("Accept-Language"))
        g.locale = detected
        if request.endpoint != "static":
            session["locale"] = detected

    @app.before_request
    def _enforce_csrf():
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
            if not security.validate_csrf_token(token):
                return (
                    render_template(
                        "errors/400.html",
                        reason=t("errors.bad_request_default"),
                    ),
                    400,
                )

    @app.before_request
    def _force_password_change():
        user = security.current_user()
        if not user or not user["must_change_password"]:
            return None
        allowed = {"account.security_settings", "auth.logout", "static"}
        if request.endpoint and request.endpoint not in allowed:
            flash(t("flash.password_required"), "warning")
            return redirect(url_for("account.security_settings"))
        return None

    @app.after_request
    def _security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
        )
        # Flutterwave inline checkout needs its script, inline bootstrap and
        # payment iframes; frame-src/frame-ancestors stay strict elsewhere.
        if request.endpoint == "checkout.pay":
            csp = (
                "default-src 'self'; img-src 'self' data: https:; "
                "style-src 'self' 'unsafe-inline'; "
                "script-src 'self' 'unsafe-inline' https://checkout.flutterwave.com; "
                "font-src 'self'; form-action 'self' https://*.flutterwave.com; "
                "frame-src https://checkout.flutterwave.com https://checkout-v3.flutterwave.com https://*.flw.pmx.ng; "
                "connect-src 'self' https://api.flutterwave.com https://api.ravepay.co; "
                "base-uri 'self'; frame-ancestors 'none'"
            )
        else:
            csp = (
                "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                "script-src 'self'; font-src 'self'; form-action 'self'; base-uri 'self'; "
                "frame-ancestors 'none'"
            )
        response.headers.setdefault("Content-Security-Policy", csp)
        if request.endpoint == "static":
            response.headers.setdefault("Cache-Control", "public, max-age=3600")
        elif security.current_user() is not None:
            response.headers.setdefault("Cache-Control", "no-store")
        return response


# ---------------------------------------------------------------------
def _audit_label(action: str) -> str:
    """Translated name of an audit action, with a readable fallback."""
    key = f"audit.{action}"
    text = t(key)
    if text == key:
        return action.replace("_", " ").title()
    return text


def _register_template_helpers(app: Flask) -> None:
    @app.context_processor
    def inject_globals():
        user = security.current_user()
        locale = get_locale()
        cart_count = 0
        if user and user["role"] == "buyer":
            cart_count = models.cart_count(user["id"])
        notifications = []
        pending_requests = 0
        unack_count = 0
        if user:
            unack = models.list_notifications(user["id"], unacknowledged_only=True)
            notifications = [dict(row) for row in unack]
            unack_count = len(notifications)
            if user["role"] == "admin":
                pending_requests = (
                    models.count_pending_approval()
                    + models.count_pending_password_resets()
                    + models.count_pending_payouts()
                    + models.count_pending_complaints()
                )
        return {
            "current_user": user,
            "is_authenticated": user is not None,
            "csrf_token": security.generate_csrf_token,
            "nav_items": security.nav_items(user),
            "role_labels": {role: t(f"role.{role}") for role in models.ALL_ROLES},
            "audit_label": _audit_label,
            "cart_count": cart_count,
            "password_rules": [
                {
                    "id": rule_id,
                    "label": security.password_rule_label(rule_id),
                    "required": required,
                }
                for rule_id, required in security.PASSWORD_RULES
            ],
            "password_min": app.config["PASSWORD_MIN_LENGTH"],
            "password_max": app.config["PASSWORD_MAX_LENGTH"],
            "t": t,
            "locale": locale,
            "locale_direction": locale_direction(locale),
            "is_rtl": is_rtl(locale),
            "locales": available_locales(),
            "app_name": app.config["APP_NAME"],
            "app_version": app.config["APP_VERSION"],
            "currencies": app.config["CURRENCIES"],
            "base_currency": app.config["BASE_CURRENCY"],
            "current_currency": session.get("currency", app.config["BASE_CURRENCY"]),
            "flutterwave_configured": bool(app.config.get("FLUTTERWAVE_SECRET_KEY")),
            "notifications": notifications,
            "pending_requests": pending_requests,
            "unack_count": unack_count,
            "menu_items": security.menu_items(user),
        }

    def _money(cents: int | None) -> str:
        """Format stored USD cents in the visitor's chosen currency."""
        currency = session.get("currency", app.config["BASE_CURRENCY"])
        info = app.config["CURRENCIES"].get(currency, app.config["CURRENCIES"]["USD"])
        rate = float(info["rate"])
        amount = ((cents or 0) / 100) * rate
        return f"{info['symbol']}{amount:,.2f}"

    app.jinja_env.filters["datetime"] = format_datetime
    app.jinja_env.filters["epoch"] = format_epoch
    app.jinja_env.filters["ago"] = time_ago
    app.jinja_env.filters["number"] = format_number
    app.jinja_env.filters["money"] = _money
    app.jinja_env.filters["device"] = utils.device_label
    app.jinja_env.filters["role_css"] = utils.role_css_class
    app.jinja_env.filters["role_label"] = lambda role: t(f"role.{role}")

    def _promo_live(expires_at: str) -> bool:
        """True when a promo code is still within its lifetime."""
        try:
            return str(expires_at) > utils.utc_now_str()
        except Exception:
            return False

    app.jinja_env.filters["promo_live"] = _promo_live

    def _discounted_price(product) -> int:
        """Effective price in cents after the seller's product discount."""
        try:
            percent = int(product["discount_percent"] or 0)
        except (KeyError, TypeError, IndexError):
            percent = 0
        if not percent:
            return int(product["price_cents"])
        return int(round(int(product["price_cents"]) * (100 - percent) / 100))

    app.jinja_env.filters["after_discount"] = _discounted_price


# ---------------------------------------------------------------------
def _register_error_handlers(app: Flask) -> None:
    def _page(template: str, code: int, **context):
        return render_template(template, **context), code

    @app.errorhandler(400)
    def bad_request(error):
        # The technical description of the exception is not shown: the page
        # explains the problem in the language of the visitor.
        return _page("errors/400.html", 400, reason=t("errors.bad_request_default"))

    @app.errorhandler(403)
    def forbidden(error):
        return _page("errors/403.html", 403)

    @app.errorhandler(404)
    def not_found(error):
        return _page("errors/404.html", 404)

    @app.errorhandler(405)
    def method_not_allowed(error):
        return _page("errors/405.html", 405)

    @app.errorhandler(500)
    def server_error(error):  # pragma: no cover - defensive
        return _page("errors/500.html", 500)
