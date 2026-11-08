import pytest

from app.services import dbhost


@pytest.mark.parametrize(
    "kwargs",
    [
        {"name": "shop\n"},
        {"name": "a`b"},
        {"user": "u1\n"},
        {"remote": "10.0.0.1\n"},
        {"remote": "10.0.0.1'"},
    ],
)
def test_check_rejects_unsafe_values(kwargs):
    with pytest.raises(ValueError):
        dbhost._check(**kwargs)


def test_check_accepts_normal_values():
    dbhost._check("shop_1", "u0123456789ab", "10.0.%")
