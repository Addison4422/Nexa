"""Stage 4: promotions.

SELLERS create 4-digit promo codes that give a percent off **their own
products** for a limited time (hours or days). Buyers browse live offers
on a promo page and apply a code at checkout; the discount is computed
per cart line, only on items from the seller who issued the code.
ADMINISTRATORS still create 'commission' offers that reduce what a chosen
account (or everyone) pays on the whole order.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    url_for,
    abort,
)

from .. import models, security
from ..i18n import t
from ..security import roles_required

promo_bp = Blueprint("promo", __name__, url_prefix="/promo")

_CODE_RE = re.compile(r"^\d{4}$")


def _parse_duration(value: str, unit: str) -> timedelta | None:
    try:
        amount = int(value)
    except (TypeError, ValueError):
        return None
    if amount < 1:
        return None
    if unit == "days":
        if amount > 30:
            return None
        return timedelta(days=amount)
    if unit == "hours":
        if amount > 720:
            return None
        return timedelta(hours=amount)
    return None


# ---------------------------------------------------------------------
# Seller area: create and manage codes for their own products
# ---------------------------------------------------------------------
@promo_bp.route("/manage")
@roles_required("seller", "admin")
def manage():
    user = security.current_user()
    promos = models.list_promos(
        created_by=user["id"] if user["role"] == "seller" else None,
        kind="discount",
    )
    products = models.list_products(
        active_only=False,
        seller_id=user["id"] if user["role"] == "seller" else None,
    )
    return render_template("promo/manage.html", promos=promos, products=products,
                           promo_max=models.PROMO_MAX_PERCENT)


@promo_bp.route("/create", methods=["POST"])
@roles_required("seller", "admin")
def create():
    user = security.current_user()
    code = (request.form.get("code") or "").strip()
    percent = request.form.get("percent", type=int)
    duration = request.form.get("duration", type=int) or 0
    unit = request.form.get("unit") or "days"

    if not _CODE_RE.match(code):
        flash(t("promo.err_code_format"), "error")
        return redirect(url_for("promo.manage"))
    if percent is None or not (1 <= percent <= models.PROMO_MAX_PERCENT):
        flash(t("promo.err_percent", max=models.PROMO_MAX_PERCENT), "error")
        return redirect(url_for("promo.manage"))

    delta = _parse_duration(str(duration), unit)
    if delta is None:
        flash(t("promo.err_duration"), "error")
        return redirect(url_for("promo.manage"))

    if models.find_promo(code, include_used=True) is not None:
        flash(t("promo.err_code_taken"), "error")
        return redirect(url_for("promo.manage"))

    expires_at = (
        datetime.now(timezone.utc) + delta
    ).strftime("%Y-%m-%d %H:%M:%S")

    models.create_promo(
        code=code, kind="discount", percent=percent,
        created_by=user["id"], target_user_id=None, expires_at=expires_at,
    )
    models.log_audit(
        "promo_created", user["id"], user["username"],
        f"seller code={code} percent={percent} unit={unit} length={duration}",
        security.client_ip(),
    )
    flash(t("promo.flash_created", code=code, percent=percent), "success")
    return redirect(url_for("promo.manage"))


@promo_bp.route("/<int:promo_id>/update", methods=["POST"])
@roles_required("seller", "admin")
def update(promo_id: int):
    """Update an existing (live) promo code: new percent and/or a new
    expiry. Sellers may only update their own codes; admins may update
    any discount code.
    """
    user = security.current_user()
    promo = models.find_promo_by_id(promo_id)
    if promo is None:
        abort(404)
    if user["role"] != "admin" and promo["created_by"] != user["id"]:
        abort(403)
    percent = request.form.get("percent", type=int)
    duration = request.form.get("duration", type=int) or 0
    unit = request.form.get("unit") or "days"
    if percent is None or not (1 <= percent <= models.PROMO_MAX_PERCENT):
        flash(t("promo.err_percent", max=models.PROMO_MAX_PERCENT), "error")
        return redirect(url_for("promo.manage"))
    delta = _parse_duration(str(duration), unit)
    if delta is None:
        flash(t("promo.err_duration"), "error")
        return redirect(url_for("promo.manage"))
    expires_at = (
        datetime.now(timezone.utc) + delta
    ).strftime("%Y-%m-%d %H:%M:%S")
    models.update_promo(
        promo_id, created_by=user["id"] if user["role"] == "seller" else None,
        percent=percent, expires_at=expires_at,
    )
    models.log_audit(
        "promo_updated", user["id"], user["username"],
        f"promo={promo_id} percent={percent} unit={unit} length={duration}",
        security.client_ip(),
    )
    flash(t("promo.flash_updated", code=promo["code"]), "success")
    return redirect(url_for("promo.manage"))

@promo_bp.route("/<int:promo_id>/delete", methods=["POST"])
@roles_required("seller", "admin")
def delete(promo_id: int):
    user = security.current_user()
    if models.delete_promo(promo_id, created_by=user["id"]):
        models.log_audit(
            "promo_deleted", user["id"], user["username"],
            f"promo={promo_id}", security.client_ip(),
        )
        flash(t("promo.flash_deleted"), "success")
    return redirect(url_for("promo.manage"))


# ---------------------------------------------------------------------
# Buyer area: browse live offers (no code creation for buyers)
# ---------------------------------------------------------------------
@promo_bp.route("/")
def offers():
    """Live product discounts from sellers, visible to everyone."""
    discounted = models.list_discounted_products(limit=12)
    return render_template("promo/offers.html", discounted=discounted)
