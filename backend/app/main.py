"""FastAPI application factory."""

from fastapi import APIRouter, Depends, FastAPI

from app.api import (
    accounts,
    auth,
    available,
    banking,
    budgets,
    categories,
    contracts,
    dashboard,
    export,
    forecast,
    health,
    household,
    imports,
    notifications,
    push,
    reports,
    rules,
    savings_goals,
    tags,
    transactions,
)
from app.config import get_settings
from app.deps import require_cloudflare_access


def create_app() -> FastAPI:
    settings = get_settings()
    docs_enabled = settings.env != "production"
    app = FastAPI(
        title=settings.app_name,
        docs_url="/api/docs" if docs_enabled else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if docs_enabled else None,
    )

    api = APIRouter(prefix="/api")
    api.include_router(health.router)

    protected = APIRouter(dependencies=[Depends(require_cloudflare_access)])
    protected.include_router(auth.router)
    protected.include_router(household.router)
    for router in (
        accounts.router,
        categories.router,
        rules.router,
        tags.router,
        transactions.router,
        imports.router,
        dashboard.router,
        contracts.router,
        budgets.router,
        available.router,
        forecast.router,
        export.router,
        reports.router,
        savings_goals.router,
        notifications.router,
        push.router,
        banking.router,
    ):
        protected.include_router(router)
    api.include_router(protected)

    app.include_router(api)
    return app


app = create_app()
