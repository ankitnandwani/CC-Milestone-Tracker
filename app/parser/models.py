from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(slots=True)
class ParsedTransaction:
    graph_message_id: str
    card_last4: str
    merchant: str
    amount: Decimal
    currency: str
    transaction_at: datetime
