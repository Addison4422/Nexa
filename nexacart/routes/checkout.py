"""Checkout and payment (Stage 2 bonus: Flutterwave integration).

A buyer checks out their cart, an order is created and payment is
initialised with Flutterwave. When no Flutterwave credentials are
configured the flow falls back to a simulated payment so the checkout can
still be demonstrated end to end.
"""

from __future__ import annotations

import secrets
import time
from urllib.parse import urlencode

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from .. import models, security
from ..i18n import t
from ..payments import initialize_payment, verify_transaction
from ..security import roles_required

checkout_bp = Blueprint("checkout", __name__, url_prefix="/checkout")


@checkout_bp.before_request
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


def _cart_value_cents(lines: list[dict]) -> int:
    total = 0
    for line in lines:
        price = int(line["price_cents"])
        if line["discount_percent"]:
            price = int(round(price * (100 - int(line["discount_percent"])) / 100))
        total += price * int(line["quantity"])
    return total


def _promo_discount_cents(lines: list[dict], promo) -> int:
    """Cents off for a valid promo row.

    Seller 'discount' codes only discount the lines that belong to the
    seller who issued the code (the buyer pays less).
    Admin 'commission' codes do NOT change what the buyer pays — they cut
    the platform commission owed on this order, recorded on the order.
    """
    if promo is None:
        return 0
    percent = int(promo["percent"])
    if promo["kind"] == "commission":
        return 0  # buyer pays full price; commission relief recorded separately
    # seller code: only that seller's items
    subtotal = 0
    for line in lines:
        if int(line["seller_id"]) != int(promo["created_by"]):
            continue
        price = int(line["price_cents"])
        if line["discount_percent"]:
            price = int(round(price * (100 - int(line["discount_percent"])) / 100))
        subtotal += price * int(line["quantity"])
    return int(round(subtotal * percent / 100))


def _checkout_promo(user):
    """The promo stored in the session for this checkout, still valid."""
    promo_id = session.get("checkout_promo")
    if not promo_id:
        return None
    promo = models.find_promo_by_id(promo_id)
    if promo is None or not models.promo_visible_to(promo, user["id"]):
        session.pop("checkout_promo", None)
        return None
    return promo


@checkout_bp.route("/")
def index():
    user = security.current_user()
    lines = models.get_cart(user["id"])
    if not lines:
        flash(t("checkout.flash.empty_cart"), "warning")
        return redirect(url_for("cart.view"))

    currency = session.get("currency", "USD")
    rate = float(current_app.config["CURRENCIES"][currency]["rate"])
    subtotal_cents = _cart_value_cents(lines)
    promo = _checkout_promo(user)
    promo_cents = _promo_discount_cents(lines, promo)
    total_cents = max(0, subtotal_cents - promo_cents)
    # amounts are stored in base currency (USD) cents; converted for display
    amount_usd_cents = round(total_cents / rate)
    amount_display = round(amount_usd_cents * rate / 100, 2)

    return render_template(
        "checkout/index.html",
        lines=lines,
        cart=_cart_totals(lines, currency),
        subtotal_cents=subtotal_cents,
        promo=promo,
        promo_cents=promo_cents,
        amount_usd_cents=amount_usd_cents,
        amount_display=amount_display,
        currency=currency,
    )


@checkout_bp.route("/promo", methods=["POST"])
def apply_promo():
    """Validate a promo code and remember it for this checkout."""
    code = (request.form.get("code") or "").strip()
    user = security.current_user()
    next_url = url_for("checkout.index")
    if request.form.get("remove"):
        session.pop("checkout_promo", None)
        flash(t("checkout.promo_removed"), "success")
        return redirect(next_url)
    if not code:
        session.pop("checkout_promo", None)
        return redirect(next_url)

    promo = models.find_promo(code)
    if promo is None or promo["kind"] == "commission" and promo["target_user_id"] not in (None, user["id"]):
        flash(t("promo.err_invalid"), "error")
        return redirect(next_url)

    session["checkout_promo"] = promo["id"]
    flash(t("promo.flash_applied", code=promo["code"], percent=promo["percent"]), "success")
    return redirect(next_url)


@checkout_bp.route("/promo/remove", methods=["POST"])
def remove_promo():
    session.pop("checkout_promo", None)
    return redirect(url_for("checkout.index"))


def _cart_totals(lines: list[dict], currency: str) -> dict:
    items = []
    subtotal = 0
    for line in lines:
        price = int(line["price_cents"])
        qty = int(line["quantity"])
        line_subtotal = price * qty
        subtotal += line_subtotal
        items.append(
            {
                "cart_id": line["cart_id"],
                "product": {
                    "id": line["product_id"],
                    "name": line["name"],
                    "image_path": line["image_path"],
                },
                "quantity": qty,
                "price_cents": price,
                "subtotal_cents": line_subtotal,
            }
        )
    return {"items": items, "subtotal_cents": subtotal, "currency": currency}


@checkout_bp.route("/pay", methods=["POST"])
def pay():
    user = security.current_user()
    lines = models.get_cart(user["id"])
    if not lines:
        flash(t("checkout.flash.empty_cart"), "warning")
        return redirect(url_for("cart.view"))

    payment_method = (request.form.get("payment_method") or "card").strip()
    if payment_method not in ("mtn_momo", "airtel_money", "card"):
        payment_method = "card"

    currency = session.get("currency", "USD")
    rate = float(current_app.config["CURRENCIES"][currency]["rate"])
    subtotal_cents = _cart_value_cents(lines)
    promo = _checkout_promo(user)
    promo_cents = _promo_discount_cents(lines, promo)
    total_cents = max(0, subtotal_cents - promo_cents)
    amount_usd_cents = round(total_cents / rate)

    reference = f"NX{int(time.time())}{secrets.randbelow(100000):05d}"

    order_id = models.create_order(
        buyer_id=user["id"],
        reference=reference,
        currency=currency,
        amount_cents=amount_usd_cents,
        payment_method=payment_method,
        commission_relief_percent=(
            promo["percent"] if promo is not None and promo["kind"] == "commission" else 0
        ),
        lines=[
            {
                "product_id": line["product_id"],
                "name": line["name"],
                "price_cents": round(int(line["price_cents"]) / rate),
                "currency": currency,
                "quantity": int(line["quantity"]),
                "subtotal_cents": round(int(line["price_cents"]) * int(line["quantity"]) / rate),
            }
            for line in lines
        ],
    )

    from .. import payments

    config = current_app.config
    redirect_url = url_for(
        "checkout.callback", reference=reference, _external=True
    )

    # Inline mode: a public key is configured (no secret key). The buyer's
    # browser opens Flutterwave's hosted payment modal and we verify on the
    # redirect back. The modal opens on the method the buyer chose.
    if payments.inline_configured():
        # Pass exactly ONE payment option so Flutterwave's hosted modal opens
        # directly on the method the buyer chose (MTN -> MoMo, Airtel ->
        # Airtel Money, card -> card) instead of always defaulting to card.
        method_options = {
            "mtn_momo": "mobilemoneyrwanda",
            "airtel_money": "mobilemoneyrwanda",
            "card": "card",
        }
        session["pending_order"] = order_id
        return render_template(
            "payment/inline.html",
            order=models.get_order(order_id),
            reference=reference,
            amount=amount_usd_cents / 100,
            currency="USD",
            customer_email=user["email"],
            customer_name=user["full_name"],
            redirect_url=redirect_url,
            payment_options=method_options.get(payment_method, "card"),
            public_key=config.get("FLUTTERWAVE_PUBLIC_KEY", ""),
        )

    try:
        result = initialize_payment(
            reference=reference,
            amount=amount_usd_cents / 100,
            currency="USD",
            customer_email=user["email"],
            customer_name=user["full_name"],
            redirect_url=redirect_url,
            narration=f"NEXACART order {reference}",
        )
    except Exception as error:  # network or configuration trouble -> simulation
        current_app.logger.warning("Flutterwave initialisation failed: %s", error)
        result = {"simulated": True, "simulate_url": f"/payment/simulate/{reference}"}

    if result.get("simulated"):
        session["pending_order"] = order_id
        if promo is not None:
            models.mark_promo_used(promo["id"], user["id"])
            session.pop("checkout_promo", None)
        return redirect(url_for("checkout.simulate", reference=reference,
                                method=payment_method))

    session["pending_order"] = order_id
    if promo is not None:
        models.mark_promo_used(promo["id"], user["id"])
        session.pop("checkout_promo", None)
    return redirect(result["checkout_url"])


@checkout_bp.route("/callback")
def callback():
    """Flutterwave redirect back after payment."""
    reference = request.args.get("reference") or request.args.get("tx_ref")
    order = models.get_order_by_reference(reference) if reference else None
    if order is None or order["buyer_id"] != security.current_user()["id"]:
        abort(404)
    if order["status"] == "paid":
        return redirect(url_for("checkout.success", reference=reference))

    transaction_id = request.args.get("transaction_id") or reference
    from .. import payments
    if payments._flutterwave_configured():
        try:
            result = verify_transaction(transaction_id)
        except Exception as error:
            current_app.logger.warning("Flutterwave verification failed: %s", error)
            result = {"paid": False, "status": "error"}
    else:
        # Inline mode (public key only): Flutterwave redirected back with the
        # status in the query string; trust the hosted checkout's redirect.
        status = (request.args.get("status") or "").lower()
        result = {"paid": status == "successful",
                  "status": status or "unknown"}

    if result.get("paid"):
        models.mark_order_paid(reference, str(transaction_id))
        _fulfill_order(order["id"])
        flash(t("checkout.flash.payment_success"), "success")
        return redirect(url_for("checkout.success", reference=reference))

    flash(t("checkout.flash.payment_failed"), "error")
    return redirect(url_for("checkout.index"))


@checkout_bp.route("/success")
def success():
    reference = request.args.get("reference")
    order = models.get_order_by_reference(reference) if reference else None
    if order is None or order["buyer_id"] != security.current_user()["id"]:
        abort(404)
    return render_template("checkout/success.html", order=order, lines=models.order_lines(order["id"]))


# ---------------------------------------------------------------------
# Simulated payment (demo mode only)
# ---------------------------------------------------------------------


PAYMENT_METHODS = {
    "mtn_momo": {"label": "MTN Mobile Money", "phone_label": "MTN number", "prefix": "+2507"},
    "airtel_money": {"label": "Airtel Money", "phone_label": "Airtel number", "prefix": "+2507"},
    "card": {"label": "Card", "phone_label": None, "prefix": None},
}


@checkout_bp.route("/payment/simulate/<reference>")
@security.login_required
def simulate(reference: str):
    order = models.get_order_by_reference(reference)
    if order is None or order["buyer_id"] != security.current_user()["id"]:
        abort(404)
    if order["status"] == "paid":
        return redirect(url_for("checkout.success", reference=reference))
    method_key = request.args.get("method", order["payment_method"] or "card")
    method = PAYMENT_METHODS.get(method_key, PAYMENT_METHODS["card"])
    return render_template("payment/simulate.html", order=order,
                           method_key=method_key, method=method)


@checkout_bp.route("/payment/simulate/<reference>/confirm", methods=["POST"])
@security.login_required
def simulate_confirm(reference: str):
    order = models.get_order_by_reference(reference)
    if order is None or order["buyer_id"] != security.current_user()["id"]:
        abort(404)
    if order["status"] != "pending":
        return redirect(url_for("checkout.success", reference=reference))

    method_key = (request.form.get("payment_method") or order["payment_method"] or "card")
    method = PAYMENT_METHODS.get(method_key, PAYMENT_METHODS["card"])

    # Mobile money simulation requires a phone number; card simulation
    # requires the card fields to be filled in. This mirrors a real
    # payment screen so the flow feels authentic.
    if method["phone_label"]:
        phone = (request.form.get("phone") or "").strip()
        digits = phone.replace(" ", "").replace("-", "")
        if not digits.startswith("+") or not digits[1:].isdigit() or len(digits) < 12:
            flash(t("err.phone_invalid"), "error")
            return redirect(url_for("checkout.simulate", reference=reference,
                                    method=method_key))
        # Simulate the operator confirmation (would be a PIN prompt on the
        # phone in reality).
        models.mark_order_paid(reference, f"{method_key}:{digits}")
    else:
        card_number = (request.form.get("card_number") or "").strip().replace(" ", "")
        expiry = (request.form.get("expiry") or "").strip()
        cvv = (request.form.get("cvv") or "").strip()
        if not card_number.isdigit() or not (12 <= len(card_number) <= 19):
            flash(t("err.card_number_invalid"), "error")
            return redirect(url_for("checkout.simulate", reference=reference,
                                    method=method_key))
        if not cvv.isdigit() or len(cvv) < 3:
            flash(t("err.card_cvv_invalid"), "error")
            return redirect(url_for("checkout.simulate", reference=reference,
                                    method=method_key))
        # Only store the last 4 digits, never the full number.
        models.mark_order_paid(reference, f"card:****{card_number[-4:]}")

    _fulfill_order(order["id"])
    flash(t("checkout.flash.payment_success"), "success")
    return redirect(url_for("checkout.success", reference=reference))


def _fulfill_order(order_id: int) -> None:
    """Decrease reserved stock and clear the buyer's cart once paid."""
    order = models.get_order(order_id)
    if order is None:
        return
    buyer_id = order["buyer_id"]
    for line in models.order_lines(order_id):
        models.reserve_stock(line["product_id"], int(line["quantity"]))
    models.clear_cart(buyer_id)
    models.notify_sellers_of_sale(order_id)
    models.log_audit(
        "order_paid", buyer_id, None,
        f"order={order_id} reference={order['reference']}",
    )
