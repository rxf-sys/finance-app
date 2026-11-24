import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuthChallenge, ChallengePurpose, UserSession
from app.models.base import utcnow
from app.worker import cleanup_expired
from tests.conftest import UserFactory


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
