from app.services import startup


def test_render_replaces_known_placeholders_only():
    text = "a {{SERVER_MEMORY}} {{ SERVER_PORT }} {{MOTD}} {{OTHER}}"
    assert startup.render(text, {"MOTD": "hi"}, 512, "1.2.3.4", 25565) == "a 512 25565 hi {{OTHER}}"


def test_render_supports_old_pterodactyl_names():
    text = "{{server.build.default.port}} {{server.build.memory}} {{env.MOTD}}"
    assert startup.render(text, {"MOTD": "hi"}, 256, "1.2.3.4", 25565) == "25565 256 hi"


def test_render_keeps_address_placeholders_without_allocation():
    assert startup.render("{{SERVER_IP}}:{{SERVER_PORT}}", {}, 256, None, None) == (
        "{{SERVER_IP}}:{{SERVER_PORT}}"
    )


def test_render_does_not_expand_values_again():
    out = startup.render("{{A}}", {"A": "{{SERVER_MEMORY}}"}, 256, None, None)
    assert out == "{{SERVER_MEMORY}}"


def test_unknown_lists_missing_names():
    assert startup.unknown("x {{A}} {{SERVER_IP}} {{B}} {{env.A}}", ["A"]) == ["B"]
    assert startup.unknown("nginx -g 'daemon off;'", []) == []


def test_render_uses_host_memory_for_unlimited_servers():
    out = startup.render("-Xmx{{SERVER_MEMORY}}M", {}, 0, None, None, host_memory_mb=8192)
    assert out == "-Xmx8192M"


def test_render_keeps_placeholder_for_unlimited_without_host_memory():
    assert startup.render("{{SERVER_MEMORY}}", {}, 0, None, None) == "{{SERVER_MEMORY}}"


def test_render_ignores_variables_named_like_builtins():
    assert startup.render("{{SERVER_MEMORY}}", {"SERVER_MEMORY": "1"}, 256, None, None) == "256"
