"""Presentation helpers (device labels, badge classes)."""

from __future__ import annotations

from .i18n import t

BROWSERS = (
    ("Edge", "edg/"),
    ("Chrome", "chrome/"),
    ("Firefox", "firefox/"),
    ("Safari", "safari/"),
    ("Internet Explorer", "msie"),
)

SYSTEMS = (
    ("Windows", "windows"),
    ("macOS", "mac os"),
    ("iOS", "iphone"),
    ("iPadOS", "ipad"),
    ("Android", "android"),
    ("Linux", "linux"),
)


def device_label(user_agent: str | None) -> str:
    """Derive a short, friendly device description from a user agent string."""
    if not user_agent:
        return t("common.unknown")

    ua = user_agent.lower()
    browser = "Browser"
    for name, marker in BROWSERS:
        if marker in ua:
            browser = name
            break

    system = "OS"
    for name, marker in SYSTEMS:
        if marker in ua:
            system = name
            break

    separator = t("common.on_device")
    return f"{browser} {separator} {system}"


def role_css_class(role: str) -> str:
    return {"admin": "badge-admin", "seller": "badge-seller", "buyer": "badge-buyer"}.get(
        role, "badge-neutral"
    )


def utc_now_str() -> str:
    """UTC 'now' as a SQLite datetime string, for expiry comparisons."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
