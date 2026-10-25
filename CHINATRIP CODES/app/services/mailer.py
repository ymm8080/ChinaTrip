# -*- coding: utf-8 -*-
"""Email delivery for verification codes (register / password reset).

Two implementations behind one tiny protocol:

- ``SmtpMailer``  - real SMTP. Port 465 = implicit SSL, anything else
  (587) = STARTTLS. Credentials come from settings (SMTP_USER/SMTP_PASS);
  envelope From defaults to SMTP_USER when SMTP_FROM is unset.
- ``DevMailer``   - active when ``smtp_host`` is empty (the default).
  Nothing leaves the machine; the code is echoed in a WARNING log and,
  via ``dev=True``, in the API response so the whole H5 flow works
  locally without SMTP.

Stdlib only (smtplib + email.mime) - no new dependencies.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Protocol

from app.config import Settings, get_settings
from app.services.lang_ctx import L

logger = logging.getLogger(__name__)

_SMTP_TIMEOUT_SECONDS = 10.0


def _purpose_label(purpose: str) -> str:
    return {
        "register": L("注册", "Sign-up"),
        "reset_password": L("密码重置", "Password reset"),
    }.get(purpose, L("验证", "Verification"))


class MailerError(Exception):
    """SMTP layer failed (connect/login/send); route maps it to 502."""


class Mailer(Protocol):
    dev: bool

    def send_code(self, to_email: str, code: str, purpose: str) -> None: ...


class DevMailer:
    """Offline stand-in: log the code, send nothing, flag responses."""

    dev = True

    def send_code(self, to_email: str, code: str, purpose: str) -> None:
        logger.warning(
            "DEV mailer: 验证码未真实发送 to=%s purpose=%s code=%s",
            to_email,
            purpose,
            code,
        )


class SmtpMailer:
    """Real SMTP delivery; raises ``MailerError`` on any failure."""

    dev = False

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _message(self, to_email: str, code: str, purpose: str) -> MIMEText:
        s = self._settings
        scene = _purpose_label(purpose)
        body = L(
            f"您的{scene}验证码是：{code}\n"
            "\n"
            "验证码 10 分钟内有效。若非本人操作，请忽略本邮件。\n"
            "\n"
            "- ChinaTrip 自助景点规划助手\n",
            f"Your {scene} verification code is: {code}\n"
            "\n"
            "This code is valid for 10 minutes. If this wasn't you, "
            "please ignore this email.\n"
            "\n"
            "- ChinaTrip Attraction Planner\n",
        )
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = Header(
            L(
                f"【ChinaTrip】{scene}验证码 {code}",
                f"[ChinaTrip] {scene} verification code {code}",
            ),
            "utf-8",
        )
        sender = s.smtp_from or s.smtp_user
        msg["From"] = formataddr((str(Header("ChinaTrip", "utf-8")), sender))
        msg["To"] = to_email
        return msg

    def send_code(self, to_email: str, code: str, purpose: str) -> None:
        s = self._settings
        msg = self._message(to_email, code, purpose)
        sender = s.smtp_from or s.smtp_user
        context = ssl.create_default_context()
        try:
            if s.smtp_port == 465:  # implicit SSL
                with smtplib.SMTP_SSL(
                    s.smtp_host,
                    s.smtp_port,
                    timeout=_SMTP_TIMEOUT_SECONDS,
                    context=context,
                ) as smtp:
                    if s.smtp_user:
                        smtp.login(s.smtp_user, s.smtp_pass)
                    smtp.sendmail(sender, [to_email], msg.as_string())
            else:  # 587 etc. -> STARTTLS
                with smtplib.SMTP(
                    s.smtp_host, s.smtp_port, timeout=_SMTP_TIMEOUT_SECONDS
                ) as smtp:
                    smtp.ehlo()
                    smtp.starttls(context=context)
                    smtp.ehlo()
                    if s.smtp_user:
                        smtp.login(s.smtp_user, s.smtp_pass)
                    smtp.sendmail(sender, [to_email], msg.as_string())
        except (smtplib.SMTPException, OSError) as exc:
            raise MailerError(f"smtp send to {to_email} failed: {exc}") from exc


_mailer_singleton: Mailer | None = None


def get_mailer() -> Mailer:
    """Process-wide singleton: real SMTP when configured, dev otherwise."""
    global _mailer_singleton
    if _mailer_singleton is None:
        settings = get_settings()
        _mailer_singleton = SmtpMailer(settings) if settings.smtp_host else DevMailer()
    return _mailer_singleton
