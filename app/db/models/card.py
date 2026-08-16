from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import BaseModel
from app.db.enums import Bank, CardNetwork


class Card(BaseModel):
    __tablename__ = "cards"

    bank_name: Mapped[Bank] = mapped_column(
        String(20),
        nullable=False,
    )

    card_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    card_network: Mapped[CardNetwork] = mapped_column(
        String(20),
        nullable=False,
    )

    last4: Mapped[str] = mapped_column(
        String(4),
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="INR",
    )

    active: Mapped[bool] = mapped_column(
        default=True,
        nullable=False,
    )
