import types

from app.services import eggio


def _egg(features):
    return {
        "meta": {"version": "PTDL_v2"},
        "name": "Test egg",
        "description": "",
        "features": features,
        "docker_images": {"Java": "ghcr.io/ptero-eggs/yolks:java_21"},
        "startup": "./run",
        "config": {},
        "scripts": {"installation": {"script": "", "container": "alpine:3.4", "entrypoint": "ash"}},
        "variables": [],
    }


def _roundtrip(data):
    fields, config, warnings = eggio.import_egg(data)
    flds = dict(fields)
    variables = flds.pop("variables")
    egg = types.SimpleNamespace(**flds, config=config)
    return eggio.export_egg(egg, [types.SimpleNamespace(**v) for v in variables]), warnings


def test_eula_is_supported_and_not_reported_as_ignored():
    out, warnings = _roundtrip(_egg(["eula"]))
    assert not any("features" in w for w in warnings)
    assert out["features"] == ["eula"]


def test_only_unsupported_features_are_reported():
    out, warnings = _roundtrip(_egg(["eula", "pid_limit"]))
    message = " ".join(w for w in warnings if "features" in w)
    assert "pid_limit" in message and "eula" not in message
    assert out["features"] == ["eula", "pid_limit"]


def test_no_features_exports_null():
    out, warnings = _roundtrip(_egg(None))
    assert out["features"] is None
    assert not any("features" in w for w in warnings)
