"""Registration, sign-in and sign-out."""

from __future__ import annotations

import hmac
import secrets
import time

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from .. import models, security
from ..i18n import get_locale, t
from ..security import guest_only, login_required

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def _clean(value: str | None) -> str:
    return (value or "").strip()
@auth_bp.route("/register", methods=["GET", "POST"])
@guest_only
def register():
    form = {
        "full_name": _clean(request.form.get("full_name")),
        "username": _clean(request.form.get("username")),
        "email": _clean(request.form.get("email")),
        "phone_number": _clean(request.form.get("phone_number")),
        "role": _clean(request.form.get("role")) or "buyer",
    }
    errors: dict[str, str] = {}

    if request.method == "POST":
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm_password") or ""
        terms = request.form.get("terms")

        if form["role"] not in models.PUBLIC_ROLES:
            form["role"] = "buyer"
            errors["role"] = t("err.role_choice")

        name, error = security.validate_full_name(form["full_name"])
        if error:
            errors["full_name"] = error
        else:
            form["full_name"] = name

        username, error = security.validate_username(form["username"])
        if error:
            errors["username"] = error
        else:
            form["username"] = username

        email, error = security.validate_email(form["email"])
        if error:
            errors["email"] = error
        else:
            form["email"] = email

        # Phone is optional but must be a valid international number when given.
        if form["phone_number"]:
            digits = form["phone_number"].replace(" ", "").replace("-", "")
            if not digits.startswith("+") or not digits[1:].isdigit() or len(digits) < 8:
                errors["phone_number"] = t("err.phone_invalid")
            else:
                form["phone_number"] = digits

        if not terms:
            errors["terms"] = t("err.terms")

        clean_password, error = security.validate_password(password, confirm)
        if error:
            errors["password"] = error

        if not errors:
            user_id = models.create_user(
                username=form["username"],
                email=form["email"],
                full_name=form["full_name"],
                password_hash=security.hash_password(clean_password),
                role=form["role"],
            )
            # Only seller accounts wait for administrator approval. Buyers
            # are approved immediately so they can log in right away.
            if form["role"] == "seller":
                models.set_user_approved(user_id, False)
            else:
                models.set_user_approved(user_id, True)
            if form["phone_number"]:
                models.update_business_profile(
                    user_id, "", "", "", form["phone_number"]
                )
            models.log_audit(
                "register_pending_approval",
                user_id,
                form["username"],
                f"role={form['role']}",
                security.client_ip(),
            )
            if form["role"] == "seller":
                flash(t("flash.register_pending"), "success")
            else:
                flash(t("flash.register_done"), "success")
            return redirect(url_for("auth.login"))

        flash(t("flash.fix_errors"), "error")

    return render_template("auth/register.html", form=form, errors=errors)


@auth_bp.route("/login", methods=["GET", "POST"])
@guest_only
def login():
    identifier = _clean(request.form.get("identifier"))
    remember = bool(request.form.get("remember_me"))
    errors: dict[str, str] = {}

    if request.method == "POST":
        password = request.form.get("password") or ""
        ip = security.client_ip()

        # --- IP level throttle (protects against credential stuffing) ---
        ip_failures = models.count_recent_ip_failures(
            ip, current_app.config["IP_ATTEMPT_WINDOW"]
        )
        if ip_failures >= current_app.config["IP_MAX_ATTEMPTS"]:
            models.record_login_attempt(identifier or "(empty)", ip, False, "ip_throttled")
            flash(t("flash.ip_throttled"), "error")
            return render_template(
                "auth/login.html", form={"identifier": identifier, "remember_me": remember},
                errors=errors,
            )

        user = models.get_user_by_identifier(identifier) if identifier else None

        if user is None:
            models.record_login_attempt(identifier or "(empty)", ip, False, "unknown_user")
            flash(t("flash.login_failed"), "error")
            return render_template(
                "auth/login.html", form={"identifier": identifier, "remember_me": remember},
                errors=errors,
            )

        now = int(time.time())
        if user["locked_until"] and user["locked_until"] > now:
            minutes = max(1, round((user["locked_until"] - now) / 60))
            models.record_login_attempt(identifier, ip, False, "locked")
            flash(t("flash.account_locked", n=minutes), "error")
            return render_template(
                "auth/login.html", form={"identifier": identifier, "remember_me": remember},
                errors=errors,
            )

        if user["status"] != "active":
            models.record_login_attempt(identifier, ip, False, "suspended")
            flash(t("flash.account_suspended"), "error")
            return render_template(
                "auth/login.html", form={"identifier": identifier, "remember_me": remember},
                errors=errors,
            )

        if not user["approved"]:
            models.record_login_attempt(identifier, ip, False, "pending_approval")
            flash(t("flash.account_pending"), "error")
            return render_template(
                "auth/login.html", form={"identifier": identifier, "remember_me": remember},
                errors=errors,
            )

        if not security.verify_password(user["password_hash"], password):
            models.record_failed_attempt(user["id"])
            models.record_login_attempt(identifier, ip, False, "bad_password")
            models.log_audit("login_failed", user["id"], user["username"], None, ip)

            max_attempts = current_app.config["MAX_LOGIN_ATTEMPTS"]
            remaining = max_attempts - (user["failed_attempts"] + 1)
            if remaining <= 0:
                until = now + current_app.config["LOCKOUT_DURATION"]
                models.lock_user(user["id"], until)
                models.log_audit("account_locked", user["id"], user["username"], None, ip)
                flash(t("flash.too_many_attempts"), "error")
            else:
                flash(t("flash.login_failed_remaining", n=remaining), "error")
            return render_template(
                "auth/login.html", form={"identifier": identifier, "remember_me": remember},
                errors=errors,
            )

        # --- success -------------------------------------------------
        models.clear_lock(user["id"])
        models.record_login_success(user["id"])
        models.record_login_attempt(identifier, ip, True, "ok")
        models.log_audit("login_success", user["id"], user["username"], None, ip)

        token = security.start_auth_session(user, remember=remember)
        locale = get_locale()
        session.clear()  # rotate the CSRF token together with the session id
        session["locale"] = locale  # keep the chosen language
        flash(t("flash.welcome_back", name=user["full_name"].split(" ")[0]), "success")

        target = security.safe_next_url(request.args.get("next")) or security.role_home(user)
        response = redirect(target)
        security.issue_session_cookie(response, token, remember)
        return response

    return render_template(
        "auth/login.html", form={"identifier": "", "remember_me": False}, errors=errors
    )


# ---------------------------------------------------------------------
# Forgot / reset password (Stage 2: advanced options)
# ---------------------------------------------------------------------
@auth_bp.route("/forgot-password", methods=["GET", "POST"])
@guest_only
def forgot_password():
    """Step 1: request a 6-digit code, delivered to the account email.

    Administrators are included: the code goes to the administrator's
    own address, and a copy goes to the platform owner's inbox
    (ADMIN_NOTIFY_EMAIL) whenever an admin account resets its password.
    """
    if request.method == "POST":
        identifier = _clean(request.form.get("identifier"))
        user = models.get_user_by_identifier(identifier) if identifier else None

        if user is not None:
            if user["role"] == "admin":
                models.purge_password_codes(user["id"])
                code = f"{secrets.randbelow(1000000):06d}"
                models.create_password_code(user["id"], models.hash_token(code))
                models.log_audit(
                    "password_reset_requested", user["id"], user["username"],
                    None, security.client_ip(),
                )
                sent = False
                try:
                    from .. import mailer
                    recipient = current_app.config.get("ADMIN_NOTIFY_EMAIL") or user["email"]
                    sent = mailer.send(
                        recipient,
                        f"{current_app.config['APP_NAME']} password reset code",
                        t("mail.reset_code_body", name=user["full_name"], code=code),
                    )
                except Exception as error:
                    current_app.logger.warning("reset email failed: %s", error)

                if sent:
                    flash(t("flash.reset_code_sent", email=current_app.config.get("ADMIN_NOTIFY_EMAIL") or user["email"]), "info")
                else:
                    flash(t("flash.reset_code_demo", code=code), "warning")
                return redirect(url_for("auth.verify_reset_code"))

            if user["role"] in ("buyer", "seller"):
                models.log_audit(
                    "password_reset_requested", user["id"], user["username"],
                    "routed_to_admin", security.client_ip(),
                )
                try:
                    models.create_admin_password_reset(user["id"])
                except Exception as error:
                    current_app.logger.warning("admin reset request failed: %s", error)
                flash(t("flash.reset_sent_to_admin"), "info")
                return redirect(url_for("auth.login"))

            models.purge_password_codes(user["id"])
            code = f"{secrets.randbelow(1000000):06d}"
            models.create_password_code(user["id"], models.hash_token(code))
            models.log_audit(
                "password_reset_requested", user["id"], user["username"],
                None, security.client_ip(),
            )
            # Deliver the code by email.
            sent = False
            try:
                from .. import mailer
                sent = mailer.send(
                    user["email"],
                    f"{current_app.config['APP_NAME']} password reset code",
                    t("mail.reset_code_body", name=user["full_name"], code=code),
                )
                if user["role"] == "admin":
                    admin_copy = current_app.config.get("ADMIN_NOTIFY_EMAIL")
                    if admin_copy and admin_copy != user["email"]:
                        mailer.send(
                            admin_copy,
                            f"{current_app.config['APP_NAME']} admin reset code",
                            t("mail.reset_code_admin_body",
                              name=user["username"], code=code),
                        )
            except Exception as error:
                current_app.logger.warning("reset email failed: %s", error)

            if sent:
                flash(t("flash.reset_code_sent", email=user["email"]), "info")
            else:
                # No SMTP configured: show the code on screen so the flow
                # still works locally (dev/demo mode only).
                flash(t("flash.reset_code_demo", code=code), "warning")
            return redirect(url_for("auth.verify_reset_code"))

        # Generic message in both cases so the form never reveals
        # whether an account exists.
        flash(t("flash.reset_code_sent_generic"), "info")
        return redirect(url_for("auth.login"))

    return render_template("auth/forgot_password.html")


@auth_bp.route("/reset-code", methods=["GET", "POST"])
@guest_only
def verify_reset_code():
    """Step 2: enter the emailed 6-digit code, then choose a new password."""
    if request.method == "POST":
        identifier = _clean(request.form.get("identifier"))
        code = (request.form.get("code") or "").strip()
        user = models.get_user_by_identifier(identifier) if identifier else None
        if user is None or not code:
            flash(t("flash.reset_code_invalid"), "error")
            return redirect(url_for("auth.verify_reset_code"))

        row = models.find_password_code(user)
        if row is None or not hmac.compare_digest(row["code_hash"], models.hash_token(code)):
            if row is not None:
                models.register_code_attempt(row["id"])
            models.log_audit(
                "password_reset_code_failed", user["id"], user["username"],
                None, security.client_ip(),
            )
            flash(t("flash.reset_code_invalid"), "error")
            return redirect(url_for("auth.verify_reset_code"))

        # Code accepted: remember the verified account for the reset step.
        session["reset_verified_user"] = user["id"]
        session["reset_verified_code_id"] = row["id"]
        return redirect(url_for("auth.reset_with_code"))

    return render_template("auth/verify_code.html")


@auth_bp.route("/reset-with-code", methods=["GET", "POST"])
@guest_only
def reset_with_code():
    """Step 3: choose a new password (requires a verified code)."""
    user_id = session.get("reset_verified_user")
    code_id = session.get("reset_verified_code_id")
    if not user_id or not code_id:
        flash(t("flash.reset_code_invalid"), "error")
        return redirect(url_for("auth.forgot_password"))

    user = models.get_user_by_id(user_id)
    if user is None:
        session.pop("reset_verified_user", None)
        session.pop("reset_verified_code_id", None)
        return redirect(url_for("auth.forgot_password"))

    errors: dict[str, str] = {}
    if request.method == "POST":
        new_password = request.form.get("password") or ""
        confirm = request.form.get("confirm_password") or ""
        clean, error = security.validate_password(new_password, confirm)
        if error:
            errors["password"] = error
        else:
            models.update_user_password(user_id, security.hash_password(clean))
            models.consume_password_code(code_id)
            models.purge_password_codes(user_id)
            models.delete_user_sessions(user_id)
            session.pop("reset_verified_user", None)
            session.pop("reset_verified_code_id", None)
            models.log_audit(
                "password_reset", user_id, user["username"], None, security.client_ip(),
            )
            flash(t("flash.password_reset_done"), "success")
            return redirect(url_for("auth.login"))
        flash(t("flash.fix_errors"), "error")

    return render_template("auth/reset_with_code.html", user=user, errors=errors)


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
@guest_only
def reset_password(token: str):
    """Reset via a link an administrator issued from the admin area."""
    user_id = models.peek_password_reset(models.hash_token(token))
    if user_id is None:
        flash(t("flash.invalid_reset_token"), "error")
        return redirect(url_for("auth.forgot_password"))

    user = models.get_user_by_id(user_id)
    errors: dict[str, str] = {}

    if request.method == "POST":
        new_password = request.form.get("password") or ""
        confirm = request.form.get("confirm_password") or ""
        clean, error = security.validate_password(new_password, confirm)
        if error:
            errors["password"] = error
        elif not errors:
            if models.consume_password_reset(models.hash_token(token)) is None:
                flash(t("flash.invalid_reset_token"), "error")
                return redirect(url_for("auth.forgot_password"))
            models.update_user_password(user_id, security.hash_password(clean))
            models.delete_password_resets_for_user(user_id)
            models.delete_user_sessions(user_id)
            models.log_audit(
                "password_reset", user_id, user["username"], None, security.client_ip(),
            )
            flash(t("flash.password_reset_done"), "success")
            return redirect(url_for("auth.login"))

        flash(t("flash.fix_errors"), "error")

    return render_template("auth/reset_password.html", token=token, errors=errors)


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    user = security.current_user()
    models.log_audit("logout", user["id"], user["username"], None, security.client_ip())
    security.end_auth_session()
    locale = get_locale()
    session.clear()
    session["locale"] = locale
    flash(t("flash.signed_out"), "success")
    response = redirect(url_for("main.index"))
    security.clear_session_cookie(response)
    return response
