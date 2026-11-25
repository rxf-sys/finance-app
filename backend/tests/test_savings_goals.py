import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.finance.contracts import today_berlin
from app.finance.goals import compute_progress, months_left
from app.models import AccountVisibility
from tests.helpers import World, make_account, make_tx

GOALS = "/api/savings-goals"


def _create(client: Any, **overrides: Any) -> Any:
    body = {"name": "Urlaub", "target_cents": 100_000, **overrides}
    return client.post(GOALS, json=body)


def test_months_left_and_progress_math() -> None:
    today = date(2026, 11, 25)
    assert months_left(today, date(2026, 11, 30)) == 1
    assert months_left(today, date(2026, 12, 1)) == 1
    assert months_left(today, date(2027, 3, 1)) == 4
    assert months_left(today, date(2026, 1, 1)) == 1
    p = compute_progress(10_000, 100_000, date(2027, 2, 1), today)  # 3 months, 90_000 left
    assert (p.percent, p.remaining_cents, p.monthly_needed_cents, p.achieved) == (10, 90_000, 30_000, False)
    assert compute_progress(0, 100_000, date(2027, 2, 1), today).monthly_needed_cents == 33_334  # ceil
    done = compute_progress(150_000, 100_000, date(2027, 2, 1), today)
    assert (done.percent, done.remaining_cents, done.monthly_needed_cents, done.achieved) == (
        150,
        0,
        None,
        True,
    )
    assert compute_progress(-500, 100_000, None, today).percent == 0
    assert compute_progress(5, 100_000, None, today).monthly_needed_cents is None


def test_goal_crud(world: World) -> None:
    target = (today_berlin() + timedelta(days=95)).isoformat()
    response = _create(
        world.owner, target_date=target, icon="plane", color="chart-2", note="Sommer", name="  Urlaub "
    )
    assert response.status_code == 201, response.text
    goal = response.json()
    assert goal["name"] == "Urlaub"
    assert goal["visibility"] == "shared"
    assert goal["archived"] is False
    assert goal["progress_cents"] == 0 and goal["percent"] == 0
    assert goal["remaining_cents"] == 100_000
    assert goal["monthly_needed_cents"] is not None and goal["monthly_needed_cents"] >= 100_000 // 5
    url = f"{GOALS}/{goal['id']}"

    # Any member may edit a shared goal.
    patched = world.member.patch(url, json={"name": "Reise", "target_cents": 200_000, "note": None})
    assert patched.status_code == 200, patched.text
    assert patched.json()["name"] == "Reise"
    assert patched.json()["note"] is None
    assert patched.json()["icon"] == "plane"
    assert world.owner.patch(url, json={"name": None}).status_code == 422
    assert world.owner.patch(url, json={"target_cents": 0}).status_code == 422

    archived = world.owner.patch(url, json={"archived": True}).json()
    assert archived["archived"] is True and archived["archived_at"] is not None
    assert world.owner.get(GOALS).json() == []
    assert [g["id"] for g in world.owner.get(GOALS, params={"include_archived": True}).json()] == [goal["id"]]
    assert world.owner.patch(url, json={"archived": False}).json()["archived_at"] is None
    assert len(world.member.get(GOALS).json()) == 1

    assert world.member.delete(url).status_code == 204
    assert world.owner.get(url).status_code == 404


def test_create_validation(world: World, db: Session) -> None:
    assert _create(world.owner, target_cents=0).status_code == 422
    assert _create(world.owner, name="").status_code == 422
    today = today_berlin().isoformat()
    assert _create(world.owner, target_date=today).status_code == 422
    past = (today_berlin() - timedelta(days=1)).isoformat()
    assert _create(world.owner, target_date=past).status_code == 422
    assert _create(world.owner, account_id=str(uuid.uuid4())).status_code == 404


def test_private_account_rule(world: World, db: Session) -> None:
    private = make_account(db, world.owner_user, "Privat", AccountVisibility.PRIVATE)
    shared = make_account(db, world.owner_user, "Gemeinsam")

    # Hidden account: 404 for the member.
    assert _create(world.member, account_id=str(private.id)).status_code == 404
    # Shared goal on a private account: rejected.
    assert _create(world.owner, account_id=str(private.id)).status_code == 422
    ok = _create(world.owner, account_id=str(private.id), visibility="private")
    assert ok.status_code == 201, ok.text
    assert ok.json()["account_name"] == "Privat"

    # PATCH: cannot make it shared, cannot move a shared goal onto the private account.
    assert world.owner.patch(f"{GOALS}/{ok.json()['id']}", json={"visibility": "shared"}).status_code == 422
    loose = _create(world.owner, account_id=str(shared.id)).json()
    url = f"{GOALS}/{loose['id']}"
    assert world.owner.patch(url, json={"account_id": str(private.id)}).status_code == 422
    assert (
        world.owner.patch(url, json={"account_id": str(private.id), "visibility": "private"}).status_code
        == 200
    )
    # Unlinking is allowed again and rolled-back attempts changed nothing.
    assert world.owner.patch(url, json={"account_id": None}).json()["account_id"] is None


def test_account_progress_and_contribution_conflict(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user, "Sparen", opening=10_000)
    make_tx(db, account, 40_000, date(2026, 1, 5))
    make_tx(db, account, -5_000, date(2026, 1, 6))
    goal = _create(world.owner, target_cents=90_000, account_id=str(account.id)).json()
    assert goal["progress_cents"] == 45_000
    assert goal["percent"] == 50
    assert goal["remaining_cents"] == 45_000
    assert goal["achieved"] is False
    response = world.owner.post(
        f"{GOALS}/{goal['id']}/contributions",
        json={"amount_cents": 100, "booked_on": today_berlin().isoformat()},
    )
    assert response.status_code == 409
    make_tx(db, account, 60_000, date(2026, 1, 7))
    assert world.member.get(f"{GOALS}/{goal['id']}").json()["achieved"] is True
    assert world.member.get(f"{GOALS}/{goal['id']}").json()["percent"] == 116


def test_contributions(world: World) -> None:
    goal = _create(world.owner, target_cents=50_000).json()
    base = f"{GOALS}/{goal['id']}"
    today = today_berlin()

    def post(**body: Any) -> Any:
        return world.member.post(f"{base}/contributions", json=body)

    assert post(amount_cents=0, booked_on=today.isoformat()).status_code == 422
    assert post(amount_cents=100, booked_on=(today + timedelta(days=1)).isoformat()).status_code == 422
    assert post(amount_cents=100, booked_on=today.isoformat(), note="x" * 201).status_code == 422
    first = post(amount_cents=30_000, booked_on=(today - timedelta(days=2)).isoformat(), note="Anfang")
    assert first.status_code == 201, first.text
    second = post(amount_cents=-5_000, booked_on=today.isoformat())
    body = second.json()
    assert body["progress_cents"] == 25_000
    assert body["percent"] == 50
    assert [c["amount_cents"] for c in body["contributions"]] == [30_000, -5_000]
    assert world.owner.get(GOALS).json()[0]["contributions"] == []  # list omits them
    assert world.owner.get(GOALS).json()[0]["progress_cents"] == 25_000

    contribution_id = body["contributions"][0]["id"]
    assert world.owner.delete(f"{base}/contributions/{uuid.uuid4()}").status_code == 404
    deleted = world.owner.delete(f"{base}/contributions/{contribution_id}")
    assert deleted.status_code == 200
    assert deleted.json()["progress_cents"] == -5_000
    assert deleted.json()["percent"] == 0
    assert deleted.json()["remaining_cents"] == 55_000

    assert world.owner.patch(base, json={"archived": True}).status_code == 200
    assert post(amount_cents=100, booked_on=today.isoformat()).status_code == 409


def test_private_goal_visibility_and_isolation(world: World, db: Session) -> None:
    goal = _create(world.owner, visibility="private").json()
    url = f"{GOALS}/{goal['id']}"
    assert world.owner.get(url).status_code == 200
    assert world.member.get(GOALS).json() == []
    for client in (world.member, world.stranger):
        assert client.get(url).status_code == 404
        assert client.patch(url, json={"name": "x"}).status_code == 404
        assert client.delete(url).status_code == 404
        assert (
            client.post(
                f"{url}/contributions", json={"amount_cents": 1, "booked_on": today_berlin().isoformat()}
            ).status_code
            == 404
        )
        assert client.delete(f"{url}/contributions/{uuid.uuid4()}").status_code == 404
    assert world.owner.get(url).status_code == 200


def test_shared_goal_isolated_from_other_household(world: World) -> None:
    goal = _create(world.owner).json()
    url = f"{GOALS}/{goal['id']}"
    assert world.stranger.get(GOALS).json() == []
    assert world.stranger.get(url).status_code == 404
    assert world.stranger.patch(url, json={"name": "x"}).status_code == 404
    assert world.stranger.delete(url).status_code == 404
    assert world.owner.get(url).status_code == 200


def test_goal_on_account_hidden_from_member_is_hidden(world: World, db: Session) -> None:
    account = make_account(db, world.owner_user, "Sparen")
    goal = _create(world.owner, account_id=str(account.id)).json()
    account.visibility = AccountVisibility.PRIVATE
    db.commit()
    assert world.member.get(f"{GOALS}/{goal['id']}").status_code == 404
    assert world.member.get(GOALS).json() == []
