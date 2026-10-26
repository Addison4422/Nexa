"""Stage 3: Weather information (OpenWeather API).

Public search page — no login required. Administrators additionally get
a search history / usage statistics view. All lookups are logged to
``weather_searches`` for admin review (no personal data stored).
"""

from __future__ import annotations

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from .. import models, security
from ..i18n import t
from ..weather import fetch_by_city, fetch_by_coords, is_configured

weather_bp = Blueprint("weather", __name__, url_prefix="/weather")


# ---------------------------------------------------------------------
# Public search page
# ---------------------------------------------------------------------
@weather_bp.route("/", methods=["GET"])
def search():
    """Weather search page — supports either city OR coordinates."""
    mode = (request.args.get("mode") or "city").strip()
    if mode not in {"city", "coords"}:
        mode = "city"

    result = None
    errors: dict[str, str] = {}
    status = None

    if "run" in request.args:
        if mode == "city":
            city = (request.args.get("city") or "").strip()
            if not city:
                errors["city"] = t("weather.err_city_required")
            elif len(city) > 100:
                errors["city"] = t("weather.err_city_long")
            else:
                result = fetch_by_city(city)
                status = result.get("status")
                _log("city", city, result)
                if status == "not_found":
                    errors["city"] = t("weather.err_not_found", city=city)
                elif status == "api_error":
                    errors["city"] = t("weather.err_api")
                elif status == "network_error":
                    errors["city"] = t("weather.err_network")
                elif status != "ok":
                    errors["city"] = t("weather.err_generic")
        else:
            lat_raw = (request.args.get("lat") or "").strip()
            lon_raw = (request.args.get("lon") or "").strip()
            lat, lon = _parse_coords(lat_raw, lon_raw, errors)
            if not errors:
                result = fetch_by_coords(lat, lon)
                status = result.get("status")
                _log("coords", f"{lat_raw}, {lon_raw}", result)
                if status == "not_found":
                    errors["coords"] = t("weather.err_not_found_coords")
                elif status == "api_error":
                    errors["coords"] = t("weather.err_api")
                elif status == "network_error":
                    errors["coords"] = t("weather.err_network")
                elif status != "ok":
                    errors["coords"] = t("weather.err_generic")

    return render_template(
        "weather/search.html",
        mode=mode,
        result=result,
        errors=errors,
        ran="run" in request.args,
        api_configured=is_configured(),
    )


def _parse_coords(lat_raw: str, lon_raw: str, errors: dict) -> tuple[float, float]:
    try:
        lat = float(lat_raw)
        lon = float(lon_raw)
    except ValueError:
        errors["coords"] = t("weather.err_coords_format")
        return (0.0, 0.0)
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        errors["coords"] = t("weather.err_coords_range")
    return (lat, lon)


def _log(query_type: str, query_value: str, result) -> None:
    models.log_weather_search(
        query_type=query_type,
        query_value=query_value,
        city_label=str(result.get("city", "")) if result.get("status") == "ok" else "",
        status=result.get("status", "invalid"),
    )


# ---------------------------------------------------------------------
# Administrator: history + usage statistics
# ---------------------------------------------------------------------
@weather_bp.route("/admin/history")
@security.roles_required("admin")
def admin_history():
    page = max(1, int(request.args.get("page", 1) or 1))
    per_page = current_app.config["ITEMS_PER_PAGE"]
    total = models.count_weather_searches()
    pages = max(1, -(-total // per_page))
    entries = models.list_weather_searches(limit=per_page, offset=(page - 1) * per_page)
    pagination = {
        "page": page,
        "pages": pages,
        "total": total,
        "start": 0 if total == 0 else (page - 1) * per_page + 1,
        "end": min(page * per_page, total),
        "has_prev": page > 1,
        "has_next": page < pages,
    }
    return render_template(
        "weather/admin_history.html",
        entries=entries,
        pagination=pagination,
        page=page,
        pages=pages,
        total=total,
    )


@weather_bp.route("/admin/stats")
@security.roles_required("admin")
def admin_stats():
    return render_template("weather/admin_stats.html", stats=models.weather_stats())


@weather_bp.route("/admin/clear", methods=["POST"])
@security.roles_required("admin")
def admin_clear():
    models.clear_weather_history()
    models.log_audit(
        "weather_history_cleared", security.current_user()["id"],
        security.current_user()["username"], "weather_searches",
        security.client_ip(),
    )
    flash(t("weather.flash_cleared"), "success")
    return redirect(url_for("weather.admin_history"))
