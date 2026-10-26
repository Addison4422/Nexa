"""Buyer area (buyers only - sellers and administrators have no personal cart)."""

from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for

from .. import models, security
from ..security import roles_required

buyer_bp = Blueprint("buyer", __name__, url_prefix="/buyer")


@buyer_bp.route("/")
@roles_required("buyer")
def dashboard():
    user = security.current_user()
    products = models.list_products(active_only=True)[:6]
    cart_count = models.cart_count(user["id"])
    lines = models.get_cart(user["id"])
    cart_value = sum(int(line["price_cents"]) * int(line["quantity"]) for line in lines)
    orders = models.list_orders_paged(user["id"], limit=5)
    order_stats = models.buyer_order_stats(user["id"])
    return render_template(
        "buyer/dashboard.html",
        user=user,
        cart_count=cart_count,
        cart_value_cents=cart_value,
        orders=orders,
        order_stats=order_stats,
        permissions=security.permissions_for(user["role"]),
        products=products,
    )


@buyer_bp.route("/cart")
@roles_required("buyer")
def cart():
    """The shopping cart lives at /cart; this kept path redirects there."""
    return redirect(url_for("cart.view"))


@buyer_bp.route("/transactions")
@roles_required("buyer")
def transactions():
    """Full transaction history: every order with its payment status."""
    user = security.current_user()
    page = request.args.get("page", 1, type=int)
    per_page = 10
    total = models.count_orders(user["id"])
    pages = max(1, -(-total // per_page))
    page = min(max(page, 1), pages)
    orders = models.list_orders_paged(user["id"], limit=per_page, offset=(page - 1) * per_page)
    stats = models.buyer_order_stats(user["id"])
    return render_template(
        "buyer/transactions.html",
        orders=orders,
        stats=stats,
        page=page,
        pages=pages,
    )
