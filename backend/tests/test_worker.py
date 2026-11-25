import uuid
from datetime import date, timedelta

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import push, worker
from app.config import Settings, get_settings
from app.db import get_sessionmaker
from app.models import (
    AuthChallenge,
    ChallengePurpose,
    Notification,
    NotificationKind,
    PushSubscription,
    User,
    UserSession,
)
from app.models.base import utcnow
from app.security.webpush import VapidKey
from app.worker import app, cleanup_expired, dispatch_push, generate_notifications_daily
from tests.conftest import UserFactory
from tests.test_push import FakePushService, Receiver


def test_cleanup_removes_only_expired_rows(db: Session, make_user: UserFactory) -> None:
    user = make_user()
    now = utcnow()
    db.add_all(
        [
            UserSession(
                user_id=user.id, token_hash="a" * 64, last_seen_at=now, expires_at=now + timedelta(days=1)
            ),
            UserSession(
                user_id=user.id, token_hash="b" * 64, last_seen_at=now, expires_at=now - timedelta(seconds=1)
            ),
            UserSession(
                user_id=user.id,
                token_hash="c" * 64,
                last_seen_at=now - timedelta(days=2),
                expires_at=now + timedelta(days=1),
            ),
            AuthChallenge(
                id=uuid.uuid4(),
                purpose=ChallengePurpose.MFA_LOGIN,
                user_id=user.id,
                expires_at=now - timedelta(minutes=1),
            ),
        ]
    )
    db.commit()

    cleanup_expired(timestamp=int(now.timestamp()))

    db.expire_all()
    assert db.scalars(select(UserSession.token_hash)).all() == ["a" * 64]
    assert db.scalar(select(func.count()).select_from(AuthChallenge)) == 0


def _push_settings() -> Settings:
    return get_settings().model_copy(
        update={
            "vapid_private_key": SecretStr(VapidKey.generate_pem()),
            "vapid_subject": "mailto:admin@example.com",
        }
    )


def _notice(db: Session, user: User) -> Notification:
    assert user.membership is not None
    notice = Notification(
        household_id=user.membership.household_id,
        user_id=user.id,
        kind=NotificationKind.BUDGET_WARNING,
        title="Budget",
        dedupe_key="worker-test",
    )
    db.add(notice)
    db.commit()
    return notice


def test_dispatch_push_task_sends_and_marks_handled(
    db: Session, make_user: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = make_user()
    assert user.membership is not None
    receiver = Receiver()
    db.add(
        PushSubscription(
            household_id=user.membership.household_id,
            user_id=user.id,
            endpoint=receiver.endpoint,
            **receiver.keys(),
        )
    )
    notice = _notice(db, user)
    service = FakePushService()
    monkeypatch.setattr(push, "build_client", lambda transport=None: service.client())
    monkeypatch.setattr(push, "get_settings", _push_settings)

    dispatch_push(timestamp=0)
    dispatch_push(timestamp=0)

    db.refresh(notice)
    assert notice.push_handled_at is not None
    assert [receiver.decrypt(r)["title"] for r in service.requests] == ["Budget"]


def test_generate_notifications_daily_dispatches_after_commit(
    db: Session, make_user: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = make_user()
    seen: list[int] = []

    def fake_generate(session: Session, today: date) -> None:
        _notice(db, user)

    def fake_dispatch() -> None:
        with get_sessionmaker()() as other:
            seen.append(len(other.scalars(select(Notification)).all()))

    monkeypatch.setattr(worker, "generate_notifications", fake_generate)
    monkeypatch.setattr(worker, "dispatch_pending", fake_dispatch)

    generate_notifications_daily(timestamp=0)

    assert seen == [1]  # the new notice was already visible to a separate session


def test_push_task_is_periodic_every_two_minutes() -> None:
    crons = [
        p.cron for p in app.periodic_registry.periodic_tasks.values() if p.task.name.endswith("dispatch_push")
    ]
    assert crons == ["*/2 * * * *"]
    assert dispatch_push.queueing_lock == "dispatch_push"
