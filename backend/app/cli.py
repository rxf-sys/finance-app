"""Admin commands, run inside the api container:

python -m app.cli create-owner --email you@example.com --name "Robin" --household "Zuhause"
python -m app.cli reset-totp --email you@example.com
python -m app.cli export-openapi > openapi.json
python -m app.cli generate-key
"""

import argparse
import getpass
import json
import sys
import uuid

from sqlalchemy import select

from app.db import get_sessionmaker
from app.finance.default_categories import seed_default_categories
from app.models import AuditLog, Household, HouseholdMember, HouseholdRole, User
from app.models.base import utcnow
from app.security.crypto import generate_key
from app.security.passwords import MIN_PASSWORD_LENGTH, hash_password


def _read_new_password() -> str:
    while True:
        password = getpass.getpass("Password: ")
        if len(password) < MIN_PASSWORD_LENGTH:
            print(f"At least {MIN_PASSWORD_LENGTH} characters, please.", file=sys.stderr)
            continue
        if password != getpass.getpass("Repeat password: "):
            print("Passwords do not match.", file=sys.stderr)
            continue
        return password


def create_owner(email: str, name: str, household_name: str) -> int:
    email = email.strip().lower()
    with get_sessionmaker().begin() as db:
        if db.scalar(select(User.id).where(User.email == email)) is not None:
            print(f"User {email} already exists.", file=sys.stderr)
            return 1
        password = _read_new_password()
        household = Household(id=uuid.uuid4(), name=household_name)
        user = User(
            id=uuid.uuid4(),
            email=email,
            display_name=name,
            password_hash=hash_password(password),
            is_active=True,
            failed_login_count=0,
        )
        db.add_all([household, user])
        db.add(HouseholdMember(household=household, user=user, role=HouseholdRole.OWNER, joined_at=utcnow()))
        db.flush()  # the audit row references the user, so insert the user first
        seed_default_categories(db, household.id)
        db.add(AuditLog(action="owner_created_cli", user_id=user.id, details={"email": email}))
    print(f"Created household '{household_name}' with owner {email}.")
    return 0


def reset_totp(email: str) -> int:
    email = email.strip().lower()
    with get_sessionmaker().begin() as db:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            print(f"User {email} not found.", file=sys.stderr)
            return 1
        user.totp_secret_encrypted = None
        user.totp_enabled_at = None
        user.totp_last_used_step = None
        user.locked_until = None
        user.failed_login_count = 0
        db.add(AuditLog(action="totp_reset_cli", user_id=user.id, details={}))
    print(f"TOTP removed for {email}. The user should set it up again after login.")
    return 0


def export_openapi() -> int:
    # Imported here so the other commands do not need the full app settings.
    from app.main import create_app

    json.dump(create_app().openapi(), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)

    owner = commands.add_parser("create-owner", help="Create the household and its owner")
    owner.add_argument("--email", required=True)
    owner.add_argument("--name", required=True)
    owner.add_argument("--household", required=True)

    reset = commands.add_parser("reset-totp", help="Remove TOTP for a user who lost the device")
    reset.add_argument("--email", required=True)

    commands.add_parser("export-openapi", help="Print the OpenAPI schema as JSON")
    commands.add_parser("generate-key", help="Print a new FA_ENCRYPTION_KEY value")

    args = parser.parse_args(argv)
    match args.command:
        case "create-owner":
            return create_owner(args.email, args.name, args.household)
        case "reset-totp":
            return reset_totp(args.email)
        case "export-openapi":
            return export_openapi()
        case "generate-key":
            print(generate_key())
            return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
