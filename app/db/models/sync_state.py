from datetime import datetime

from sqlalchemy import DateTime, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SyncState(Base):
    __tablename__ = "sync_state"

    id = mapped_column(
        Integer,
        primary_key=True,
        default=1,
    )

    token_cache: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
