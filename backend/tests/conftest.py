"""Test fixtures: a throwaway Postgres container, migrated once per test session."""

import base64
import os
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session
from testcontainers.community.postgres import PostgresContainer

from alembic import command

os.environ.update(
    {
        "FA_ENV": "test",
        "FA_ENCRYPTION_KEY": base64.b64encode(os.urandom(32)).decode(),
        "FA_COOKIE_SECURE": "false",
        "FA_PUBLIC_ORIGIN": "http://testserver",
        "FA_WEBAUTHN_RP_ID": "testserver",
    }
)

from app import push
from app.config import get_settings
from app.db import get_engine, get_sessionmaker
from app.main import create_app
from app.models import Household, HouseholdMember, HouseholdRole, User
from app.models.base import utcnow
from app.security.passwords import hash_password
from tests.helpers import World

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_PASSWORD = "correct horse battery"


def _clear_caches() -> None:
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()


@pytest.fixture(scope="session", autouse=True)
def database() -> Iterator[None]:
    with PostgresContainer("postgres:18-alpine", username="finance", password="test", dbname="finance") as pg:
        os.environ.update(
            {
                "FA_DB_HOST": pg.get_container_host_ip(),
                "FA_DB_PORT": str(pg.get_exposed_port(5432)),
                "FA_DB_PASSWORD": "test",
            }
        )
        _clear_caches()
        command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), "head")
        yield
        get_engine().dispose()
        _clear_caches()


@pytest.fixture(autouse=True)
def _no_push_quiet_hours(monkeypatch: pytest.MonkeyPatch) -> None:
    """Push dispatch pauses at night; tests must not depend on the wall clock.

    Quiet-hour tests override this, and `app.push.in_quiet_hours` imported by name stays the real one.
    """
    monkeypatch.setattr(push, "in_quiet_hours", lambda _moment: False)


@pytest.fixture(autouse=True)
def _clean_tables() -> Iterator[None]:
    yield
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "TRUNCATE audit_log, auth_challenges, user_sessions, webauthn_credentials, "
                "invites, household_members, users, households CASCADE"
            )
        )


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def db() -> Iterator[Session]:
    with get_sessionmaker()() as session:
        yield session


UserFactory = Callable[..., User]


@pytest.fixture
def make_user(db: Session) -> UserFactory:
    household_cache: dict[str, Household] = {}

    def factory(
        email: str = "owner@example.com",
        role: HouseholdRole = HouseholdRole.OWNER,
        household: str = "Zuhause",
        password: str = DEFAULT_PASSWORD,
    ) -> User:
        if household not in household_cache:
            household_cache[household] = Household(id=uuid.uuid4(), name=household)
            db.add(household_cache[household])
        user = User(
            id=uuid.uuid4(),
            email=email,
            display_name=email.split("@", maxsplit=1)[0].title(),
            password_hash=hash_password(password),
            is_active=True,
            failed_login_count=0,
        )
        db.add(user)
        db.add(
            HouseholdMember(household=household_cache[household], user=user, role=role, joined_at=utcnow())
        )
        db.commit()
        return user

    return factory


def login(client: TestClient, email: str, password: str = DEFAULT_PASSWORD) -> dict[str, object]:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    return body


@pytest.fixture
def client_for(client: TestClient) -> Callable[[str], TestClient]:
    """Log in another user in a separate cookie jar."""

    def factory(email: str) -> TestClient:
        other = TestClient(client.app)
        login(other, email)
        return other

    return factory


@pytest.fixture
def world(make_user: UserFactory, client_for: Callable[[str], TestClient]) -> World:
    owner = make_user("owner@example.com")
    member = make_user("member@example.com", role=HouseholdRole.MEMBER)
    stranger = make_user("stranger@example.com", household="Nachbarn")
    return World(
        owner=client_for("owner@example.com"),
        member=client_for("member@example.com"),
        stranger=client_for("stranger@example.com"),
        owner_user=owner,
        member_user=member,
        stranger_user=stranger,
    )
