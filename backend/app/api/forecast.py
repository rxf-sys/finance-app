"""Balance forecast for the spendable accounts."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.api import planning_schemas as schemas
from app.deps import CurrentMember, DbDep
from app.finance.contracts import today_berlin
from app.finance.forecast import load_forecast

router = APIRouter(prefix="/forecast", tags=["forecast"])


@router.get("")
def get_forecast(
    member: CurrentMember, db: DbDep, months: Annotated[int, Query(ge=1, le=3)] = 3
) -> schemas.ForecastOut:
    result = load_forecast(db, member, today_berlin(), months)
    return schemas.ForecastOut.model_validate(result, from_attributes=True)
