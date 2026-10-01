from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.domains.audit.models import AuditRecord


def record_audit(
    db: Session,
    *,
    action: str,
    resource_type: str,
    request_id: str,
    actor_kind: str = "admin",
    actor_id: str | None = None,
    resource_id: str | None = None,
    outcome: str = "success",
    summary: str = "",
) -> None:
    """Only caller-authored summaries; never pass request bodies or provider errors."""
    db.add(
        AuditRecord(
            actor_kind=actor_kind,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            request_id=request_id,
            occurred_at=datetime.now(UTC),
            summary=summary[:500],
        )
    )
