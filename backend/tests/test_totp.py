import pyotp
from sqlalchemy import select

from app.models import RecoveryCode
from app.security import totp

T = 1_800_000_000  # liegt genau auf einer Zeitschrittgrenze


def _code(secret: str, at: int) -> str:
    return pyotp.TOTP(secret).at(at)


def _wrong(code: str) -> str:
    return str((int(code) + 1) % 1_000_000).zfill(6)


def test_secret_is_encrypted_at_rest(db_session, user):
    secret = totp.begin_enrollment(db_session, user)
    assert secret not in user.totp_secret
    assert totp.decrypt_secret(user.totp_secret) == secret
    assert not totp.is_enabled(user)


def test_valid_and_invalid_codes(db_session, user):
    secret = totp.begin_enrollment(db_session, user)
    good = _code(secret, T)
    assert totp.verify_code(db_session, user, _wrong(good), now=T) is False
    assert totp.verify_code(db_session, user, "abcdef", now=T) is False
    assert totp.verify_code(db_session, user, "12345", now=T) is False
    assert totp.verify_code(db_session, user, f"{good[:3]} {good[3:]}", now=T) is True


def test_code_cannot_be_reused(db_session, user):
    secret = totp.begin_enrollment(db_session, user)
    good = _code(secret, T)
    assert totp.verify_code(db_session, user, good, now=T) is True
    assert totp.verify_code(db_session, user, good, now=T) is False


def test_time_window_and_order(db_session, user):
    secret = totp.begin_enrollment(db_session, user)
    assert totp.verify_code(db_session, user, _code(secret, T - 60), now=T) is False
    assert totp.verify_code(db_session, user, _code(secret, T - 30), now=T) is True
    assert totp.verify_code(db_session, user, _code(secret, T), now=T) is True
    assert totp.verify_code(db_session, user, _code(secret, T - 30), now=T) is False


def test_tampered_or_missing_secret(db_session, user):
    assert totp.verify_code(db_session, user, "123456", now=T) is False
    user.totp_secret = "kein-gueltiger-token"
    db_session.commit()
    assert totp.decrypt_secret(user.totp_secret) is None
    assert totp.verify_code(db_session, user, "123456", now=T) is False


def test_recovery_codes(db_session, user):
    codes = totp.generate_recovery_codes(db_session, user)
    assert len(codes) == 10 and len(set(codes)) == 10
    stored = db_session.scalars(select(RecoveryCode.code_hash)).all()
    assert len(stored) == 10
    assert all(len(h) == 64 and h not in codes for h in stored)

    assert totp.consume_recovery_code(db_session, user, codes[0]) is True
    assert totp.consume_recovery_code(db_session, user, codes[0]) is False
    assert totp.consume_recovery_code(db_session, user, codes[1].lower().replace("-", "")) is True
    assert totp.consume_recovery_code(db_session, user, "AAAA-AAAA-AAAA") is False
    assert totp.remaining_recovery_codes(db_session, user) == 8

    new_codes = totp.generate_recovery_codes(db_session, user)
    assert totp.consume_recovery_code(db_session, user, codes[2]) is False
    assert totp.consume_recovery_code(db_session, user, new_codes[0]) is True


def test_activate_and_disable(db_session, user):
    secret = totp.begin_enrollment(db_session, user)
    assert totp.verify_code(db_session, user, _code(secret, T), now=T) is True
    codes = totp.activate(db_session, user)
    assert totp.is_enabled(user) and len(codes) == 10
    try:
        totp.begin_enrollment(db_session, user)
        raise AssertionError("Neu einrichten bei aktiver 2FA muss scheitern")
    except ValueError:
        pass

    totp.disable(db_session, user)
    assert user.totp_secret is None and user.totp_enabled_at is None
    assert user.totp_last_step is None
    assert totp.remaining_recovery_codes(db_session, user) == 0
