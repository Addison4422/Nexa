"""Public pages: landing page, language switcher and health check."""

from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for

from ..i18n import is_supported, set_locale, t

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    return render_template("main/index.html")


@main_bp.route("/about")
def about():
    """Public page explaining how the platform works for each role."""
    def steps(role: str) -> list:
        return [t(f"about.{role}_steps.{i}") for i in range(8)
                if t(f"about.{role}_steps.{i}") != f"about.{role}_steps.{i}"]
    return render_template(
        "main/about.html",
        about_general=steps("general"),
        about_admin=steps("admin"),
        about_seller=steps("seller"),
        about_buyer=steps("buyer"),
    )


@main_bp.route("/about/<role>")
def about_role(role: str):
    """Per-role help page, readable without signing in."""
    if role not in ("buyer", "seller", "admin"):
        from flask import abort

        abort(404)
    steps = [t(f"about.{role}_steps.{i}") for i in range(8)
             if t(f"about.{role}_steps.{i}") != f"about.{role}_steps.{i}"]
    return render_template(
        "main/about_role.html",
        role=role,
        steps=steps,
        lead=t(f"about.{role}_lead"),
    )


@main_bp.route("/language/<locale>")
def set_language(locale: str):
    """Store the chosen language and return to the page the visitor came from."""
    if not is_supported(locale):
        locale = "en"
    set_locale(locale)

    target = request.args.get("next") or ""
    if not (target.startswith("/") and not target.startswith("//") and "\\" not in target):
        target = url_for("main.index")
    return redirect(target)


@main_bp.route("/health")
def health():
    return {"status": "ok", "app": "NEXACART"}
