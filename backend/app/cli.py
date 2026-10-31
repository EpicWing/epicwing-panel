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

MIN_PASSWORD_LENGTH = 1


def _normalize_email(email: str) -> str | None:
    email = email.strip().lower()
    if "@" not in email or len(email) > 320:
        print("Ungültige E-Mail-Adresse.", file=sys.stderr)
        return None
    return email


def _ask_password() -> str | None:
    password = getpass.getpass("Passwort: ")
    if len(password) < MIN_PASSWORD_LENGTH:
        print(
            f"Das Passwort muss mindestens {MIN_PASSWORD_LENGTH} Zeichen lang sein.",
            file=sys.stderr,
        )
        return None
    if password != getpass.getpass("Passwort wiederholen: "):
        print("Die Passwörter stimmen nicht überein.", file=sys.stderr)
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
            print("Ein Benutzer mit dieser E-Mail existiert bereits.", file=sys.stderr)
            return 1
        db.add(User(email=email, password_hash=hash_password(password), is_admin=True))
        db.commit()

    print(f"Admin {email} wurde angelegt.")
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
            print("Kein Benutzer mit dieser E-Mail gefunden.", file=sys.stderr)
            return 1
        user.password_hash = hash_password(password)
        # Alle bestehenden Sessions des Benutzers beenden.
        for session in user.sessions:
            db.delete(session)
        db.commit()

    print("Passwort wurde geändert, alle Sessions wurden beendet.")
    return 0


def disable_2fa(email: str) -> int:
    """Notfall: schaltet die 2FA eines Benutzers ab und beendet alle Sessions."""
    email = _normalize_email(email)
    if email is None:
        return 1

    with Session(get_engine()) as db:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            print("Kein Benutzer mit dieser E-Mail gefunden.", file=sys.stderr)
            return 1
        if user.totp_secret is None:
            print("Für diesen Benutzer ist keine 2FA eingerichtet.")
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

    print("2FA wurde abgeschaltet, alle Sessions wurden beendet.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="epicwing")
    sub = parser.add_subparsers(dest="command", required=True)

    admin = sub.add_parser("create-admin", help="Ersten Administrator anlegen")
    admin.add_argument("--email", required=True)

    password = sub.add_parser("set-password", help="Passwort eines Benutzers ändern")
    password.add_argument("--email", required=True)

    twofa = sub.add_parser("disable-2fa", help="2FA eines Benutzers abschalten (Notfall)")
    twofa.add_argument("--email", required=True)

    sub.add_parser("seed-eggs", help="Mitgelieferte Eggs anlegen, die noch fehlen")

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
