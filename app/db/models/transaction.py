from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import BaseModel


class Transaction(BaseModel):
    __tablename__ = "transactions"

    card_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("cards.id"),
        nullable=False,
    )

    graph_message_id: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
    )

    merchant: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
    )

    transaction_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
    )

    pending: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
    )
