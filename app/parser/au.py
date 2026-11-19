import re
from datetime import datetime
from decimal import Decimal

from app.parser.models import ParsedTransaction
from app.parser.utils import html_to_text

PURCHASE_PATTERN = re.compile(
    r"(?P<currency>[A-Z]{3})\s+(?P<amount>\d[\d,]*\.\d{2})\s+"
    r"were\s+spent\s+on\s+your\s+AU\s+Credit\s+Card\s+xx(?P<last4>\d{4})\s+"
    r"at\s+(?P<merchant>.+?)\s+on\s+(?P<date>\d{2}-\d{2}-\d{4})\s+"
    r"at\s+(?P<time>\d{1,2}:\d{2}:\d{2}\s+[AP]M)\b",
    re.IGNORECASE | re.DOTALL,
)


def parse_transaction(graph_message_id: str, html: str) -> ParsedTransaction:
    match = PURCHASE_PATTERN.search(html_to_text(html))
    if not match:
        raise ValueError("Could not parse AU transaction email.")

    time = " ".join(match["time"].split())
    return ParsedTransaction(
        graph_message_id=graph_message_id,
        card_last4=match["last4"],
        merchant=match["merchant"].strip(),
        amount=Decimal(match["amount"].replace(",", "")),
        currency=match["currency"].upper(),
        transaction_at=datetime.strptime(f"{match['date']} {time}", "%d-%m-%Y %I:%M:%S %p"),
    )
