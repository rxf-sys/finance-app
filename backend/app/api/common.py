"""Small helpers shared by routers."""

from collections.abc import Iterable, Iterator
from contextlib import contextmanager

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


@contextmanager
def conflict_on_duplicate(db: Session, detail: str) -> Iterator[None]:
    """Flush inside a savepoint and turn a unique violation into 409, leaving the session usable."""
    try:
        with db.begin_nested():
            yield
            db.flush()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail) from exc


def ensure_name_free(existing: Iterable[str], name: str, detail: str) -> None:
    """409 when `name` equals one of `existing` ignoring case (the DB constraint is case-sensitive)."""
    folded = name.casefold()
    if any(other.casefold() == folded for other in existing):
        raise HTTPException(status.HTTP_409_CONFLICT, detail)
