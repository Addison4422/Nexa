"""Flutterwave payment integration (bonus feature).

Talks to the Flutterwave API when ``FLUTTERWAVE_SECRET_KEY`` is configured
and falls back to a fully simulated payment flow otherwise. The simulation
lets the checkout be demonstrated end to end without any real credentials.

All network access uses the standard library only - no extra dependency.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from flask import current_app


class PaymentError(Exception):
    """Raised when a payment action cannot be completed."""


# ---------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------
def _flutterwave_configured() -> bool:
    return bool(current_app.config.get("FLUTTERWAVE_SECRET_KEY"))


def inline_configured() -> bool:
    """True when a public key is set but no secret key: inline-checkout mode.

    The public key can open Flutterwave's hosted payment modal from the
    browser, but creating links / verifying requires the secret key, so
    verification falls back to the callback reference match.
    """
    return (bool(current_app.config.get("FLUTTERWAVE_PUBLIC_KEY"))
            and not _flutterwave_configured())


def _flutterwave_headers() -> dict[str, str]:
    secret = current_app.config["FLUTTERWAVE_SECRET_KEY"]
    return {
        "Authorization": f"Bearer {secret}",
        "Content-Type": "application/json",
    }


def _flutterwave_request(path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    base = current_app.config["FLUTTERWAVE_BASE_URL"].rstrip("/")
    url = f"{base}/{path.lstrip('/')}"
    data = None
    headers = _flutterwave_headers()
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    timeout = current_app.config.get("FLUTTERWAVE_TIMEOUT", 20)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise PaymentError(
            f"Flutterwave API returned HTTP {error.code}: {body[:500]}"
        ) from error
    except urllib.error.URLError as error:
        raise PaymentError(f"Flutterwave API unreachable: {error}") from error

    try:
        return json.loads(body) if body else {}
    except json.JSONDecodeError as error:
        raise PaymentError(f"Invalid response from Flutterwave: {body[:500]}") from error


# ---------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------
def initialize_payment(
    *,
    reference: str,
    amount: float,
    currency: str,
    customer_email: str,
    customer_name: str,
    redirect_url: str,
    narration: str | None = None,
) -> dict[str, Any]:
    """Ask Flutterwave to initialise a transaction.

    Returns a dict with either ``checkout_url`` (real mode) or
    ``simulate_url`` (demo mode) plus a ``simulated`` flag.
    """
    config = current_app.config
    payload: dict[str, Any] = {
        "tx_ref": reference,
        "amount": amount,
        "currency": currency,
        "customer": {"email": customer_email, "name": customer_name},
        "redirect_url": redirect_url,
        "narration": narration or "NEXACART order",
    }

    if _flutterwave_configured():
        response = _flutterwave_request("payments", payload)
        data = response.get("data") or {}
        link = data.get("link") or data.get("checkout_url")
        if not link:
            raise PaymentError(f"Flutterwave did not return a checkout link: {response}")
        return {"checkout_url": link, "simulated": False, "reference": reference}

    # --- simulated mode (no credentials configured) ------------------
    return {
        "checkout_url": None,
        "simulate_url": f"/payment/simulate/{reference}",
        "simulated": True,
        "reference": reference,
    }


def verify_transaction(transaction_id: str) -> dict[str, Any]:
    """Verify a Flutterwave transaction by its reference."""
    if _flutterwave_configured():
        response = _flutterwave_request(f"transactions/verify/{transaction_id}")
        data = response.get("data") or {}
        status = (data.get("status") or "").lower()
        return {
            "paid": status in {"successful", "success"},
            "status": status,
            "amount": data.get("amount"),
            "currency": data.get("currency"),
            "tx_ref": data.get("tx_ref"),
            "raw": response,
        }

    # --- simulated mode: treat every verify as successful ------------
    return {
        "paid": True,
        "status": "successful",
        "amount": None,
        "currency": None,
        "tx_ref": transaction_id,
        "raw": {"simulated": True},
    }


def money(amount: float, currency: str = "USD") -> str:
    """Format an amount for display (simple two-decimal rendering)."""
    currencies = config_currencies()
    info = currencies.get(currency, currencies["USD"])
    symbol = info["symbol"]
    return f"{symbol}{amount:,.2f}"


def config_currencies() -> dict[str, dict[str, str | float]]:
    return current_app.config["CURRENCIES"]
