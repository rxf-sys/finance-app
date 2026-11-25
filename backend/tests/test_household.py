from fastapi.testclient import TestClient

from app.models import HouseholdRole
from tests.conftest import UserFactory, login

NEW_PASSWORD = "member passphrase 123"


def _invite(client: TestClient, email: str = "partner@example.com") -> dict[str, str]:
    response = client.post("/api/household/invites", json={"email": email})
    assert response.status_code == 201, response.text
    body: dict[str, str] = response.json()
    return body


def test_owner_invites_member_who_joins(client: TestClient, make_user: UserFactory) -> None:
    make_user()
    login(client, "owner@example.com")
    created = _invite(client)
    token = created["invite_url"].rsplit("/", 1)[1]
    assert [i["email"] for i in client.get("/api/household/invites").json()] == ["partner@example.com"]

    client.post("/api/auth/logout")
    info = client.get(f"/api/auth/invites/{token}").json()
    assert info == {
        "email": "partner@example.com",
        "household_name": "Zuhause",
        "expires_at": info["expires_at"],
    }

    joined = client.post(
        "/api/auth/invites/accept",
        json={"token": token, "display_name": "Partner", "password": NEW_PASSWORD},
    )
    assert joined.status_code == 200
    assert joined.json()["user"]["role"] == "member"

    members = client.get("/api/household").json()["members"]
    assert {m["email"] for m in members} == {"owner@example.com", "partner@example.com"}
    # The invite is single-use.
    again = client.post(
        "/api/auth/invites/accept",
        json={"token": token, "display_name": "Someone", "password": NEW_PASSWORD},
    )
    assert again.status_code == 404


def test_member_cannot_invite_or_remove(client: TestClient, make_user: UserFactory) -> None:
    owner = make_user()
    make_user("member@example.com", role=HouseholdRole.MEMBER)
    login(client, "member@example.com")

    assert client.post("/api/household/invites", json={"email": "x@example.com"}).status_code == 403
    assert client.delete(f"/api/household/members/{owner.id}").status_code == 403


def test_owner_removes_member_and_their_sessions(client: TestClient, make_user: UserFactory) -> None:
    make_user()
    member = make_user("member@example.com", role=HouseholdRole.MEMBER)

    member_client = TestClient(client.app)
    login(member_client, "member@example.com")
    login(client, "owner@example.com")

    assert client.delete(f"/api/household/members/{member.id}").status_code == 204
    assert member_client.get("/api/auth/me").status_code == 401
    assert [m["email"] for m in client.get("/api/household").json()["members"]] == ["owner@example.com"]


def test_households_are_isolated(client: TestClient, make_user: UserFactory) -> None:
    make_user()
    other = make_user("other@example.com", household="Nachbarn")
    login(client, "owner@example.com")

    assert client.delete(f"/api/household/members/{other.id}").status_code == 404
    assert len(client.get("/api/household").json()["members"]) == 1


def test_invite_for_existing_account_is_rejected(client: TestClient, make_user: UserFactory) -> None:
    make_user()
    make_user("taken@example.com", household="Nachbarn")
    login(client, "owner@example.com")

    assert client.post("/api/household/invites", json={"email": "taken@example.com"}).status_code == 409
