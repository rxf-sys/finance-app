import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import cli
from app.models import AuditLog, HouseholdRole, User


def test_create_owner_creates_household_and_audit_entry(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_read_new_password", lambda: "owner passphrase 2026")

    assert (
        cli.main(
            ["create-owner", "--email", "Robin@Example.com", "--name", "Robin", "--household", "Zuhause"]
        )
        == 0
    )

    user = db.scalar(select(User).where(User.email == "robin@example.com"))
    assert user is not None and user.membership is not None
    assert user.membership.role is HouseholdRole.OWNER
    assert user.membership.household.name == "Zuhause"
    assert db.scalar(select(AuditLog.action).where(AuditLog.user_id == user.id)) == "owner_created_cli"


def test_create_owner_refuses_duplicates(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_read_new_password", lambda: "owner passphrase 2026")
    args = ["create-owner", "--email", "robin@example.com", "--name", "Robin", "--household", "Zuhause"]

    assert cli.main(args) == 0
    assert cli.main(args) == 1


def test_reset_totp_clears_secret_and_lock(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_read_new_password", lambda: "owner passphrase 2026")
    cli.main(["create-owner", "--email", "robin@example.com", "--name", "Robin", "--household", "Zuhause"])
    user = db.scalar(select(User).where(User.email == "robin@example.com"))
    assert user is not None
    user.totp_secret_encrypted = b"x"
    user.failed_login_count = 3
    db.commit()

    assert cli.main(["reset-totp", "--email", "robin@example.com"]) == 0

    db.expire_all()
    assert user.totp_secret_encrypted is None and user.failed_login_count == 0
