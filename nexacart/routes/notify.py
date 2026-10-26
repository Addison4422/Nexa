"""In-app notifications: list, acknowledge."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, request, url_for

from .. import models, security
from ..i18n import t
from ..security import login_required

notify_bp = Blueprint("notify", __name__)


@notify_bp.route("/notifications/<int:notification_id>/acknowledge", methods=["POST"])
@login_required
def acknowledge(notification_id: int):
    user = security.current_user()
    ok = models.acknowledge_notification(user["id"], notification_id)
    if not ok:
        flash(t("notify.not_found"), "error")
    # Stay where the user was instead of jumping to the account page.
    target = (security.safe_next_url(request.form.get("next"))
              or security.safe_next_url(request.args.get("next"))
              or request.referrer)
    return redirect(target or url_for("main.index"))


@notify_bp.route("/role-offer/<int:notification_id>/accept", methods=["POST"])
@login_required
def accept_role_offer(notification_id: int):
    user = security.current_user()
    notification = models.get_notification(user["id"], notification_id)
    if notification is None or not str(notification["kind"]).startswith("role_offer:"):
        flash(t("notify.not_found"), "error")
        return redirect(url_for("account.profile"))

    offered = str(notification["kind"]).split(":", 1)[1]
    if offered not in models.ALL_ROLES:
        flash(t("notify.not_found"), "error")
        return redirect(url_for("account.profile"))

    models.update_user_role(user["id"], offered)
    models.acknowledge_notification(user["id"], notification_id)
    models.log_audit(
        "role_accepted", user["id"], user["username"], f"accepted {offered}",
        security.client_ip(),
    )
    flash(t("flash.role_accepted", role=t(f"role.{offered}")), "success")
    return redirect(url_for("account.profile"))


@notify_bp.route("/role-offer/<int:notification_id>/decline", methods=["POST"])
@login_required
def decline_role_offer(notification_id: int):
    user = security.current_user()
    notification = models.get_notification(user["id"], notification_id)
    if notification is None or not str(notification["kind"]).startswith("role_offer:"):
        flash(t("notify.not_found"), "error")
        return redirect(url_for("account.profile"))

    models.acknowledge_notification(user["id"], notification_id)
    models.log_audit(
        "role_declined", user["id"], user["username"], None,
        security.client_ip(),
    )
    flash(t("flash.role_declined"), "success")
    return redirect(url_for("account.profile"))
