from datetime import date, datetime, timedelta
from decimal import Decimal


def card_milestones(
    bank: str, last4: str, today: date
) -> list[tuple[str, Decimal, datetime, datetime]]:
    """Return milestone targets and half-open transaction windows."""
    if (bank, last4) == ("HSBC", "2677"):
        return [
            ("Spending milestone", Decimal("1200000"), datetime(2026, 6, 13), datetime(2027, 6, 13))
        ]
    if (bank, last4) != ("AU", "3052"):
        return []

    annual_start = datetime(today.year, 11, 12)
    if today < annual_start.date():
        annual_start = annual_start.replace(year=today.year - 1)
    annual_end = annual_start.replace(year=annual_start.year + 1)

    # The 23rd belongs to the closing cycle. The next cycle opens on the 24th.
    cycle_boundary = datetime(today.year, today.month, 24)
    if today < cycle_boundary.date():
        monthly_end = cycle_boundary
        monthly_start = (monthly_end.replace(day=1) - timedelta(days=1)).replace(day=24)
    else:
        monthly_start = cycle_boundary
        monthly_end = (monthly_start + timedelta(days=20)).replace(day=24)

    return [
        ("Annual fee waiver (₹5,000)", Decimal("800000"), annual_start, annual_end),
        ("Taj Epicure", Decimal("1200000"), annual_start, annual_end),
        ("Monthly bonus (1,000 reward points)", Decimal("75000"), monthly_start, monthly_end),
    ]
