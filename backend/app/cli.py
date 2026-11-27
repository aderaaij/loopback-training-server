"""Admin CLI for user + token management.

Run inside the backend container, e.g.:

    docker exec -it backend__training-api python -m app.cli list-users
    docker exec -it backend__training-api python -m app.cli create-user alice
    docker exec -it backend__training-api python -m app.cli create-token alice --name "iPhone"
    docker exec -it backend__training-api python -m app.cli create-token alice --name "Coach · my agent" --coach

`bootstrap` is invoked automatically on container start (scripts/start.sh) and
applies BOOTSTRAP_ADMIN_PASSWORD to the admin account once, if it has none yet.
"""

import argparse
import getpass
import sys

from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models.api_token import ApiToken
from app.models.user import User
from app.security import generate_token, hash_password, hash_token
from app.token_scope import COACH, FULL


def _prompt_password() -> str:
    pw = getpass.getpass("Password: ")
    if pw != getpass.getpass("Confirm password: "):
        sys.exit("Passwords do not match.")
    if not pw:
        sys.exit("Password must not be empty.")
    return pw


def cmd_bootstrap(_args: argparse.Namespace) -> None:
    settings = get_settings()
    password = settings.bootstrap_admin_password
    username = settings.bootstrap_admin_username.strip().lower()
    if not password:
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.username == username))
        if user is None or user.password_hash is None:
            print(
                f"bootstrap: admin '{username}' has no password yet — open the dashboard in a browser\n"
                "           to finish first-run setup (create the admin account there). Alternatively,\n"
                "           set BOOTSTRAP_ADMIN_PASSWORD in .env and restart, or run:\n"
                f"           docker compose exec app python -m app.cli set-password {username}"
            )
        else:
            print("bootstrap: BOOTSTRAP_ADMIN_PASSWORD not set — admin already configured, skipping.")
        return
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == username))
        if user is None:
            db.add(User(username=username, role="admin", display_name="Admin", password_hash=hash_password(password)))
            db.commit()
            print(f"bootstrap: created admin '{username}'.")
        elif user.password_hash is None:
            user.password_hash = hash_password(password)
            if user.role != "admin":
                user.role = "admin"
            db.commit()
            print(f"bootstrap: set password for admin '{username}'.")
        else:
            print(f"bootstrap: admin '{username}' already has a password — unchanged.")


def cmd_create_user(args: argparse.Namespace) -> None:
    username = args.username.strip().lower()
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.username == username)):
            sys.exit(f"User '{username}' already exists.")
        password = _prompt_password()
        db.add(
            User(
                username=username,
                display_name=args.display_name or username,
                role="admin" if args.admin else "user",
                password_hash=hash_password(password),
            )
        )
        db.commit()
        print(f"Created {'admin' if args.admin else 'user'} '{username}'.")


def cmd_set_password(args: argparse.Namespace) -> None:
    username = args.username.strip().lower()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == username))
        if user is None:
            sys.exit(f"No such user '{username}'.")
        user.password_hash = hash_password(_prompt_password())
        db.commit()
        print(f"Password updated for '{username}'.")


def cmd_create_token(args: argparse.Namespace) -> None:
    username = args.username.strip().lower()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == username))
        if user is None:
            sys.exit(f"No such user '{username}'.")
        raw = generate_token()
        scope = COACH if args.coach else FULL
        db.add(ApiToken(user_id=user.id, token_hash=hash_token(raw), name=args.name or "", scope=scope))
        db.commit()
        print(f"Token for '{username}' ({args.name or 'unnamed'}) — shown once, store it now:\n\n  {raw}\n")


def cmd_list_users(_args: argparse.Namespace) -> None:
    with SessionLocal() as db:
        users = db.scalars(select(User).order_by(User.created_at)).all()
        if not users:
            print("(no users)")
            return
        for u in users:
            token_count = len(db.scalars(select(ApiToken.id).where(ApiToken.user_id == u.id)).all())
            state = "active" if u.is_active else "inactive"
            pw = "set" if u.password_hash else "no-password"
            print(f"{u.username:<20} {u.role:<6} {state:<9} {pw:<12} tokens={token_count}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.cli", description="Training API user/token admin")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("bootstrap", help="Apply BOOTSTRAP_ADMIN_PASSWORD if admin has none").set_defaults(func=cmd_bootstrap)

    p = sub.add_parser("create-user", help="Create a user (prompts for password)")
    p.add_argument("username")
    p.add_argument("--display-name", default=None)
    p.add_argument("--admin", action="store_true")
    p.set_defaults(func=cmd_create_user)

    p = sub.add_parser("set-password", help="Set/replace a user's password")
    p.add_argument("username")
    p.set_defaults(func=cmd_set_password)

    p = sub.add_parser("create-token", help="Create an API token for a user (printed once)")
    p.add_argument("username")
    p.add_argument("--name", default="")
    p.add_argument(
        "--coach", action="store_true",
        help="A token for an AI assistant: it can do what the coach's tools do and nothing else",
    )
    p.set_defaults(func=cmd_create_token)

    sub.add_parser("list-users", help="List users").set_defaults(func=cmd_list_users)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
