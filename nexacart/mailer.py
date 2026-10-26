"""Simple SMTP email sending (used for password reset codes).

Credentials come from the environment so they never live in the source
tree. When SMTP is not configured the message is written to the log and
the code is shown to the administrator on screen instead (dev mode).
"""

from __future__ import annotations

import smtplib
from email.mime.text import MIMEText

from flask import current_app


class MailError(Exception):
    pass


def configured() -> bool:
    return bool(current_app.config.get("SMTP_HOST") and current_app.config.get("SMTP_USER"))


def send(to: str, subject: str, body: str) -> bool:
    """Send a plain-text email. Returns True when actually sent."""
    host = current_app.config.get("SMTP_HOST")
    if not host:
        current_app.logger.info(
            "SMTP not configured; email to %s skipped. Subject: %s", to, subject
        )
        return False
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = current_app.config.get("SMTP_FROM") or current_app.config["SMTP_USER"]
    msg["To"] = to

    user = current_app.config["SMTP_USER"]
    password = current_app.config.get("SMTP_PASSWORD") or ""
    try:
        with smtplib.SMTP(host, current_app.config.get("SMTP_PORT", 587), timeout=15) as server:
            server.starttls()
            if user:
                server.login(user, password)
            server.sendmail(msg["From"], [to], msg.as_string())
        return True
    except Exception as error:  # smtplib.SMTPException, OSError
        current_app.logger.warning("Email to %s failed: %s", to, error)
        raise MailError(str(error)) from error
