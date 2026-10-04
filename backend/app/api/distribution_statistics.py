from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from fastapi import APIRouter
from sqlalchemy import Date, cast, func, select

from app.api.applications import get_app
from app.api.contracts import DistributionStatistics
from app.api.dependencies import DB, Admin
from app.core.errors import AppError
from app.domains.distribution.statistics import COUNTERS, DistributionObservation
from app.domains.library.models import LibraryGrant, PublicationRecord

router = APIRouter(tags=["apps"])


@router.get(
    "/apps/{id}/distribution-statistics",
    response_model=DistributionStatistics,
    operation_id="get_app_distribution_statistics",
)
def distribution_statistics(
    id: UUID, db: DB, admin: Admin, start_date: date | None = None, end_date: date | None = None
):
    get_app(db, id)
    today = datetime.now(UTC).date()
    end_date = end_date or today
    start_date = start_date or date.fromordinal(max(1, end_date.toordinal() - 29))
    if start_date > end_date or (end_date - start_date).days >= 90 or end_date > today:
        raise AppError(422, "INVALID_STATISTICS_RANGE", "请选择不超过 90 天且不晚于今天的日期范围")
    rows = {
        row.date: row
        for row in db.scalars(
            select(DistributionObservation).where(
                DistributionObservation.app_id == id,
                DistributionObservation.date >= start_date,
                DistributionObservation.date <= end_date,
            )
        )
    }
    grant_day = cast(func.timezone("UTC", LibraryGrant.created_at), Date)
    grant_counts = dict(
        db.execute(
            select(grant_day, func.count())
            .join(PublicationRecord, LibraryGrant.publication_id == PublicationRecord.id)
            .where(
                PublicationRecord.app_id == id,
                LibraryGrant.created_at.is_not(None),
                LibraryGrant.created_at >= datetime.combine(start_date, time.min, tzinfo=UTC),
                LibraryGrant.created_at
                < datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=UTC),
            )
            .group_by(grant_day)
        ).all()
    )
    days = []
    for delta in range((end_date - start_date).days + 1):
        day = start_date + timedelta(days=delta)
        row = rows.get(day)
        days.append(
            {
                "date": day,
                "grant_count": grant_counts.get(day, 0),
                **{name: getattr(row, name) if row else 0 for name in COUNTERS},
            }
        )
    return {
        "app_id": id,
        "start_date": start_date,
        "end_date": end_date,
        "days": days,
        "totals": {name: sum(day[name] for day in days) for name in ("grant_count", *COUNTERS)},
    }
