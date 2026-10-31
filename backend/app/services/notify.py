"""Notifications to Discord and by e-mail, with failover between the channels."""

import logging
from collections.abc import Callable
from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PanelSetting
from app.security.vault import decrypt_text, encrypt_text
from app.services.mail import is_configured, load_config, render_for, send_mail

log = logging.getLogger("epicwing.notify")

PREFIX = "notify."
VAULT_PURPOSE = "notify"
WEBHOOK_PREFIXES = (
    "https://discord.com/api/webhooks/",
    "https://discordapp.com/api/webhooks/",
)


@dataclass
class NotifySettings:
    discord_enabled: bool = False
    discord_webhook: str = ""
    email_enabled: bool = False
    email_to: str = ""


def load_settings(db: Session) -> NotifySettings:
    rows = {
        row.key: row.value
        for row in db.scalars(select(PanelSetting).where(PanelSetting.key.like(PREFIX + "%")))
    }
    webhook = rows.get(PREFIX + "discord_webhook", "")
    if webhook:
        webhook = decrypt_text(webhook, VAULT_PURPOSE) or ""
    return NotifySettings(
        discord_enabled=rows.get(PREFIX + "discord_enabled") == "1",
        discord_webhook=webhook,
        email_enabled=rows.get(PREFIX + "email_enabled") == "1",
        email_to=rows.get(PREFIX + "email_to", ""),
    )


def _put(db: Session, key: str, value: str) -> None:
    row = db.get(PanelSetting, PREFIX + key)
    if row is None:
        db.add(PanelSetting(key=PREFIX + key, value=value))
    else:
        row.value = value


def save_settings(
    db: Session,
    *,
    discord_enabled: bool,
    email_enabled: bool,
    email_to: str,
    discord_webhook: str | None,
) -> None:
    """discord_webhook: None leaves the stored URL unchanged, "" deletes it."""
    _put(db, "discord_enabled", "1" if discord_enabled else "0")
    _put(db, "email_enabled", "1" if email_enabled else "0")
    _put(db, "email_to", email_to)
    if discord_webhook is not None:
        _put(
            db,
            "discord_webhook",
            encrypt_text(discord_webhook, VAULT_PURPOSE) if discord_webhook else "",
        )
    db.commit()


def send_discord(url: str, title: str, text: str) -> tuple[bool, str]:
    content = f"**{title}**\n{text}"[:1900]
    try:
        response = httpx.post(
            url,
            json={"content": content, "allowed_mentions": {"parse": []}},
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        # Only the type, never the message: it could contain the webhook URL.
        return False, f"Request failed ({type(exc).__name__})"
    if response.status_code in (200, 204):
        return True, "OK"
    return False, f"Discord answered with HTTP {response.status_code}"


def send_email(db: Session, to: str, title: str, text: str) -> tuple[bool, str]:
    config = load_config(db)
    if not is_configured(config):
        return False, "Email delivery is not set up yet"
    html, plain = render_for(config, title, [text])
    return send_mail(to, f"EpicWing: {title}", html, plain, config)


def _attempt(channel: str, send: Callable[[], tuple[bool, str]]) -> tuple[bool, str]:
    try:
        ok, detail = send()
    except Exception as exc:  # a failed channel must never block the others
        ok, detail = False, type(exc).__name__
    if not ok:
        log.warning("Notification via %s failed: %s", channel, detail)
    return ok, detail


def notify(db: Session, title: str, text: str) -> dict[str, tuple[bool, str]]:
    """Sends to all enabled channels. Every channel is tried on its own."""
    settings = load_settings(db)
    results: dict[str, tuple[bool, str]] = {}
    if settings.discord_enabled and settings.discord_webhook:
        results["discord"] = _attempt(
            "discord", lambda: send_discord(settings.discord_webhook, title, text)
        )
    if settings.email_enabled and settings.email_to:
        results["email"] = _attempt("email", lambda: send_email(db, settings.email_to, title, text))
    if results and not any(ok for ok, _ in results.values()):
        log.error("Notification '%s' could not be delivered on any channel", title)
    return results
