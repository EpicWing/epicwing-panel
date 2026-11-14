from app.services import secretvars


def test_roundtrip():
    sealed = secretvars.seal("abc.def-token")
    assert sealed.startswith("enc:")
    assert "abc.def-token" not in sealed
    assert secretvars.unseal(sealed) == "abc.def-token"


def test_empty_stays_empty():
    assert secretvars.seal("") == ""
    assert secretvars.unseal("") == ""


def test_plain_text_from_before_is_still_readable():
    assert secretvars.unseal("plain-token") == "plain-token"


def test_broken_value_gives_empty_string():
    assert secretvars.unseal("enc:not-a-token") == ""
