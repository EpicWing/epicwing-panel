"""E-Mail-Versand über Resend und das gemeinsame EpicWing-Mail-Layout."""

import sys
from datetime import UTC, datetime
from html import escape

import httpx

from app.config import get_settings

API_URL = "https://api.resend.com/emails"
DISCORD_URL = "https://discord.gg/tc7xtNPsmh"
ACCENT = "#f59e0b"
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
_P = "margin:0 0 16px;font-size:15px;line-height:24px;color:#d4d4d8;"


def _button(label: str, url: str) -> str:
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" style="margin-top:12px;">'
        f'<tr><td bgcolor="{ACCENT}" style="border-radius:10px;">'
        f'<a href="{escape(url, quote=True)}" style="display:inline-block;padding:13px 26px;'
        f"font-family:{FONT};font-size:15px;font-weight:700;color:#0a0a0a;"
        f'text-decoration:none;">{escape(label)}</a></td></tr></table>'
    )


def render(
    title: str, paragraphs: list[str], button: tuple[str, str] | None = None
) -> tuple[str, str]:
    """Baut HTML- und Textversion einer Mail im EpicWing-Design."""
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
        f"Copyright &copy; {year} EpicWing. Questions? Reply to this email or "
        f'<a href="{DISCORD_URL}" style="color:{ACCENT};text-decoration:none;">'
        "join our Discord</a>.</td></tr></table></td></tr></table></body></html>"
    )
    lines = [title, ""]
    for paragraph in paragraphs:
        lines += [paragraph, ""]
    if button:
        lines += [f"{button[0]}: {button[1]}", ""]
    lines += [f"Copyright (c) {year} EpicWing", f"Discord: {DISCORD_URL}"]
    return html, "\n".join(lines)


def send_mail(to: str, subject: str, html: str, text: str) -> tuple[bool, str]:
    """Sendet eine Mail über Resend. Wirft nie; Rückgabe: (Erfolg, ID oder Fehlertext)."""
    settings = get_settings()
    if not settings.resend_api_key:
        return False, "RESEND_API_KEY is not set"
    payload = {
        "from": settings.mail_from,
        "to": [to],
        "subject": subject,
        "html": html,
        "text": text,
    }
    if settings.mail_reply_to:
        payload["reply_to"] = settings.mail_reply_to
    try:
        response = httpx.post(
            API_URL,
            headers={
                "Authorization": f"Bearer {settings.resend_api_key}",
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


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m app.services.mail recipient@example.com")
    page, plain = render(
        "Mail delivery works",
        [
            "This is a test message from your EpicWing panel.",
            "If you can read this, the panel can send emails with your domain.",
        ],
        ("Open Discord", DISCORD_URL),
    )
    ok, info = send_mail(sys.argv[1], "EpicWing test email", page, plain)
    print(("OK, Resend id: " if ok else "FAILED: ") + info)
    sys.exit(0 if ok else 1)
