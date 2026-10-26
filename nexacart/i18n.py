"""Internationalisation for NEXACART.

A small, dependency free translation layer:

* every visible string lives in ``nexacart/translations/<locale>.json``
* :func:`t` resolves a dotted key such as ``"auth.login.title"``
* the active locale is stored in the signed session cookie and can be
  changed from the language switcher in the header
* Arabic is a right-to-left language, so the layout direction travels
  with the locale (``<html dir="rtl">``) and the stylesheet uses
  logical properties instead of left/right.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from flask import g, has_request_context, session

TRANSLATIONS_DIR = Path(__file__).with_name("translations")

DEFAULT_LOCALE = "en"

LOCALE_META: dict[str, dict[str, str]] = {
    "en": {"name": "English", "english_name": "English", "dir": "ltr"},
    "fr": {"name": "Français", "english_name": "French", "dir": "ltr"},
    "ar": {"name": "العربية", "english_name": "Arabic", "dir": "rtl"},
}

ARABIC_DIGITS = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")

MONTHS: dict[str, list[str]] = {
    "en": [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ],
    "fr": [
        "janvier", "février", "mars", "avril", "mai", "juin",
        "juillet", "août", "septembre", "octobre", "novembre", "décembre",
    ],
    "ar": [
        "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
        "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر",
    ],
}

_AGO_FORMS: dict[str, dict[str, str]] = {
    "en": {
        "now": "just now",
        "minute_one": "{n} minute ago",
        "minute_many": "{n} minutes ago",
        "hour_one": "{n} hour ago",
        "hour_many": "{n} hours ago",
        "day_one": "{n} day ago",
        "day_many": "{n} days ago",
    },
    "fr": {
        "now": "à l'instant",
        "minute_one": "il y a {n} minute",
        "minute_many": "il y a {n} minutes",
        "hour_one": "il y a {n} heure",
        "hour_many": "il y a {n} heures",
        "day_one": "il y a {n} jour",
        "day_many": "il y a {n} jours",
    },
    "ar": {
        "now": "الآن",
        "minute_one": "منذ دقيقة واحدة",
        "minute_many": "منذ {n} دقائق",
        "hour_one": "منذ ساعة",
        "hour_many": "منذ {n} ساعات",
        "day_one": "منذ يوم",
        "day_many": "منذ {n} أيام",
    },
}

_catalogue_cache: dict[str, dict] = {}


# ---------------------------------------------------------------------
# Catalogue handling
# ---------------------------------------------------------------------
def _load_catalogue(code: str) -> dict:
    if code in _catalogue_cache:
        return _catalogue_cache[code]
    path = TRANSLATIONS_DIR / f"{code}.json"
    data: dict = {}
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    _catalogue_cache[code] = data
    return data


def _lookup(data: dict, key: str) -> str | None:
    node: Any = data
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, str) else None


def available_locales() -> list[dict[str, str]]:
    return [
        {
            "code": code,
            "name": meta["name"],
            "english_name": meta["english_name"],
            "dir": meta["dir"],
        }
        for code, meta in LOCALE_META.items()
    ]


def is_supported(code: str | None) -> bool:
    return bool(code) and code.lower() in LOCALE_META


def locale_direction(code: str | None = None) -> str:
    code = (code or get_locale()).lower()
    return LOCALE_META.get(code, LOCALE_META[DEFAULT_LOCALE])["dir"]


def is_rtl(code: str | None = None) -> bool:
    return locale_direction(code) == "rtl"


def detect_locale(accept_language: str | None) -> str:
    """Pick the best supported locale from an ``Accept-Language`` header."""
    if not accept_language:
        return DEFAULT_LOCALE

    candidates: list[tuple[str, float]] = []
    for part in accept_language.split(","):
        piece = part.strip()
        if not piece:
            continue
        code, _, params = piece.partition(";")
        quality = 1.0
        if params.strip().startswith("q="):
            try:
                quality = float(params.strip()[2:])
            except ValueError:
                quality = 0.0
        candidates.append((code.strip().lower(), quality))
    candidates.sort(key=lambda item: item[1], reverse=True)

    for code, _ in candidates:
        if is_supported(code):
            return code
        primary = code.split("-")[0]
        if is_supported(primary):
            return primary
    return DEFAULT_LOCALE


def get_locale() -> str:
    """The locale of the current request (English outside a request)."""
    if has_request_context():
        active = getattr(g, "locale", None)
        if is_supported(active):
            return active
        stored = session.get("locale")
        if is_supported(stored):
            return stored
    return DEFAULT_LOCALE


def set_locale(code: str) -> bool:
    """Remember the chosen locale in the session."""
    if not is_supported(code):
        return False
    code = code.lower()
    session["locale"] = code
    g.locale = code
    return True


def translate(key: str, **kwargs: Any) -> str:
    """Translate a dotted key, falling back to English and then to the key."""
    locale = get_locale()
    text = _lookup(_load_catalogue(locale), key)
    if text is None and locale != DEFAULT_LOCALE:
        text = _lookup(_load_catalogue(DEFAULT_LOCALE), key)
    if text is None:
        text = key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text


t = translate


# ---------------------------------------------------------------------
# Locale aware formatting
# ---------------------------------------------------------------------
def format_datetime(value: str | None) -> str:
    """Format a SQLite UTC timestamp, e.g. ``22 Oct 2026, 14:30``."""
    if not value:
        return "-"
    from datetime import datetime

    locale = get_locale()
    try:
        when = datetime.strptime(str(value)[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return str(value)
    day = when.strftime("%d")
    month = MONTHS[locale][when.month - 1]
    time = when.strftime("%H:%M")
    if locale == "fr":
        return f"{day} {month[:4]}. {when.year} à {time}"
    if locale == "ar":
        return f"{day} {month} {when.year}، {time}"
    return f"{day} {month[:3]} {when.year}, {time}"


def format_epoch(value: int | float | None) -> str:
    """Format a UNIX timestamp in the active locale."""
    if not value:
        return "-"
    from datetime import datetime, timezone

    locale = get_locale()
    try:
        when = datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return "-"
    day = when.strftime("%d")
    month = MONTHS[locale][when.month - 1]
    time = when.strftime("%H:%M")
    if locale == "fr":
        return f"{day} {month[:4]}. {when.year} à {time}"
    if locale == "ar":
        return f"{day} {month} {when.year}، {time}"
    return f"{day} {month[:3]} {when.year}, {time}"


def time_ago(value: int | float | str | None) -> str:
    """Relative time such as ``3 minutes ago`` / ``il y a 3 minutes``."""
    if value is None:
        return translate("common.never")
    from datetime import datetime, timezone

    locale = get_locale()
    forms = _AGO_FORMS.get(locale, _AGO_FORMS[DEFAULT_LOCALE])

    if isinstance(value, str):
        try:
            when = datetime.strptime(value[:19], "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc
            )
            seconds = (datetime.now(timezone.utc) - when).total_seconds()
        except ValueError:
            return translate("common.unknown")
    else:
        seconds = datetime.now(timezone.utc).timestamp() - float(value)

    seconds = int(max(seconds, 0))
    if seconds < 60:
        return forms["now"]
    if seconds < 3600:
        minutes = seconds // 60
        return forms["minute_one" if minutes == 1 else "minute_many"].format(n=minutes)
    if seconds < 86400:
        hours = seconds // 3600
        return forms["hour_one" if hours == 1 else "hour_many"].format(n=hours)
    days = seconds // 86400
    return forms["day_one" if days == 1 else "day_many"].format(n=days)


def format_number(value: Any) -> str:
    """Format a number the way the active locale writes it.

    * English: ``1,234.5``
    * French: ``1 234,5`` (narrow no-break space as thousands separator)
    * Arabic: ``١٬٢٣٤٫٥`` (Arabic-Indic digits and Arabic separators)
    """
    locale = get_locale()
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number == int(number):
        number = int(number)

    text = f"{number:,}"
    if locale == "fr":
        text = text.replace(",", "\u202f").replace(".", ",")
    elif locale == "ar":
        text = text.replace(",", "\u066c").replace(".", "\u066b")
        text = text.translate(ARABIC_DIGITS)
    return text
