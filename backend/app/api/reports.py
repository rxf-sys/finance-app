"""Year reports for the report pages."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.deps import CurrentMember, DbDep
from app.finance import reports
from app.finance.reports import CategoryLine, ReportKind

router = APIRouter(prefix="/reports", tags=["reports"])

Year = Annotated[int, Query(ge=2000, le=2100)]


class MonthOut(BaseModel):
    month: str
    income_cents: int
    expense_cents: int = Field(description="Negative")
    saldo_cents: int
    savings_rate_bp: int | None = Field(description="Saldo / income in basis points; null without income")


class YearReportOut(BaseModel):
    year: int
    months: list[MonthOut]
    income_cents: int
    expense_cents: int = Field(description="Negative")
    saldo_cents: int
    savings_rate_bp: int | None


class CategoryRowOut(BaseModel):
    category_id: uuid.UUID | None
    name: str | None
    icon: str | None
    color: str | None
    months_cents: list[int] = Field(description="Twelve signed values, January first")
    total_cents: int
    children: list["CategoryRowOut"]


class CategoryReportOut(BaseModel):
    """Per top-level category with its children; `uncategorized` has a null id and name."""

    year: int
    kind: ReportKind
    rows: list[CategoryRowOut]
    uncategorized: CategoryRowOut
    totals_cents: list[int] = Field(description="Twelve column totals including uncategorized")
    total_cents: int


@router.get("/year")
def year_report(member: CurrentMember, db: DbDep, year: Year) -> YearReportOut:
    months = [MonthOut.model_validate(m, from_attributes=True) for m in reports.year_flows(db, member, year)]
    income = sum(m.income_cents for m in months)
    expense = sum(m.expense_cents for m in months)
    return YearReportOut(
        year=year,
        months=months,
        income_cents=income,
        expense_cents=expense,
        saldo_cents=income + expense,
        savings_rate_bp=reports.savings_rate_bp(income, income + expense),
    )


def _row(line: CategoryLine) -> CategoryRowOut:
    return CategoryRowOut(
        category_id=line.category_id,
        name=line.name,
        icon=line.icon,
        color=line.color,
        months_cents=line.months,
        total_cents=line.total_cents,
        children=[_row(c) for c in line.children],
    )


@router.get("/categories")
def category_report(
    member: CurrentMember, db: DbDep, year: Year, kind: ReportKind = "expense"
) -> CategoryReportOut:
    report = reports.category_report(db, member, year, kind)
    return CategoryReportOut(
        year=year,
        kind=kind,
        rows=[_row(r) for r in report.rows],
        uncategorized=_row(report.uncategorized),
        totals_cents=report.totals,
        total_cents=sum(report.totals),
    )
