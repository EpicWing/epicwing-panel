from argon2 import PasswordHasher

from app.security import passwords


def test_production_hasher_uses_default_parameters(
    production_password_hasher: PasswordHasher,
) -> None:
    # Schützt davor, die Produktionsparameter versehentlich abzuschwächen.
    defaults = PasswordHasher()
    assert production_password_hasher.time_cost == defaults.time_cost
    assert production_password_hasher.memory_cost == defaults.memory_cost
    assert production_password_hasher.parallelism == defaults.parallelism
    assert production_password_hasher.hash_len == defaults.hash_len
    assert production_password_hasher.salt_len == defaults.salt_len


def test_fast_hasher_is_active_in_tests() -> None:
    assert passwords._hasher.time_cost == 1
    assert passwords._hasher.memory_cost == 8
    assert passwords._hasher.parallelism == 1
