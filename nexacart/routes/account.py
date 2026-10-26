"""Account management for the signed-in user (any role)."""

from __future__ import annotations

from flask import (
    Blueprint,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from .. import models, security
from ..i18n import t
from ..security import login_required

account_bp = Blueprint("account", __name__, url_prefix="/account")


@account_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = security.current_user()
    form = {
        "full_name": user["full_name"],
        "email": user["email"],
    }
    errors: dict[str, str] = {}

    if request.method == "POST":
        form = {
            "full_name": (request.form.get("full_name") or "").strip(),
            "email": (request.form.get("email") or "").strip(),
        }
        email_changed = form["email"].lower() != user["email"].lower()

        name, error = security.validate_full_name(form["full_name"])
        if error:
            errors["full_name"] = error
        else:
            form["full_name"] = name

        email, error = security.validate_email(form["email"], exclude_id=user["id"])
        if error:
            errors["email"] = error
        else:
            form["email"] = email

        if email_changed:
            password = request.form.get("current_password") or ""
            if not password:
                errors["current_password"] = t("err.current_password_required")
            elif not security.verify_password(user["password_hash"], password):
                errors["current_password"] = t("err.current_password_wrong")

        if not errors:
            models.update_user_profile(user["id"], form["full_name"], form["email"])
            models.log_audit(
                "profile_updated", user["id"], user["username"], f"email={form['email']}",
                security.client_ip(),
            )
            flash(t("flash.profile_updated"), "success")
            return redirect(url_for("account.profile"))

        flash(t("flash.fix_fields"), "error")

    return render_template(
        "account/profile.html",
        form=form,
        errors=errors,
        user=user,
        activity=models.recent_audit_for_user(user["id"], 6),
    )


@account_bp.route("/security", methods=["GET", "POST"])
@login_required
def security_settings():
    """Change password and review / revoke active devices."""
    user = security.current_user()
    errors: dict[str, str] = {}

    if request.method == "POST":
        current = request.form.get("current_password") or ""
        new = request.form.get("new_password") or ""
        confirm = request.form.get("confirm_password") or ""

        if not security.verify_password(user["password_hash"], current):
            errors["current_password"] = t("err.current_password_wrong")
        else:
            clean, error = security.validate_password(new, confirm)
            if error:
                errors["new_password"] = error
            elif clean == current:
                errors["new_password"] = t("err.same_password")

        if not errors:
            models.update_user_password(user["id"], security.hash_password(new))
            removed = models.delete_user_sessions(
                user["id"], keep_token_hash=g.get("session_token_hash")
            )
            models.log_audit(
                "password_changed",
                user["id"],
                user["username"],
                f"other_sessions_ended={removed}",
                security.client_ip(),
            )
            if removed:
                flash(t("flash.password_changed_others", n=removed), "success")
            else:
                flash(t("flash.password_changed"), "success")
            return redirect(url_for("account.security_settings"))

        flash(t("flash.password_not_changed"), "error")

    sessions_rows = models.list_user_sessions(user["id"])
    return render_template(
        "account/security.html",
        errors=errors,
        user=user,
        sessions_rows=sessions_rows,
        current_hash=getattr(security.g, "session_token_hash", None),
    )


@account_bp.route("/sessions/<int:session_id>/revoke", methods=["POST"])
@login_required
def revoke_session(session_id: int):
    user = security.current_user()
    row = models.get_auth_session_by_id(session_id)
    if row is None or row["user_id"] != user["id"]:
        flash(t("flash.session_not_found"), "error")
        return redirect(url_for("account.security_settings"))

    models.delete_auth_session(row["token_hash"])
    models.log_audit(
        "session_revoked", user["id"], user["username"], f"session={session_id}",
        security.client_ip(),
    )
    flash(t("flash.session_revoked"), "success")
    return redirect(url_for("account.security_settings"))


@account_bp.route("/sessions/revoke-all", methods=["POST"])
@login_required
def revoke_all_sessions():
    user = security.current_user()
    current_hash = g.get("session_token_hash")
    removed = models.delete_user_sessions(user["id"], keep_token_hash=current_hash)
    models.log_audit(
        "sessions_revoked_all", user["id"], user["username"], f"removed={removed}",
        security.client_ip(),
    )
    flash(t("flash.sessions_revoked", n=removed), "success")
    return redirect(url_for("account.security_settings"))


@account_bp.route("/business", methods=["GET", "POST"])
@login_required
def business_profile():
    """Business / personal profile: name, description, country, phone."""
    user = security.current_user()
    form = {
        "business_name": user["business_name"],
        "business_description": user["business_description"],
        "country": user["country"],
        "phone_number": user["phone_number"],
    }
    errors: dict[str, str] = {}

    if request.method == "POST":
        form = {
            "business_name": (request.form.get("business_name") or "").strip(),
            "business_description": (request.form.get("business_description") or "").strip(),
            "country": (request.form.get("country") or "").strip(),
            "phone_number": (request.form.get("phone_number") or "").strip(),
        }

        if len(form["business_name"]) > 120:
            errors["business_name"] = t("err.business_name_long")
        if len(form["business_description"]) > 500:
            errors["business_description"] = t("err.business_description_long")
        if form["country"] and len(form["country"]) > 60:
            errors["country"] = t("err.country_long")
        if form["phone_number"]:
            digits = form["phone_number"].replace(" ", "").replace("-", "")
            if not digits.startswith("+") or not digits[1:].isdigit() or len(digits) < 8:
                errors["phone_number"] = t("err.phone_invalid")

        if not errors:
            models.update_business_profile(
                user["id"],
                form["business_name"],
                form["business_description"],
                form["country"],
                form["phone_number"],
            )
            models.log_audit(
                "business_profile_updated", user["id"], user["username"], None,
                security.client_ip(),
            )
            flash(t("flash.business_profile_updated"), "success")
            return redirect(url_for("account.business_profile"))

        flash(t("flash.fix_fields"), "error")

    return render_template(
        "account/business_profile.html",
        form=form,
        errors=errors,
        user=user,
    )


@account_bp.route("/complaints", methods=["GET", "POST"])
@login_required
def complaints():
    """Report a problem using preset categories; track its resolution."""
    user = security.current_user()
    if request.method == "POST":
        category = (request.form.get("category") or "").strip()
        detail = (request.form.get("detail") or "").strip()
        if category not in models.COMPLAINT_CATEGORIES:
            flash(t("err.complaint_category"), "error")
        else:
            models.create_complaint(user["id"], category, detail)
            models.log_audit(
                "complaint_filed", user["id"], user["username"],
                f"category={category}", security.client_ip(),
            )
            flash(t("flash.complaint_filed"), "success")
            return redirect(url_for("account.complaints"))

    return render_template(
        "account/complaints.html",
        categories=models.COMPLAINT_CATEGORIES,
        complaints=models.my_complaints(user["id"]),
    )


@account_bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    """Advanced settings: currency preference and dangerous actions."""
    user = security.current_user()
    currencies = current_app.config["CURRENCIES"]
    current_currency = session.get("currency", current_app.config["BASE_CURRENCY"])
    errors: dict[str, str] = {}

    if request.method == "POST":
        action = (request.form.get("action") or "").strip()

        if action == "currency":
            currency = (request.form.get("currency") or "").strip().upper()
            if currency not in currencies:
                errors["currency"] = t("err.unknown_currency")
            else:
                session["currency"] = currency
                flash(t("flash.currency_updated"), "success")
                return redirect(url_for("account.settings"))

        elif action == "delete_account":
            password = request.form.get("password") or ""
            confirm = request.form.get("delete_confirm")
            if not security.verify_password(user["password_hash"], password):
                errors["password"] = t("err.current_password_wrong")
            if not confirm:
                errors["confirm"] = t("err.delete_confirm_required")
            if not errors:
                models.delete_user_sessions(user["id"])
                models.execute_db("DELETE FROM users WHERE id = ?", (user["id"],))
                models.log_audit(
                    "account_deleted", user["id"], user["username"],
                    None, security.client_ip(),
                )
                security.end_auth_session()
                session.clear()
                flash(t("flash.account_deleted"), "success")
                return redirect(url_for("main.index"))

        if not errors:
            flash(t("flash.fix_fields"), "error")

    return render_template(
        "account/settings.html",
        user=user,
        currencies=currencies,
        current_currency=current_currency,
        errors=errors,
    )
