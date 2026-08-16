import re
from datetime import datetime, timedelta
from decimal import Decimal

from app.parser.models import ParsedTransaction
from app.parser.utils import html_to_text

TRANSACTION_PATTERN = re.compile(
    r"ending with\s+(?P<last4>\d{4}).*?"
    r"used for\s+(?P<currency>[A-Z]{3})\s*"
    r"(?P<amount>[\d,]+\.\d{2}).*?"
    r"payment to\s+(?P<merchant>.*?)\s+"
    r"on\s+(?P<date>\d{1,2}\s+\w+\s+\d{4})\s+"
    r"at\s+(?P<time>\d{2}:\d{2})",
    re.IGNORECASE | re.DOTALL,
)


def parse_transaction(graph_message_id: str, html: str) -> ParsedTransaction:
    text = html_to_text(html)

    match = TRANSACTION_PATTERN.search(text)

    if not match:
        raise ValueError("Could not parse HSBC transaction email.")

    amount = Decimal(match["amount"].replace(",", ""))

    # Build datetime, treating '24' hour as midnight of next day
    date_str = match["date"]
    time_str = match["time"]
    if time_str.startswith("24"):
        # Replace the hour '24' with '00' and add a day to the date
        time_str = time_str.replace("24", "00", 1)
        transaction_time = datetime.strptime(
            f"{date_str} {time_str}", "%d %b %Y %H:%M"
        ) + timedelta(days=1)
    else:
        transaction_time = datetime.strptime(f"{date_str} {time_str}", "%d %b %Y %H:%M")

    return ParsedTransaction(
        graph_message_id=graph_message_id,
        amount=amount,
        currency=match["currency"],
        merchant=match["merchant"].strip(),
        transaction_at=transaction_time,
        card_last4=match["last4"],
    )
