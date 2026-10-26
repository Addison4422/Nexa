"""Shopping cart for buyers (Stage 2).

Persistent server side cart: survives page changes and browser refreshes.
Every endpoint is buyer-only.
"""

from __future__ import annotations

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from .. import models, security
from ..i18n import t
from ..security import roles_required

cart_bp = Blueprint("cart", __name__, url_prefix="/cart")


@cart_bp.before_request
def restrict_to_buyers():
    user = security.current_user()
    if user is None:
        flash(t("flash.sign_in_required"), "warning")
        return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
    if user["role"] != "buyer":
        models.log_audit(
            "access_denied", user["id"], user["username"],
            f"{request.method} {request.path} requires buyer", security.client_ip(),
        )
        return (
            render_template(
                "errors/403.html", required_roles=("buyer",), user_role=user["role"]
            ),
            403,
        )


def _money(cents: int, currency: str) -> str:
    info = current_app.config["CURRENCIES"].get(currency, current_app.config["CURRENCIES"]["USD"])
    rate = float(info["rate"])
    amount = (cents / 100) * rate
    return f"{info['symbol']}{amount:,.2f}"


def _cart_totals(lines: list[dict], currency: str) -> dict:
    items = []
    subtotal = 0
    for line in lines:
        price = int(line["price_cents"])
        discount = int(line["discount_percent"] or 0)
        effective = int(round(price * (100 - discount) / 100)) if discount else price
        qty = int(line["quantity"])
        line_subtotal = effective * qty
        subtotal += line_subtotal
        items.append(
            {
                "cart_id": line["cart_id"],
                "product": {
                    "id": line["product_id"],
                    "name": line["name"],
                    "image_path": line["image_path"],
                    "image_url": (
                        url_for("product.product_image", filename=line["image_path"])
                        if line["image_path"] else ""
                    ),
                    "stock_quantity": line["stock_quantity"],
                    "seller": (line["seller_business"] or line["seller_username"] or ""),
                },
                "quantity": qty,
                "price_cents": effective,
                "list_price_cents": price if discount else None,
                "discount_percent": discount,
                "price_display": _money(effective, currency),
                "list_price_display": _money(price, currency) if discount else "",
                "subtotal_cents": line_subtotal,
                "subtotal_display": _money(line_subtotal, currency),
                "at_limit": qty >= int(line["stock_quantity"]),
            }
        )
    return {
        "items": items,
        "subtotal_cents": subtotal,
        "subtotal_display": _money(subtotal, currency),
        "currency": currency,
    }


@cart_bp.route("/")
def view():
    user = security.current_user()
    lines = models.get_cart(user["id"])
    currency = session.get("currency", "USD")
    cart = _cart_totals(lines, currency)
    # promo entered on this page applies before checkout
    promo = None
    promo_cents = 0
    promo_id = session.get("checkout_promo")
    if promo_id:
        promo = models.find_promo_by_id(promo_id)
        if promo is not None and promo["kind"] == "discount":
            promo_cents = int(round(cart["subtotal_cents"] * int(promo["percent"]) / 100))
        else:
            promo = None
    return render_template("cart/view.html", cart=cart, promo=promo,
                           promo_cents=promo_cents)


@cart_bp.route("/add", methods=["POST"])
def add():
    user = security.current_user()
    product_id = request.form.get("product_id", type=int)
    quantity = request.form.get("quantity", default=1, type=int)
    if not product_id or quantity < 1:
        return jsonify(ok=False, error=t("cart.err.quantity_invalid")), 400

    ok, error_key = models.add_to_cart(user["id"], product_id, quantity)
    if not ok:
        return jsonify(ok=False, error=t(error_key)), 400

    count = models.cart_count(user["id"])
    product = models.get_product(product_id)
    return jsonify(
        ok=True,
        cart_count=count,
        message=t("cart.flash.added", name=product["name"] if product else "item"),
    )


@cart_bp.route("/<int:cart_id>/update", methods=["POST"])
def update(cart_id: int):
    user = security.current_user()
    quantity = request.form.get("quantity", type=int)
    if quantity is None or quantity < 1:
        return jsonify(ok=False, error=t("cart.err.quantity_invalid")), 400

    ok, error_key = models.update_cart_quantity(user["id"], cart_id, quantity)
    if not ok:
        return jsonify(ok=False, error=t(error_key)), 400

    lines = models.get_cart(user["id"])
    currency = session.get("currency", "USD")
    return jsonify(ok=True, cart=_cart_totals(lines, currency))


@cart_bp.route("/<int:cart_id>/remove", methods=["POST"])
def remove(cart_id: int):
    user = security.current_user()
    removed = models.remove_cart_item(user["id"], cart_id)
    if not removed:
        return jsonify(ok=False, error=t("cart.err.cart_item_not_found")), 404

    lines = models.get_cart(user["id"])
    currency = session.get("currency", "USD")
    return jsonify(
        ok=True,
        cart=_cart_totals(lines, currency),
        cart_count=models.cart_count(user["id"]),
    )


@cart_bp.route("/clear", methods=["GET", "POST"])
def clear():
    user = security.current_user()
    models.clear_cart(user["id"])
    flash(t("cart.flash.cleared"), "info")
    return redirect(url_for("cart.view"))
