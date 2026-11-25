"""CSV import: format analysis, preview, commit, run history and saved formats.

The upload travels as JSON (base64) because multipart parsing would need an extra dependency.
"""

import base64
import binascii
import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import import_schemas as schemas
from app.api.common import conflict_on_duplicate
from app.deps import CurrentMember, DbDep, MemberContext, SettingsDep
from app.finance.access import get_visible_account, visible_account_clause
from app.finance.importer import preview_import, run_import, sample_rows
from app.importing import PRESETS, CsvFormat, suggest_format
from app.models import Account, ImportProfile, ImportRun
from app.sessions import audit

router = APIRouter(prefix="/imports", tags=["imports"])

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_RUNS = 50
DEFAULT_PROFILE_NAME = "custom"
_MAX_BASE64_CHARS = (MAX_UPLOAD_BYTES + 2) // 3 * 4


def decode_upload(content_base64: str) -> bytes:
    if len(content_base64) > _MAX_BASE64_CHARS + 2:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "File too large")
    try:
        data = base64.b64decode(content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid base64 content") from exc
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "File too large")
    return data


def _profile_out(profile: ImportProfile) -> schemas.ProfileOut:
    return schemas.ProfileOut(
        id=profile.id,
        name=profile.name,
        format=CsvFormat.model_validate(profile.config),
        created_at=profile.created_at,
    )


def _get_profile(db: Session, member: MemberContext, profile_id: uuid.UUID) -> ImportProfile:
    profile = db.scalar(
        select(ImportProfile).where(
            ImportProfile.id == profile_id, ImportProfile.household_id == member.household.id
        )
    )
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Import profile not found")
    return profile


@router.get("/presets")
def list_presets(member: CurrentMember) -> list[schemas.PresetOut]:
    return [schemas.PresetOut(key=p.key, label=p.label, format=p.format) for p in PRESETS]


@router.post("/analyze")
def analyze(body: schemas.AnalyzeRequest, member: CurrentMember) -> schemas.AnalyzeOut:
    data = decode_upload(body.content_base64)
    suggestion = suggest_format(data)
    rows: list[list[str]] = []
    if suggestion.format is not None and suggestion.header_row is not None:
        rows = sample_rows(data, suggestion.header_row, suggestion.format.delimiter)
    return schemas.AnalyzeOut(
        format=suggestion.format,
        preset_key=suggestion.preset_key,
        headers=suggestion.headers,
        header_row=suggestion.header_row,
        confidence=suggestion.confidence,
        unmapped_required=suggestion.unmapped_required,
        unmapped_headers=suggestion.unmapped_headers,
        sample_rows=rows,
    )


@router.post("/preview")
def preview(body: schemas.PreviewRequest, member: CurrentMember, db: DbDep) -> schemas.PreviewOut:
    account = get_visible_account(db, member, body.account_id)
    data = decode_upload(body.content_base64)
    result = preview_import(db, member, account, data, body.format)
    return schemas.PreviewOut(
        rows_total=result.rows_total,
        rows_new=result.rows_new,
        rows_duplicate=result.rows_duplicate,
        rows_skipped=result.rows_skipped,
        errors_total=result.errors_total,
        rows=[schemas.PreviewRowOut(**row.__dict__) for row in result.rows],
        errors=[schemas.RowErrorOut(line_no=e.line_no, message=e.message) for e in result.errors],
    )


@router.post("", status_code=status.HTTP_201_CREATED)
def commit_import(
    body: schemas.ImportRequest,
    request: Request,
    member: CurrentMember,
    db: DbDep,
    settings: SettingsDep,
) -> schemas.ImportRunOut:
    account = get_visible_account(db, member, body.account_id)
    data = decode_upload(body.content_base64)
    run = run_import(
        db, member, account, data, body.format, body.profile_name or DEFAULT_PROFILE_NAME, body.filename
    )
    # Counts and ids only; never transaction contents.
    audit(
        db,
        request,
        settings,
        "import_completed",
        member.user,
        account_id=str(account.id),
        import_run_id=str(run.id),
        rows_total=str(run.rows_total),
        rows_new=str(run.rows_new),
        rows_duplicate=str(run.rows_duplicate),
        rows_skipped=str(run.rows_skipped),
    )
    return schemas.ImportRunOut.model_validate(run, from_attributes=True)


@router.get("")
def list_runs(
    member: CurrentMember, db: DbDep, account_id: Annotated[uuid.UUID | None, Query()] = None
) -> list[schemas.ImportRunOut]:
    query = select(ImportRun).where(
        ImportRun.household_id == member.household.id,
        ImportRun.account_id.in_(select(Account.id).where(visible_account_clause(member))),
    )
    if account_id is not None:
        get_visible_account(db, member, account_id)
        query = query.where(ImportRun.account_id == account_id)
    runs = db.scalars(query.order_by(ImportRun.started_at.desc(), ImportRun.id).limit(MAX_RUNS))
    return [schemas.ImportRunOut.model_validate(run, from_attributes=True) for run in runs]


# ---------------------------------------------------------------- saved formats


@router.get("/profiles")
def list_profiles(member: CurrentMember, db: DbDep) -> list[schemas.ProfileOut]:
    profiles = db.scalars(
        select(ImportProfile)
        .where(ImportProfile.household_id == member.household.id)
        .order_by(ImportProfile.name, ImportProfile.id)
    )
    return [_profile_out(p) for p in profiles]


@router.post("/profiles", status_code=status.HTTP_201_CREATED)
def create_profile(body: schemas.ProfileCreate, member: CurrentMember, db: DbDep) -> schemas.ProfileOut:
    profile = ImportProfile(
        id=uuid.uuid4(),
        household_id=member.household.id,
        name=body.name,
        config=body.format.model_dump(mode="json"),
    )
    with conflict_on_duplicate(db, "An import profile with this name already exists"):
        db.add(profile)
    db.refresh(profile)  # load the server-side created_at
    return _profile_out(profile)


@router.patch("/profiles/{profile_id}")
def update_profile(
    profile_id: uuid.UUID, body: schemas.ProfileUpdate, member: CurrentMember, db: DbDep
) -> schemas.ProfileOut:
    profile = _get_profile(db, member, profile_id)
    with conflict_on_duplicate(db, "An import profile with this name already exists"):
        if body.name is not None:
            profile.name = body.name
        if body.format is not None:
            profile.config = body.format.model_dump(mode="json")
    return _profile_out(profile)


@router.delete("/profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_profile(profile_id: uuid.UUID, member: CurrentMember, db: DbDep) -> Response:
    db.delete(_get_profile(db, member, profile_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
