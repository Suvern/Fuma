from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime
from sqlalchemy import func, select

from app.api.contracts import AuditEvent, AuditPage
from app.api.dependencies import DB, require_admin
from app.domains.audit.models import AuditRecord

router = APIRouter(tags=["audit-events"], dependencies=[Depends(require_admin)])


@router.get("/audit-events", response_model=AuditPage, operation_id="list_audit_events")
def list_audit_events(
    db: DB,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: str | None = Query(None, max_length=200),
    action: str | None = None,
    since: Annotated[AwareDatetime | None, Query()] = None,
    until: Annotated[AwareDatetime | None, Query()] = None,
):
    stmt = select(AuditRecord)
    if q:
        stmt = stmt.where(AuditRecord.summary.icontains(q, autoescape=True))
    if action:
        stmt = stmt.where(AuditRecord.action == action)
    if since:
        stmt = stmt.where(AuditRecord.occurred_at >= since)
    if until:
        stmt = stmt.where(AuditRecord.occurred_at <= until)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(
        stmt.order_by(AuditRecord.occurred_at.desc(), AuditRecord.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return AuditPage(
        items=[AuditEvent.model_validate(row, from_attributes=True) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
    )
