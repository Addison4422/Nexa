"""Seller area (sellers and administrators only)."""

from __future__ import annotations

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from .. import models, security
from ..i18n import t
from ..security import roles_required

seller_bp = Blueprint("seller", __name__, url_prefix="/seller")


@seller_bp.route("/")
@roles_required("admin", "seller")
def dashboard():
    user = security.current_user()
    if user["role"] == "admin":
        products = models.list_products(active_only=False)
        sales = models.seller_sales_stats()
    else:
        products = models.list_products(active_only=False, seller_id=user["id"])
        sales = models.seller_sales_stats(user["id"])
    stock_units = sum(int(p["stock_quantity"]) for p in products)
    low_stock = [p for p in products if int(p["stock_quantity"]) <= 5]
    out_of_stock = [p for p in products if int(p["stock_quantity"]) <= 0]
    return render_template(
        "seller/dashboard.html",
        user=user,
        permissions=security.permissions_for(user["role"]),
        products=products,
        product_count=len(products),
        stock_units=stock_units,
        sales=sales,
        low_stock=low_stock,
        out_of_stock=out_of_stock,
        low_stock_threshold=5,
        top_products=models.seller_top_products(None if user["role"] == "admin" else user["id"]),
    )


@seller_bp.route("/earnings", methods=["GET", "POST"])
@roles_required("admin", "seller")
def earnings():
    """Earnings dashboard: balance after the platform fee, payout requests."""
    user = security.current_user()
    fee_percent = current_app.config["PLATFORM_FEE_PERCENT"]
    seller_id = None if user["role"] == "admin" else user["id"]
    stats = models.seller_earnings(seller_id, fee_percent)

    if request.method == "POST" and seller_id is not None:
        amount_cents = request.form.get("amount", type=float)
        if amount_cents is None:
            flash(t("err.price_required"), "error")
        else:
            cents = int(round(amount_cents * 100))
            if models.request_payout(seller_id, cents, stats["available_cents"]):
                models.log_audit(
                    "payout_requested", user["id"], user["username"],
                    f"amount={cents}", security.client_ip(),
                )
                # Notify administrators to process the payout.
                for admin_row in models.query_db(
                    "SELECT id FROM users WHERE role = 'admin' AND status = 'active'"
                ):
                    models.create_notification(
                        admin_row["id"], "payout_request",
                        t("notify.payout_request", name=user["username"],
                          amount=f"{cents / 100:.2f}"),
                    )
                flash(t("flash.payout_requested"), "success")
            else:
                flash(t("err.payout_invalid"), "error")
        return redirect(url_for("seller.earnings"))

    payouts = models.seller_payouts(seller_id) if seller_id else models.all_payouts()
    # commission-relief codes this seller (or everyone) can currently use
    relief_promos = [p for p in models.active_promos_for_user(user["id"])
                     if p["kind"] == "commission"] if user["role"] == "seller" else []
    return render_template(
        "seller/earnings.html",
        stats=stats,
        fee_percent=fee_percent,
        payouts=payouts,
        is_admin=user["role"] == "admin",
        relief_promos=relief_promos,
    )


@seller_bp.route("/transactions")
@roles_required("admin", "seller")
def transactions():
    """Receipts: who bought what, when, and for how much."""
    user = security.current_user()
    seller_id = None if user["role"] == "admin" else user["id"]
    rows = models.seller_transactions(seller_id)
    return render_template("seller/transactions.html", rows=rows)


@seller_bp.route("/orders")
@roles_required("admin", "seller")
def orders():
    """Fulfillment view: paid orders the seller needs to ship."""
    user = security.current_user()
    seller_id = None if user["role"] == "admin" else user["id"]
    rows = models.seller_order_lines(seller_id)
    return render_template("seller/orders.html", rows=rows)


@seller_bp.route("/orders/<int:order_id>/fulfill", methods=["POST"])
@roles_required("admin", "seller")
def fulfill_order(order_id: int):
    user = security.current_user()
    status = (request.form.get("status") or "").strip()
    note = (request.form.get("note") or "").strip()
    if user["role"] != "admin" and not models.order_belongs_to_seller(order_id, user["id"]):
        flash(t("flash.session_not_found"), "error")
        return redirect(url_for("seller.orders"))
    if models.set_fulfillment(order_id, status, note):
        flash(t("flash.fulfillment_updated", status=t(f"fulfillment.{status}")), "success")
    else:
        flash(t("flash.unknown_status"), "error")
    return redirect(url_for("seller.orders"))
