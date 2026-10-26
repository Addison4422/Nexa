"""Weather service: OpenWeather API client with graceful degradation.

Credentials live in the environment, never in the source (Stage 3
requirement). Set ``OPENWEATHER_API_KEY`` in the environment — the app
still works without it by returning demo data so the feature can be
demonstrated, and every page clearly says when demo data is shown.

Network or API failures never crash the application: the caller
receives a status string and renders friendly feedback.
"""

from __future__ import annotations

import os
import time
import urllib.error
import urllib.parse
import urllib.request

# Match the OpenWeather condition codes to readable groups.
_CONDITIONS = {
    "clear": ("Clear sky", "clear"),
    "clouds": ("Cloudy", "cloud"),
    "rain": ("Rain", "rain"),
    "drizzle": ("Drizzle", "rain"),
    "thunderstorm": ("Thunderstorm", "storm"),
    "snow": ("Snow", "snow"),
    "mist": ("Mist", "mist"),
    "fog": ("Fog", "mist"),
    "haze": ("Haze", "mist"),
    "smoke": ("Haze", "mist"),
    "dust": ("Dust", "mist"),
    "sand": ("Dust", "mist"),
    "ash": ("Haze", "mist"),
    "squall": ("Squall", "storm"),
    "tornado": ("Tornado", "storm"),
}

TIMEOUT = 8  # seconds


def api_key() -> str:
    from flask import current_app
    try:
        key = current_app.config.get("OPENWEATHER_API_KEY", "")
    except RuntimeError:  # outside the application context
        key = ""
    return (key or os.environ.get("OPENWEATHER_API_KEY", "")).strip()


def is_configured() -> bool:
    return bool(api_key())


def _classify(code: int) -> tuple[str, str]:
    """Return (readable label, icon group) for an OpenWeather code."""
    if code == 800:
        return _CONDITIONS["clear"]
    if code in (801, 802):
        return ("Few clouds", "cloud")
    if code in (803, 804):
        return ("Overcast", "cloud")
    if 200 <= code < 300:
        return _CONDITIONS["thunderstorm"]
    if 300 <= code < 400:
        return _CONDITIONS["drizzle"]
    if 500 <= code < 600:
        return _CONDITIONS["rain"]
    if 600 <= code < 700:
        return _CONDITIONS["snow"]
    if 700 <= code < 800:
        return _CONDITIONS["haze"]
    return ("Unknown", "clear")


class WeatherResult(dict):
    """Dict with an extra ``status`` key: ok / not_found / api_error / network_error."""


def fetch_by_city(city: str, units: str = "metric") -> WeatherResult:
    """Look up weather by city name (optionally ',CC' e.g. 'Kigali,RW')."""
    if not is_configured():
        return _demo_result(city=city)
    params = urllib.parse.urlencode({"q": city, "units": units, "appid": api_key()})
    return _fetch(params)


def fetch_by_coords(lat: float, lon: float, units: str = "metric") -> WeatherResult:
    """Look up weather by latitude/longitude."""
    if not is_configured():
        return _demo_result(lat=lat, lon=lon)
    params = urllib.parse.urlencode(
        {"lat": lat, "lon": lon, "units": units, "appid": api_key()}
    )
    return _fetch(params)


def _fetch(params: str) -> WeatherResult:
    url = f"https://api.openweathermap.org/data/2.5/weather?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "NEXACART/3.0"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = _parse(resp.read())
        if data is None:
            return WeatherResult(status="not_found")
        return data
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return WeatherResult(status="not_found")
        return WeatherResult(status="api_error")
    except (urllib.error.URLError, TimeoutError, OSError):
        return WeatherResult(status="network_error")


def _parse(raw: bytes) -> WeatherResult | None:
    import json

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if payload.get("cod") not in (200, "200") or not payload.get("weather"):
        return None
    try:
        weather = payload["weather"][0]
        main = payload.get("main", {})
        wind = payload.get("wind", {})
        result = WeatherResult(
            status="ok",
            city=payload.get("name", ""),
            country=(payload.get("sys", {}) or {}).get("country", ""),
            lat=payload.get("coord", {}).get("lat"),
            lon=payload.get("coord", {}).get("lon"),
            temp=round(main.get("temp", 0.0), 1),
            feels_like=round(main.get("feels_like", 0.0), 1),
            humidity=main.get("humidity", 0),
            wind_speed=wind.get("speed", 0.0),
            condition_code=weather.get("id", 800),
            condition=weather.get("main", ""),
            description=weather.get("description", "").capitalize(),
            icon_group=_classify(weather.get("id", 800))[1],
            observed_at=int(payload.get("dt", time.time())),
            timezone_offset=payload.get("timezone", 0),
            units="metric",
        )
        return result
    except (KeyError, TypeError, ValueError):
        return None


# ---------------------------------------------------------------------
# Demo fallback (no API key configured). Realistic static data so the
# full feature — search, history, admin review — can be demonstrated
# without credentials. Clearly flagged via ``demo=True``.
# ---------------------------------------------------------------------
_DEMO_CITIES = {
    "kigali": ("Kigali", "RW", -1.95, 30.06, 24.6, 68, 3.4, "few clouds", 802),
    "nairobi": ("Nairobi", "KE", -1.29, 36.82, 21.3, 61, 4.1, "scattered clouds", 803),
    "kampala": ("Kampala", "UG", 0.35, 32.58, 23.1, 70, 2.8, "light rain", 500),
    "london": ("London", "GB", 51.51, -0.13, 12.4, 76, 5.2, "overcast clouds", 804),
    "paris": ("Paris", "FR", 48.86, 2.35, 15.8, 64, 3.0, "clear sky", 800),
    "dubai": ("Dubai", "AE", 25.20, 55.27, 36.9, 42, 4.6, "clear sky", 800),
    "tokyo": ("Tokyo", "JP", 35.68, 139.69, 18.2, 58, 3.7, "broken clouds", 803),
    "new york": ("New York", "US", 40.71, -74.01, 14.5, 55, 6.1, "clear sky", 800),
    "cairo": ("Cairo", "EG", 30.04, 31.24, 33.4, 30, 4.9, "clear sky", 800),
    "cape town": ("Cape Town", "ZA", -33.92, 18.42, 19.7, 71, 5.5, "fog", 701),
}


def _demo_result(city: str = "", lat: float | None = None, lon: float | None = None) -> WeatherResult:
    key = city.strip().lower()
    if key and key not in _DEMO_CITIES:
        # Demo mode only knows the sample cities: an unknown city is
        # treated as "not found" so the error state is demonstrable.
        return WeatherResult(status="not_found")
    if key in _DEMO_CITIES:
        name, cc, dlat, dlon, temp, hum, wind, desc, code = _DEMO_CITIES[key]
    else:
        name = "Sample location"
        cc = ""
        dlat = lat if lat is not None else 0.0
        dlon = lon if lon is not None else 0.0
        seed = f"{dlat},{dlon}"
        temp = round(18 + (abs(hash(seed)) % 140) / 10, 1)
        hum = 40 + (abs(hash(seed)) % 50)
        wind = round(1.5 + (abs(hash(seed)) % 60) / 10, 1)
        desc = "clear sky"
        code = 800
    label, group = _classify(code)
    return WeatherResult(
        status="ok",
        demo=True,
        city=name,
        country=cc,
        lat=dlat,
        lon=dlon,
        temp=temp,
        feels_like=round(temp - 0.8, 1),
        humidity=hum,
        wind_speed=wind,
        condition_code=code,
        condition=label,
        description=desc.capitalize(),
        icon_group=group,
        observed_at=int(time.time()),
        timezone_offset=0,
        units="metric",
    )
