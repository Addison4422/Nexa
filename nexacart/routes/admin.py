"""Administrator area: platform management, user administration, audit log."""

from __future__ import annotations

import math
import secrets
import re
from datetime import datetime, timezone

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from .. import models, security
from ..i18n import t

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.before_request
def restrict_to_administrators():
    """Server side RBAC gate for the whole administrator area."""
    user = security.current_user()
    if user is None:
        flash(t("flash.sign_in_required"), "warning")
        return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
    if user["role"] != "admin":
        models.log_audit(
            "access_denied",
            user["id"],
            user["username"],
            f"{request.method} {request.path} requires admin",
            security.client_ip(),
        )
        return (
            render_template(
                "errors/403.html", required_roles=("admin",), user_role=user["role"]
            ),
            403,
        )


def _pagination(total: int, page: int, per_page: int) -> dict:
    pages = max(1, math.ceil(total / per_page)) if per_page else 1
    page = min(max(page, 1), pages)
    start = (page - 1) * per_page + 1 if total else 0
    end = min(page * per_page, total)
    return {
        "page": page,
        "pages": pages,
        "per_page": per_page,
        "total": total,
        "start": start,
        "end": end,
        "has_prev": page > 1,
        "has_next": page < pages,
    }


@admin_bp.route("/")
def dashboard():
    stats = models.user_statistics()
    sessions_count = models.count_active_sessions()
    failures = models.count_recent_failures_all(24 * 60 * 60)
    successes = models.count_recent_successes_all(24 * 60 * 60)
    recent_users = models.query_db("SELECT * FROM users ORDER BY created_at DESC, id DESC LIMIT 5")
    recent_activity = models.list_audit_log(8)
    pending_approvals = models.count_pending_approval()
    fee_percent = current_app.config["PLATFORM_FEE_PERCENT"]
    txn_stats = models.platform_transaction_stats(fee_percent)
    recent_transactions = models.platform_transactions(limit=10)

    max_role = max(stats["by_role"].values()) if stats["by_role"] else 0
    role_bars = [
        {
            "role": role,
            "count": count,
            "percent": int(round((count / max_role) * 100)) if max_role else 0,
        }
        for role, count in stats["by_role"].items()
    ]

    return render_template(
        "admin/dashboard.html",
        stats=stats,
        sessions_count=sessions_count,
        failures=failures,
        successes=successes,
        recent_users=recent_users,
        recent_activity=recent_activity,
        role_bars=role_bars,
        pending_approvals=pending_approvals,
        txn_stats=txn_stats,
        recent_transactions=recent_transactions,
        fee_percent=fee_percent,
    )


@admin_bp.route("/users")
def users():
    search = (request.args.get("q") or "").strip()
    role = (request.args.get("role") or "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = current_app.config["ITEMS_PER_PAGE"]

    rows, total = models.list_users(search=search, role=role, page=page, per_page=per_page)
    pagination = _pagination(total, page, per_page)
    return render_template(
        "admin/users.html",
        users=rows,
        pagination=pagination,
        search=search,
        role=role,
    )


@admin_bp.route("/users/<int:user_id>")
def user_detail(user_id: int):
    target = models.get_user_by_id(user_id)
    if target is None:
        abort(404)
    return render_template(
        "admin/user_detail.html",
        target=target,
        user_sessions=models.list_user_sessions(user_id),
        activity=models.recent_audit_for_user(user_id, 10),
    )


@admin_bp.route("/users/<int:user_id>/role", methods=["POST"])
def change_role(user_id: int):
    admin = security.current_user()
    target = models.get_user_by_id(user_id)
    if target is None:
        abort(404)

    new_role = (request.form.get("role") or "").strip()
    if new_role not in models.ALL_ROLES:
        flash(t("flash.unknown_role"), "error")
        return redirect(url_for("admin.user_detail", user_id=user_id))

    if target["id"] == admin["id"]:
        flash(t("flash.self_role"), "error")
        return redirect(url_for("admin.user_detail", user_id=user_id))

    if target["role"] == "admin" and new_role != "admin":
        if models.count_active_admin_users() <= 1:
            flash(t("flash.last_admin_role"), "error")
            return redirect(url_for("admin.user_detail", user_id=user_id))

    if new_role == "admin":
        # Promoting an account to administrator is a high risk action:
        # the administrator must confirm it with their own password.
        current_password = request.form.get("current_password") or ""
        if not current_password or not security.verify_password(
            admin["password_hash"], current_password
        ):
            flash(t("admin.admin_password_required"), "error")
            return redirect(url_for("admin.user_detail", user_id=user_id))
        models.update_user_role(user_id, new_role)
        models.create_notification(
            user_id,
            "role_changed",
            t("notify.role_changed", role=t("role.admin")),
        )
        models.log_audit(
            "role_changed",
            admin["id"],
            admin["username"],
            f"{target['username']}: {target['role']} -> {new_role} (password confirmed)",
            security.client_ip(),
        )
        flash(
            t("flash.role_changed", name=target["username"], role=t("role.admin")),
            "success",
        )
        return redirect(url_for("admin.user_detail", user_id=user_id))

    # Buyer <-> seller: the target account decides. The change only takes
    # effect after the person accepts it from their own account.
    models.create_notification(
        user_id,
        f"role_offer:{new_role}",
        t("notify.role_offer", role=t(f"role.{new_role}")),
    )
    models.log_audit(
        "role_offer",
        admin["id"],
        admin["username"],
        f"{target['username']}: offered {new_role}",
        security.client_ip(),
    )
    flash(t("flash.role_offer_sent", name=target["username"]), "success")
    return redirect(url_for("admin.user_detail", user_id=user_id))

@admin_bp.route("/users/<int:user_id>/status", methods=["POST"])
def change_status(user_id: int):
    admin = security.current_user()
    target = models.get_user_by_id(user_id)
    if target is None:
        abort(404)

    new_status = (request.form.get("status") or "").strip()
    if new_status not in ("active", "suspended"):
        flash(t("flash.unknown_status"), "error")
        return redirect(url_for("admin.user_detail", user_id=user_id))

    if target["id"] == admin["id"] and new_status == "suspended":
        flash(t("flash.self_suspend"), "error")
        return redirect(url_for("admin.user_detail", user_id=user_id))

    if target["role"] == "admin" and new_status == "suspended":
        if models.count_active_admin_users() <= 1:
            flash(t("flash.last_admin_suspend"), "error")
            return redirect(url_for("admin.user_detail", user_id=user_id))

    models.set_user_status(user_id, new_status)
    if new_status == "suspended":
        models.delete_user_sessions(user_id)
    models.log_audit(
        "status_changed",
        admin["id"],
        admin["username"],
        f"{target['username']}: {target['status']} -> {new_status}",
        security.client_ip(),
    )
    if new_status == "suspended":
        flash(
            t("flash.status_changed_extra", name=target["username"], status=t(f"status.{new_status}")),
            "success",
        )
    else:
        flash(
            t("flash.status_changed", name=target["username"], status=t(f"status.{new_status}")),
            "success",
        )
    return redirect(url_for("admin.user_detail", user_id=user_id))


@admin_bp.route("/requests")
def pending_requests():
    """One hub: account approvals, password resets and payout requests."""
    return render_template(
        "admin/pending_requests.html",
        approvals=models.list_pending_approval(),
        resets=models.pending_password_resets(),
        payouts=models.all_payouts(),
        pending_complaints=models.pending_complaints(),
    )


@admin_bp.route("/approvals")
def approvals():
    """Accounts registered by the public that still await approval."""
    return render_template("admin/approvals.html", pending=models.list_pending_approval())


@admin_bp.route("/users/<int:user_id>/resend-pin", methods=["POST"])
def resend_pin(user_id: int):
    """Resend a 6-digit reset code (PIN) to an existing account's email.

    The administrator picks an existing account; a fresh code replaces any
    previous one and is delivered exactly like the public forgot-password
    flow delivers it: by email when SMTP is configured, otherwise shown on
    screen (demo mode). The account owner then completes the reset.
    """
    admin = security.current_user()
    target = models.get_user_by_id(user_id)
    if target is None:
        abort(404)
    models.purge_password_codes(target["id"])
    code = f"{secrets.randbelow(1000000):06d}"
    models.create_password_code(target["id"], models.hash_token(code))
    models.log_audit(
        "password_code_resent", admin["id"], admin["username"],
        f"for={target['username']} ({target['role']})", security.client_ip(),
    )
    sent = False
    try:
        from .. import mailer
        sent = mailer.send(
            target["email"],
            f"{current_app.config['APP_NAME']} password reset code",
            t("mail.reset_code_body", name=target["full_name"], code=code),
        )
    except Exception as error:
        current_app.logger.warning("reset email failed: %s", error)
    if sent:
        flash(t("flash.reset_code_sent", email=target["email"]), "info")
    else:
        flash(t("flash.reset_code_demo", code=code), "warning")
    return redirect(url_for("admin.password_resets"))

@admin_bp.route("/users/<int:user_id>/decision", methods=["POST"])
def user_decision(user_id: int):
    """Approve or reject a pending account from the approvals page form."""
    decision = request.form.get("decision") or "approve"
    if decision == "reject":
        return reject_user(user_id)
    return approve_user(user_id)

@admin_bp.route("/users/<int:user_id>/approve", methods=["POST"])
def approve_user(user_id: int):
    """Approve a pending account. Requires the admin's password."""
    admin = security.current_user()
    target = models.get_user_by_id(user_id)
    if target is None:
        abort(404)

    current_password = request.form.get("current_password") or ""
    if not current_password or not security.verify_password(admin["password_hash"], current_password):
        flash(t("admin.admin_password_required"), "error")
        return redirect(url_for("admin.approvals"))

    if target["role"] == "buyer":
        flash(t("errors.action_not_allowed"), "error")
        return redirect(url_for("admin.approvals"))
    models.set_user_approved(user_id, True)
    models.create_notification(
        user_id,
        "account_approved",
        t("notify.account_approved"),
    )
    models.log_audit(
        "account_approved",
        admin["id"],
        admin["username"],
        f"{target['username']} ({target['role']})",
        security.client_ip(),
    )
    flash(t("flash.account_approved", name=target["username"]), "success")
    return redirect(url_for("admin.approvals"))


@admin_bp.route("/users/<int:user_id>/reject", methods=["POST"])
def reject_user(user_id: int):
    """Reject (suspend) a pending account. Requires the admin's password."""
    admin = security.current_user()
    target = models.get_user_by_id(user_id)
    if target is None:
        abort(404)

    current_password = request.form.get("current_password") or ""
    if not current_password or not security.verify_password(admin["password_hash"], current_password):
        flash(t("admin.admin_password_required"), "error")
        return redirect(url_for("admin.approvals"))

    if target["role"] == "buyer":
        flash(t("errors.action_not_allowed"), "error")
        return redirect(url_for("admin.approvals"))
    models.set_user_status(user_id, "suspended")
    models.set_user_approved(user_id, False)
    models.delete_user_sessions(user_id)
    models.create_notification(
        user_id,
        "account_rejected",
        t("notify.account_rejected"),
    )
    models.log_audit(
        "account_rejected",
        admin["id"],
        admin["username"],
        f"{target['username']} ({target['role']})",
        security.client_ip(),
    )
    flash(t("flash.account_rejected", name=target["username"]), "success")
    return redirect(url_for("admin.approvals"))


@admin_bp.route("/password-resets")
def password_resets():
    """Accounts with a pending password reset request."""
    return render_template(
        "admin/password_resets.html",
        pending=models.pending_password_resets(),
    )


@admin_bp.route("/password-resets/<int:user_id>/issue", methods=["POST"])
def issue_password_reset(user_id: int):
    """Create a fresh reset link for the user and show it to the admin."""
    token = models.create_admin_password_reset(user_id)
    if token is None:
        abort(404)
    user = models.get_user_by_id(user_id)
    models.log_audit(
        "password_reset_issued",
        security.current_user()["id"],
        security.current_user()["username"],
        f"for={user['username']}",
        security.client_ip(),
    )
    link = url_for("auth.reset_password", token=token, _external=True)
    flash(t("flash.reset_link_issued"), "success")
    return render_template(
        "admin/password_resets.html",
        pending=models.pending_password_resets(),
        issued_link=link,
        issued_user=user["username"],
    )


@admin_bp.route("/payouts/<int:payout_id>/process", methods=["POST"])
def process_payout(payout_id: int):
    """Approve (mark paid) or reject a seller payout request."""
    admin = security.current_user()
    status = (request.form.get("decision") or "").strip()
    note = (request.form.get("note") or "").strip()
    if models.process_payout(payout_id, admin["id"], status, note):
        models.log_audit(
            "payout_processed", admin["id"], admin["username"],
            f"payout={payout_id} status={status}", security.client_ip(),
        )
        flash(t("flash.payout_processed", status=t(f"payouts.{status}")), "success")
    else:
        flash(t("flash.unknown_status"), "error")
    return redirect(url_for("seller.earnings"))


@admin_bp.route("/complaints")
def complaints():
    """User complaints for review."""
    return render_template("admin/complaints.html", complaints=models.all_complaints())


@admin_bp.route("/complaints/<int:complaint_id>/resolve", methods=["POST"])
def resolve_complaint(complaint_id: int):
    """Mark a complaint done with feedback for the reporter."""
    admin = security.current_user()
    feedback = (request.form.get("feedback") or "").strip()
    if not feedback:
        flash(t("err.complaint_feedback"), "error")
        return redirect(url_for("admin.complaints"))
    if models.resolve_complaint(complaint_id, admin["id"], feedback):
        models.log_audit(
            "complaint_resolved", admin["id"], admin["username"],
            f"complaint={complaint_id}", security.client_ip(),
        )
        flash(t("flash.complaint_resolved"), "success")
    else:
        flash(t("notify.not_found"), "error")
    return redirect(url_for("admin.complaints"))


@admin_bp.route("/audit")
def audit():
    page = request.args.get("page", 1, type=int)
    per_page = 25
    total = models.count_audit_entries()
    rows = models.list_audit_log(limit=per_page, offset=(max(page, 1) - 1) * per_page)
    pagination = _pagination(total, page, per_page)
    return render_template("admin/audit.html", entries=rows, pagination=pagination)


@admin_bp.route("/sessions")
def sessions():
    return render_template("admin/sessions.html", sessions_rows=models.list_all_sessions(200))

@admin_bp.route("/promos")
def promos():
    """Commission offers: reduce cost for one account or for everyone."""
    users, _total = models.list_users(per_page=200)
    rows = models.active_admin_promos()
    # commission relief only makes sense for accounts that sell
    sellers = [u for u in users if u["role"] in ("seller", "admin")]
    return render_template("admin/promos.html", promos=rows, users=sellers,
                           promo_max=models.PROMO_MAX_PERCENT)


@admin_bp.route("/promos/create", methods=["POST"])
def create_promo():
    """Send a commission-reduction promo to a chosen account or everyone."""
    admin = security.current_user()
    code = (request.form.get("code") or "").strip()
    percent = request.form.get("percent", type=int)
    duration = request.form.get("duration", type=int) or 0
    unit = request.form.get("unit") or "days"
    target = request.form.get("target") or "all"  # 'all' or a user id

    from .promo import _parse_duration

    if not re.fullmatch(r"\d{4}", code or ""):
        flash(t("promo.err_code_format"), "error")
        return redirect(url_for("admin.promos"))
    if percent is None or not (1 <= percent <= models.PROMO_MAX_PERCENT):
        flash(t("promo.err_percent", max=models.PROMO_MAX_PERCENT), "error")
        return redirect(url_for("admin.promos"))
    delta = _parse_duration(str(duration), unit)
    if delta is None:
        flash(t("promo.err_duration"), "error")
        return redirect(url_for("admin.promos"))

    target_user_id = None
    if target != "all":
        target_user_id = int(target)
        if models.get_user_by_id(target_user_id) is None:
            flash(t("notify.not_found"), "error")
            return redirect(url_for("admin.promos"))

    expires_at = (
        datetime.now(timezone.utc) + delta
    ).strftime("%Y-%m-%d %H:%M:%S")

    if models.find_promo(code) is not None:
        flash(t("promo.err_code_taken"), "error")
        return redirect(url_for("admin.promos"))

    models.create_promo(
        code=code, kind="commission", percent=percent,
        created_by=admin["id"], target_user_id=target_user_id,
        expires_at=expires_at,
    )
    if target_user_id:
        models.create_notification(
            target_user_id, "promo",
            t("notify.promo_targeted", code=code, percent=percent),
        )
        models.log_audit(
            "promo_created", admin["id"], admin["username"],
            f"commission code={code} percent={percent} target={target_user_id}",
            security.client_ip(),
        )
    else:
        models.log_audit(
            "promo_created", admin["id"], admin["username"],
            f"commission code={code} percent={percent} target=all",
            security.client_ip(),
        )
    flash(t("promo.flash_created", code=code, percent=percent), "success")
    return redirect(url_for("admin.promos"))


@admin_bp.route("/promos/<int:promo_id>/delete", methods=["POST"])
def delete_promo(promo_id: int):
    if models.delete_promo(promo_id):
        models.log_audit(
            "promo_deleted", security.current_user()["id"],
            security.current_user()["username"], f"promo={promo_id}",
            security.client_ip(),
        )
        flash(t("promo.flash_deleted"), "success")
    return redirect(url_for("admin.promos"))