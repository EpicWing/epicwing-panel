"""Sending e-mail through Resend or SMTP and the shared EpicWing mail layout."""

import smtplib
import ssl
import sys
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from email.message import EmailMessage
from html import escape

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_engine
from app.models import PanelSetting
from app.security.vault import decrypt_text, encrypt_text

API_URL = "https://api.resend.com/emails"
ACCENT = "#f59e0b"
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
_P = "margin:0 0 16px;font-size:15px;line-height:24px;color:#d4d4d8;"

PREFIX = "mail."
VAULT_PURPOSE = "mail"
PROVIDERS = ("resend", "smtp")
SECURITY_MODES = ("starttls", "ssl", "none")
SECRET_FIELDS = ("resend_api_key", "smtp_password")


@dataclass
class MailConfig:
    provider: str = "resend"
    sender: str = ""
    reply_to: str = ""
    resend_api_key: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_security: str = "starttls"


FIELD_NAMES = tuple(f.name for f in fields(MailConfig))


def config_from_env() -> MailConfig:
    env = get_settings()
    return MailConfig(
        resend_api_key=env.resend_api_key, sender=env.mail_from, reply_to=env.mail_reply_to
    )


def load_config(db: Session) -> MailConfig:
    """Mail settings from the panel settings, with values from .env as fallback."""
    config = config_from_env()
    rows = {
        row.key: row.value
        for row in db.scalars(select(PanelSetting).where(PanelSetting.key.like(PREFIX + "%")))
    }
    for name in FIELD_NAMES:
        value = rows.get(PREFIX + name, "")
        if name in SECRET_FIELDS and value:
            value = decrypt_text(value, VAULT_PURPOSE) or ""
        if value == "":
            continue
        if name == "smtp_port":
            try:
                config.smtp_port = int(value)
            except ValueError:
                pass
        else:
            setattr(config, name, value)
    if config.provider not in PROVIDERS:
        config.provider = "resend"
    if config.smtp_security not in SECURITY_MODES:
        config.smtp_security = "starttls"
    return config


def save_config(db: Session, values: dict[str, object]) -> None:
    """Saves settings; secrets are encrypted, None leaves a value unchanged."""
    for name, value in values.items():
        if name not in FIELD_NAMES or value is None:
            continue
        text = str(value)
        if name in SECRET_FIELDS and text:
            text = encrypt_text(text, VAULT_PURPOSE)
        key = PREFIX + name
        row = db.get(PanelSetting, key)
        if row is None:
            db.add(PanelSetting(key=key, value=text))
        else:
            row.value = text
    db.commit()


def is_configured(config: MailConfig) -> bool:
    if not config.sender:
        return False
    if config.provider == "smtp":
        return bool(config.smtp_host)
    return bool(config.resend_api_key)


def _button(label: str, url: str) -> str:
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" style="margin-top:12px;">'
        f'<tr><td bgcolor="{ACCENT}" style="border-radius:10px;">'
        f'<a href="{escape(url, quote=True)}" style="display:inline-block;padding:13px 26px;'
        f"font-family:{FONT};font-size:15px;font-weight:700;color:#0a0a0a;"
        f'text-decoration:none;">{escape(label)}</a></td></tr></table>'
    )


SITE_URL = "https://epicwing.de"
DISCLAIMER = (
    "This email was sent by the operator of this panel, not by EpicWing. "
    "EpicWing is not responsible for how this email is used or for its content."
)
LOGO_NOTE = "The logo shown is a simplified version and not the official EpicWing logo."
ABUSE_EMAIL = "abuse@epicwing.de"


def _footer(year: int, reply_hint: bool) -> str:
    """Fixed footer. Operators cannot change it through settings."""
    site = f'<a href="{SITE_URL}" style="color:{ACCENT};text-decoration:none;">EpicWing</a>'
    ask = " Questions? Reply to this email." if reply_hint else ""
    abuse = (
        f'<a href="mailto:{ABUSE_EMAIL}" '
        f'style="color:{ACCENT};text-decoration:none;">{ABUSE_EMAIL}</a>'
    )
    return (
        f"Powered by {site}.{ask}<br>{escape(DISCLAIMER)}<br>{escape(LOGO_NOTE)}<br>"
        f"Report abuse: {abuse}<br>"
        f"Copyright &copy; {year} EpicWing."
    )


def render(
    title: str,
    paragraphs: list[str],
    button: tuple[str, str] | None = None,
    *,
    reply_hint: bool = False,
) -> tuple[str, str]:
    """Builds the HTML and text version of a mail in the EpicWing design."""
    if button and not button[1].startswith(("https://", "http://")):
        raise ValueError("button url must start with http(s)://")
    year = datetime.now(UTC).year
    body = "".join(f'<p style="{_P}">{escape(p)}</p>' for p in paragraphs)
    action = _button(*button) if button else ""
    html = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="dark">'
        f"<title>{escape(title)}</title></head>"
        '<body style="margin:0;padding:0;background:#0a0a0a;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="background:#0a0a0a;"><tr><td align="center" style="padding:32px 16px;">'
        '<table role="presentation" width="560" cellpadding="0" cellspacing="0" '
        'style="width:100%;max-width:560px;">'
        f'<tr><td style="padding:0 4px 20px;font-family:{FONT};font-size:22px;'
        f'font-weight:700;color:#fafafa;"><span style="color:{ACCENT};">//</span>'
        " EpicWing</td></tr>"
        '<tr><td style="background:#111113;border:1px solid #26262b;border-radius:14px;'
        f'padding:32px;font-family:{FONT};">'
        '<h1 style="margin:0 0 20px;font-size:24px;line-height:30px;color:#fafafa;">'
        f"{escape(title)}</h1>{body}{action}</td></tr>"
        f'<tr><td style="padding:24px 4px 0;font-family:{FONT};font-size:12px;'
        'line-height:20px;color:#71717a;">'
        f"{_footer(year, reply_hint)}</td></tr></table></td></tr></table>"
        "</body></html>"
    )
    lines = [title, ""]
    for paragraph in paragraphs:
        lines += [paragraph, ""]
    if button:
        lines += [f"{button[0]}: {button[1]}", ""]
    lines.append(f"Powered by EpicWing ({SITE_URL})")
    if reply_hint:
        lines.append("Questions? Reply to this email.")
    lines += [DISCLAIMER, LOGO_NOTE, f"Report abuse: {ABUSE_EMAIL}"]
    lines.append(f"Copyright (c) {year} EpicWing")
    return html, "\n".join(lines)


def render_for(
    config: MailConfig,
    title: str,
    paragraphs: list[str],
    button: tuple[str, str] | None = None,
) -> tuple[str, str]:
    """Like render, with a reply hint only if a Reply-To address is set."""
    return render(title, paragraphs, button, reply_hint=bool(config.reply_to))


def _send_resend(
    config: MailConfig, to: str, subject: str, html: str, text: str
) -> tuple[bool, str]:
    if not config.resend_api_key:
        return False, "Resend API key is not set"
    payload = {
        "from": config.sender,
        "to": [to],
        "subject": subject,
        "html": html,
        "text": text,
    }
    if config.reply_to:
        payload["reply_to"] = config.reply_to
    try:
        response = httpx.post(
            API_URL,
            headers={
                "Authorization": f"Bearer {config.resend_api_key}",
                "User-Agent": "epicwing-panel",
            },
            json=payload,
            timeout=10,
        )
    except httpx.HTTPError as exc:
        return False, f"request failed: {type(exc).__name__}"
    if response.status_code >= 300:
        return False, f"HTTP {response.status_code}: {response.text[:300]}"
    try:
        return True, str(response.json().get("id", ""))
    except ValueError:
        return True, ""


def _send_smtp(config: MailConfig, to: str, subject: str, html: str, text: str) -> tuple[bool, str]:
    if not config.smtp_host:
        return False, "SMTP host is not set"
    try:
        message = EmailMessage()
        message["From"] = config.sender
        message["To"] = to
        message["Subject"] = subject
        if config.reply_to:
            message["Reply-To"] = config.reply_to
        message.set_content(text)
        message.add_alternative(html, subtype="html")
        if config.smtp_security == "ssl":
            client = smtplib.SMTP_SSL(
                config.smtp_host,
                config.smtp_port,
                timeout=10,
                context=ssl.create_default_context(),
            )
        else:
            client = smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=10)
        with client:
            if config.smtp_security == "starttls":
                client.starttls(context=ssl.create_default_context())
            if config.smtp_user:
                client.login(config.smtp_user, config.smtp_password)
            client.send_message(message)
    except (smtplib.SMTPException, OSError, ValueError) as exc:
        return False, f"SMTP failed: {type(exc).__name__}"
    return True, ""


def send_mail(
    to: str, subject: str, html: str, text: str, config: MailConfig | None = None
) -> tuple[bool, str]:
    """Sends a mail. Never raises; returns (success, ID or error text)."""
    config = config or config_from_env()
    if not config.sender:
        return False, "sender address is not set"
    if config.provider == "smtp":
        return _send_smtp(config, to, subject, html, text)
    return _send_resend(config, to, subject, html, text)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m app.services.mail recipient@example.com")
    with Session(get_engine()) as session:
        cli_config = load_config(session)
    page, plain = render_for(
        cli_config,
        "Mail delivery works",
        [
            "This is a test message from your EpicWing panel.",
            "If you can read this, the panel can send emails with your settings.",
        ],
    )
    ok, info = send_mail(sys.argv[1], "EpicWing test email", page, plain, cli_config)
    print(("OK, id: " if ok else "FAILED: ") + info)
    sys.exit(0 if ok else 1)
