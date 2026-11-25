"""'Frei verfügbar': what is left to spend this month."""

from fastapi import APIRouter

from app.api import planning_schemas as schemas
from app.deps import CurrentMember, DbDep
from app.finance.available import available_to_spend
from app.finance.contracts import today_berlin

router = APIRouter(prefix="/available", tags=["available"])


@router.get("")
def get_available(member: CurrentMember, db: DbDep) -> schemas.AvailableOut:
    result = available_to_spend(db, member, today_berlin())
    return schemas.AvailableOut(
        balance_cents=result.balance_cents,
        upcoming_out_cents=result.upcoming_out_cents,
        upcoming_in_cents=result.upcoming_in_cents,
        available_cents=result.available_cents,
        items=[
            schemas.AvailableItem(
                contract_id=i.contract_id, name=i.name, due_date=i.due_date, amount_cents=i.amount_cents
            )
            for i in result.items
        ],
    )
