"""Basic Streamlit UI for CCGeek.

This UI provides:
* A button to trigger the same sync logic used by the CLI (`graph sync`).
* A table of the most recent transactions (default 20 rows).

It purposefully stays minimal – no extra styling, no pagination, no charts.
You can run it with:
    uv run streamlit run app/ui/streamlit_app.py
"""

import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import asyncio
from datetime import datetime
from decimal import Decimal

import streamlit as st
from sqlalchemy import desc, func, select

from app.db import SessionLocal
from app.db.models.card import Card
from app.db.models.transaction import Transaction
from app.graph.auth import authenticate
from app.graph.client import GraphClient
from app.parser.hsbc import parse_transaction

# ------------------------------------------------------------
# Spending target configuration
# ------------------------------------------------------------
TARGET_START = datetime(2026, 6, 13)
TARGET_END = datetime(2027, 6, 12, 23, 59, 59)
TARGET_AMOUNT = Decimal("1200000")  # Rs 12 Lakhs


# ------------------------------------------------------------
# Sync logic – identical to the CLI implementation, but kept
# local to avoid importing the CLI (which pulls in Typer).
# ------------------------------------------------------------
async def _run_sync(client: GraphClient) -> dict[str, int]:
    fetched = 0
    parsed = 0
    imported = 0
    skipped = 0

    # Retrieve HSBC transaction messages (increase top to fetch more)
    messages = client.list_hsbc_transaction_messages(top=100)
    fetched = len(messages)

    failed = []  # keep track of messages that could not be parsed
    async with SessionLocal() as session:
        for msg in messages:
            html = client.message_body(msg["id"])  # retrieve full body
            try:
                tx = parse_transaction(graph_message_id=msg["id"], html=html)
            except Exception as e:
                # parsing failed – skip this email, record the failure
                failed.append({"id": msg["id"], "subject": msg.get("subject", ""), "error": str(e)})
                continue
            parsed += 1

            # Find the Card by last4
            card_res = await session.execute(select(Card).where(Card.last4 == tx.card_last4))
            card = card_res.scalar_one_or_none()
            if not card:
                # No matching card – skip
                skipped += 1
                continue

            # Duplicate detection
            dup_res = await session.execute(
                select(Transaction).where(Transaction.graph_message_id == tx.graph_message_id)
            )
            if dup_res.scalar_one_or_none():
                skipped += 1
                continue

            # Persist transaction
            transaction = Transaction(
                card_id=card.id,
                graph_message_id=tx.graph_message_id,
                merchant=tx.merchant,
                amount=tx.amount,
                currency=tx.currency,
                transaction_at=tx.transaction_at,
                pending=False,
            )
            session.add(transaction)
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                skipped += 1
            else:
                imported += 1

    return {
        "fetched": fetched,
        "parsed": parsed,
        "imported": imported,
        "skipped": skipped,
        "failed": failed,
    }


# ------------------------------------------------------------
# Helper to fetch recent transactions for display.
# ------------------------------------------------------------
async def _fetch_recent(limit: int = 20) -> list[dict]:
    async with SessionLocal() as session:
        result = await session.execute(
            select(
                Transaction.graph_message_id,
                Transaction.transaction_at,
                Transaction.merchant,
                Transaction.amount,
                Transaction.currency,
                Card.last4,
            )
            .join(Card, Transaction.card_id == Card.id)
            .order_by(desc(Transaction.transaction_at))
            .limit(limit)
        )
        rows = result.all()
    # Convert to list of dicts suitable for st.table
    records = []
    for (
        graph_message_id,
        transaction_at,
        merchant,
        amount,
        currency,
        last4,
    ) in rows:
        records.append(
            {
                "Date": transaction_at.strftime("%Y-%m-%d %H:%M"),
                "Card last4": last4,
                "Merchant": merchant,
                "Amount": f"{amount} {currency}",
                "Message ID": graph_message_id,
            }
        )
    return records


# ------------------------------------------------------------
# Helper to fetch total spent for target period
# ------------------------------------------------------------
async def _fetch_total_spent() -> Decimal:
    async with SessionLocal() as session:
        result = await session.execute(
            select(func.sum(Transaction.amount)).where(
                Transaction.transaction_at >= TARGET_START,
                Transaction.transaction_at <= TARGET_END,
            )
        )
        total = result.scalar()
    return total or Decimal("0")


# ------------------------------------------------------------
# Streamlit UI layout
# ------------------------------------------------------------
st.title("CCGeek – Credit Card Spend Tracker")
st.caption("Simple UI built with Streamlit – syncs your HSBC transaction emails into PostgreSQL.")

# Progress towards spending target
st.subheader("Spending Target – ₹12 Lakhs (June 13 2026 – June 12 2027)")
# Fetch total spent for the target period
total_spent = asyncio.run(_fetch_total_spent())
progress_fraction = (
    min(float(total_spent) / float(TARGET_AMOUNT), 1.0) if TARGET_AMOUNT != 0 else 0.0
)
st.progress(progress_fraction)
st.metric(
    label="Spent",
    value=f"₹{total_spent:,.2f}",
    delta=f"₹{(TARGET_AMOUNT - total_spent):,.2f} remaining",
)

if st.button("Sync now"):
    with st.spinner("Synchronizing…"):
        token = authenticate()
        with GraphClient(token) as client:
            stats = asyncio.run(_run_sync(client))
    st.success("Sync complete!")
    st.json(stats)
    # Show any parsing failures, if present
    if stats.get("failed"):
        st.warning("Some emails could not be parsed:")
        for f in stats["failed"]:
            st.write(f"ID: {f['id']} – Subject: {f['subject']} – Error: {f['error']}")

st.subheader("Recent Transactions (latest 20)")
with st.spinner("Loading transactions…"):
    recent = asyncio.run(_fetch_recent(20))
if recent:
    st.table(recent)
else:
    st.info("No transactions found. Run the sync first.")

# End of file
