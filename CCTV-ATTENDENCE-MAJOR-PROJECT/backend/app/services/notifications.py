"""Step 8b – Notifications.

Send attendance reports via email (SMTP) or SMS (Twilio).
"""

from __future__ import annotations

import logging
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from .models import NotificationPayload

log = logging.getLogger(__name__)


# -------------------------------------------------------------------- #
#  Email                                                                 #
# -------------------------------------------------------------------- #

def send_email(
    payload: NotificationPayload,
    smtp_host: str = "smtp.gmail.com",
    smtp_port: int = 587,
    smtp_user: str = "",
    smtp_password: str = "",
) -> bool:
    """
    Send an email via SMTP with an optional attachment.

    Returns ``True`` on success, ``False`` on failure.
    """
    msg = MIMEMultipart()
    msg["From"] = smtp_user
    msg["To"] = payload.recipient
    msg["Subject"] = payload.subject

    msg.attach(MIMEText(payload.message, "html"))

    if payload.attachment_path:
        attachment = Path(payload.attachment_path)
        if attachment.exists():
            with open(attachment, "rb") as f:
                part = MIMEApplication(f.read(), Name=attachment.name)
            part["Content-Disposition"] = (
                f'attachment; filename="{attachment.name}"'
            )
            msg.attach(part)

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, [payload.recipient], msg.as_string())
        log.info("Email sent to %s", payload.recipient)
        return True
    except Exception as exc:
        log.error("Failed to send email to %s: %s", payload.recipient, exc)
        return False


# -------------------------------------------------------------------- #
#  SMS (Twilio)                                                          #
# -------------------------------------------------------------------- #

def send_sms(
    payload: NotificationPayload,
    account_sid: str = "",
    auth_token: str = "",
    from_number: str = "",
) -> bool:
    """
    Send an SMS message via the Twilio API.

    Requires the ``twilio`` package::

        pip install twilio

    Returns ``True`` on success, ``False`` on failure.
    """
    try:
        from twilio.rest import Client  # type: ignore[import-untyped]

        client = Client(account_sid, auth_token)
        message = client.messages.create(
            body=payload.message,
            from_=from_number,
            to=payload.recipient,
        )
        log.info("SMS sent to %s (SID: %s)", payload.recipient, message.sid)
        return True
    except Exception as exc:
        log.error("Failed to send SMS to %s: %s", payload.recipient, exc)
        return False


# -------------------------------------------------------------------- #
#  Dispatcher                                                            #
# -------------------------------------------------------------------- #

class NotificationDispatcher:
    """
    Route notifications to the appropriate channel (email or SMS).
    """

    def __init__(
        self,
        smtp_host: str = "smtp.gmail.com",
        smtp_port: int = 587,
        smtp_user: str = "",
        smtp_password: str = "",
        twilio_sid: str = "",
        twilio_token: str = "",
        twilio_from: str = "",
    ) -> None:
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.twilio_sid = twilio_sid
        self.twilio_token = twilio_token
        self.twilio_from = twilio_from

    def dispatch(self, notifications: list[NotificationPayload]) -> dict:
        """
        Send all notifications and return a summary of results.
        """
        results = {"sent": 0, "failed": 0, "details": []}

        for n in notifications:
            if n.channel == "email":
                ok = send_email(
                    n,
                    smtp_host=self.smtp_host,
                    smtp_port=self.smtp_port,
                    smtp_user=self.smtp_user,
                    smtp_password=self.smtp_password,
                )
            elif n.channel == "sms":
                ok = send_sms(
                    n,
                    account_sid=self.twilio_sid,
                    auth_token=self.twilio_token,
                    from_number=self.twilio_from,
                )
            else:
                log.warning("Unknown channel '%s', skipping", n.channel)
                ok = False

            if ok:
                results["sent"] += 1
            else:
                results["failed"] += 1
            results["details"].append(
                {"channel": n.channel, "recipient": n.recipient, "success": ok}
            )

        return results
