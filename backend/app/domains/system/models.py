from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


class SystemState(Base):
    __tablename__ = "system_state"
    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    initialized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    encryption_key_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
