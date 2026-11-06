from app.services.node_limits import exceeds


def test_no_limit_never_exceeds():
    assert not exceeds(None, 500, 10_000, None)


def test_fits_exactly():
    assert not exceeds(1000, 500, 500, None)


def test_new_server_over_limit():
    assert exceeds(1000, 500, 501, None)


def test_unlimited_server_rejected_on_limited_node():
    assert exceeds(1000, 0, 0, None)


def test_unchanged_value_is_always_fine():
    assert not exceeds(1000, 5000, 700, 700)


def test_lowering_is_fine_even_when_node_is_over():
    assert not exceeds(1000, 5000, 400, 700)


def test_raising_over_limit_is_rejected():
    assert exceeds(1000, 600, 500, 300)


def test_changing_to_unlimited_is_rejected():
    assert exceeds(1000, 0, 0, 512)
