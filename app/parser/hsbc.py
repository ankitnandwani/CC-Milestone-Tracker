import re
from datetime import datetime, timedelta
from decimal import Decimal

from app.parser.models import ParsedTransaction
from app.parser.utils import html_to_text

LEGACY_TRANSACTION_PATTERN = re.compile(
    r"ending with\s+(?P<last4>\d{4}).*?"
    r"used for\s+(?P<currency>[A-Z]{3})\s*"
    r"(?P<amount>[\d,]+\.\d{2}).*?"
    r"payment to\s+(?P<merchant>.*?)\s+"
    r"on\s+(?P<date>\d{1,2}\s+\w+\s+\d{4})\s+"
    r"at\s+(?P<time>\d{2}:\d{2})",
    re.IGNORECASE | re.DOTALL,
)

DATE_ONLY_TRANSACTION_PATTERN = re.compile(
    r"HSBC\s+Credit\s+Card\s+xx(?P<last4>\d{4})\s+"
    r"was\s+used\s+for\s+a\s+transaction\s+of\s+"
    r"(?P<currency>[A-Z]{3})\s+(?P<amount>\d[\d,]*\.\d{2})\s+"
    r"at\s+(?P<merchant>.+?)\s+"
    r"on\s+(?P<date>\d{1,2}/\d{1,2}/(?:\d{4}|\d{2}))(?!\d)",
    re.IGNORECASE | re.DOTALL,
)


def parse_transaction(graph_message_id: str, html: str) -> ParsedTransaction:
    text = html_to_text(html)

    if match := DATE_ONLY_TRANSACTION_PATTERN.search(text):
        date_format = "%d/%m/%Y" if len(match["date"].rsplit("/", 1)[1]) == 4 else "%d/%m/%y"
        # The alert gives the transaction date without a time.
        transaction_time = datetime.strptime(match["date"], date_format)
    elif match := LEGACY_TRANSACTION_PATTERN.search(text):
        date_str = match["date"]
        time_str = match["time"]
        if time_str.startswith("24"):
            transaction_time = datetime.strptime(
                f"{date_str} 00{time_str[2:]}", "%d %b %Y %H:%M"
            ) + timedelta(days=1)
        else:
            transaction_time = datetime.strptime(f"{date_str} {time_str}", "%d %b %Y %H:%M")
    else:
        raise ValueError("Could not parse HSBC transaction email.")

    return ParsedTransaction(
        graph_message_id=graph_message_id,
        amount=Decimal(match["amount"].replace(",", "")),
        currency=match["currency"].upper(),
        merchant=match["merchant"].strip(),
        transaction_at=transaction_time,
        card_last4=match["last4"],
    )
