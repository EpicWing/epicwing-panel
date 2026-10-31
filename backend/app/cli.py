import argparse
import getpass
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_engine
from app.models import User
from app.security import totp
from app.security.passwords import hash_password
from app.services import audit

MIN_PASSWORD_LENGTH = 8


def _normalize_email(email: str) -> str | None:
    email = email.strip().lower()
    if "@" not in email or len(email) > 320:
        print("Invalid e-mail address.", file=sys.stderr)
        return None
    return email


def _ask_password() -> str | None:
    password = getpass.getpass("Password: ")
    if len(password) < MIN_PASSWORD_LENGTH:
        print(
            f"The password must be at least {MIN_PASSWORD_LENGTH} characters long.",
            file=sys.stderr,
        )
        return None
    if password != getpass.getpass("Repeat password: "):
        print("The passwords do not match.", file=sys.stderr)
        return None
    return password


def create_admin(email: str) -> int:
    email = _normalize_email(email)
    if email is None:
        return 1
    password = _ask_password()
    if password is None:
        return 1

    with Session(get_engine()) as db:
        if db.scalar(select(User).where(User.email == email)):
            print("A user with this e-mail address already exists.", file=sys.stderr)
            return 1
        db.add(User(email=email, password_hash=hash_password(password), is_admin=True))
        db.commit()

    print(f"Administrator {email} created.")
    return 0


def set_password(email: str) -> int:
    email = _normalize_email(email)
    if email is None:
        return 1
    password = _ask_password()
    if password is None:
        return 1

    with Session(get_engine()) as db:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            print("No user with this e-mail address found.", file=sys.stderr)
            return 1
        user.password_hash = hash_password(password)
        # End all existing sessions of the user.
        for session in user.sessions:
            db.delete(session)
        db.commit()

    print("Password changed, all sessions ended.")
    return 0


def disable_2fa(email: str) -> int:
    """Emergency: turns off 2FA for a user and ends all sessions."""
    email = _normalize_email(email)
    if email is None:
        return 1

    with Session(get_engine()) as db:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            print("No user with this e-mail address found.", file=sys.stderr)
            return 1
        if user.totp_secret is None:
            print("This user has no 2FA set up.")
            return 0
        totp.disable(db, user)
        for session in user.sessions:
            db.delete(session)
        audit.record(
            db,
            "auth.2fa_disabled_cli",
            actor_id=None,
            ip=None,
            details={"user_id": str(user.id)},
        )
        db.commit()

    print("2FA turned off, all sessions ended.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="epicwing")
    sub = parser.add_subparsers(dest="command", required=True)

    admin = sub.add_parser("create-admin", help="Create the first administrator")
    admin.add_argument("--email", required=True)

    password = sub.add_parser("set-password", help="Change the password of a user")
    password.add_argument("--email", required=True)

    twofa = sub.add_parser("disable-2fa", help="Turn off 2FA for a user (emergency)")
    twofa.add_argument("--email", required=True)

    sub.add_parser("seed-eggs", help="Create the bundled eggs that are missing")

    args = parser.parse_args(argv)
    if args.command == "seed-eggs":
        from app import seed_eggs

        return seed_eggs.main()
    if args.command == "disable-2fa":
        return disable_2fa(args.email)
    if args.command == "create-admin":
        return create_admin(args.email)
    if args.command == "set-password":
        return set_password(args.email)
    return 1


if __name__ == "__main__":
    sys.exit(main())
