"""Download visible transactions as CSV or XLSX."""

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from app.deps import CurrentMember, DbDep, SettingsDep
from app.finance.access import get_visible_account
from app.finance.contracts import today_berlin
from app.finance.export import (
    CSV_MEDIA_TYPE,
    XLSX_MEDIA_TYPE,
    TooManyRowsError,
    build_rows,
    render_csv,
    render_xlsx,
)
from app.sessions import audit

router = APIRouter(prefix="/export", tags=["export"])


@router.get("/transactions", response_class=Response)
def export_transactions(
    request: Request,
    member: CurrentMember,
    db: DbDep,
    settings: SettingsDep,
    export_format: Annotated[Literal["csv", "xlsx"], Query(alias="format")] = "csv",
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    account_id: uuid.UUID | None = None,
) -> Response:
    """Visible transactions ordered by booking date; split transactions give one row per split."""
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "'from' must not be after 'to'")
    if account_id is not None:
        get_visible_account(db, member, account_id)
    try:
        rows = build_rows(db, member, date_from, date_to, account_id)
    except TooManyRowsError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Too many transactions to export ({exc.count}); narrow the date range or pick an account",
        ) from exc
    audit(
        db,
        request,
        settings,
        "export_transactions",
        member.user,
        format=export_format,
        rows=str(len(rows)),
    )
    if export_format == "csv":
        content, media_type = render_csv(rows), CSV_MEDIA_TYPE
    else:
        content, media_type = render_xlsx(rows), XLSX_MEDIA_TYPE
    filename = f"buchungen-{today_berlin().isoformat()}.{export_format}"
    return Response(
        content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
