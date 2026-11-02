"""The footer is always in the mail, the reply note only with Reply-To."""

from app.services.mail import MailConfig, render, render_for


def test_footer_is_always_present():
    html, text = render("Hi", ["Body"])
    parts = (
        "Powered by",
        "https://epicwing.de",
        "not by EpicWing",
        "not the official EpicWing logo",
    )
    for part in parts:
        assert part in html
    assert "Powered by EpicWing (https://epicwing.de)" in text
    assert "not by EpicWing" in text
    assert "not the official EpicWing logo" in text


def test_footer_present_with_empty_config():
    html, text = render_for(MailConfig(), "Hi", ["Body"])
    assert "Powered by" in html
    assert "Powered by" in text


def test_reply_hint_only_with_reply_to():
    html, text = render_for(MailConfig(), "Hi", ["Body"])
    assert "Reply to this email" not in html
    assert "Reply to this email" not in text
    html, text = render_for(MailConfig(reply_to="support@example.com"), "Hi", ["Body"])
    assert "Reply to this email" in html
    assert "Reply to this email" in text


def test_no_discord_in_mail():
    html, text = render_for(MailConfig(reply_to="support@example.com"), "Hi", ["Body"])
    assert "discord" not in html.lower()
    assert "discord" not in text.lower()


def test_abuse_contact_is_always_present():
    html, text = render("Hi", ["Body"])
    assert "mailto:abuse@epicwing.de" in html
    assert "Report abuse: abuse@epicwing.de" in text
    html, text = render_for(MailConfig(), "Hi", ["Body"])
    assert "abuse@epicwing.de" in html
    assert "abuse@epicwing.de" in text
