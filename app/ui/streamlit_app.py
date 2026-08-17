"""Streamlit UI for CCGeek.

Provides:
- Milestone spend tracking with target progress bar and pace calculation.
- KPI summary metrics (total spent, remaining balance, pace).
- Visual charts: monthly spend trends and top merchant breakdowns.
- Interactive searchable transactions table with custom column formatting.
- Microsoft Graph sync button with live status reporting and toast notifications.
- CSV export for transactions.

Run with:
    uv run streamlit run app/ui/streamlit_app.py
"""

import asyncio
import os
import sys
from datetime import UTC, datetime
from decimal import Decimal

import pandas as pd
import streamlit as st
from sqlalchemy import desc, func, select

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.db import SessionLocal  # noqa: E402
from app.db.models.card import Card  # noqa: E402
from app.db.models.transaction import Transaction  # noqa: E402
from app.graph.auth import authenticate  # noqa: E402
from app.graph.client import GraphClient  # noqa: E402
from app.parser.hsbc import parse_transaction  # noqa: E402

# ------------------------------------------------------------
# Spending target configuration
# ------------------------------------------------------------
TARGET_START = datetime(2026, 6, 13)
TARGET_END = datetime(2027, 6, 12, 23, 59, 59)
TARGET_AMOUNT = Decimal("1200000")  # Rs 12 Lakhs


# ------------------------------------------------------------
# Page configuration
# ------------------------------------------------------------
st.set_page_config(
    page_title="CCGeek — Spend Tracker",
    page_icon=":material/credit_card:",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ------------------------------------------------------------
# Sync logic
# ------------------------------------------------------------
async def _run_sync(client: GraphClient) -> dict:
    fetched = 0
    parsed = 0
    imported = 0
    skipped = 0
    failed = []
    unmatched_cards = []

    messages = client.list_hsbc_transaction_messages(top=100)
    fetched = len(messages)

    async with SessionLocal() as session:
        # Prefetch existing transaction IDs for instant duplicate checking
        existing_tx_res = await session.execute(select(Transaction.graph_message_id))
        existing_ids = set(existing_tx_res.scalars().all())

        # Prefetch active cards mapped by last4
        cards_res = await session.execute(select(Card).where(Card.active.is_(True)))
        cards_by_last4 = {c.last4: c for c in cards_res.scalars().all()}

        for msg in messages:
            msg_id = msg["id"]

            # Quick duplicate check: skip without downloading HTML body
            if msg_id in existing_ids:
                skipped += 1
                continue

            try:
                html = client.message_body(msg_id)
                tx = parse_transaction(graph_message_id=msg_id, html=html)
            except Exception as e:
                failed.append(
                    {
                        "id": msg_id,
                        "subject": msg.get("subject", ""),
                        "error": str(e),
                    }
                )
                continue
            parsed += 1

            # Match card
            card = cards_by_last4.get(tx.card_last4)
            if not card:
                unmatched_cards.append(
                    {
                        "id": msg_id,
                        "card_last4": tx.card_last4,
                        "merchant": tx.merchant,
                        "amount": float(tx.amount),
                        "subject": msg.get("subject", ""),
                    }
                )
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
                existing_ids.add(tx.graph_message_id)
                imported += 1
            except Exception:
                await session.rollback()
                skipped += 1

    return {
        "fetched": fetched,
        "parsed": parsed,
        "imported": imported,
        "skipped": skipped,
        "failed": failed,
        "unmatched_cards": unmatched_cards,
    }


# ------------------------------------------------------------
# Database queries
# ------------------------------------------------------------
async def _fetch_card_info() -> Card | None:
    async with SessionLocal() as session:
        res = await session.execute(select(Card).where(Card.active.is_(True)).limit(1))
        return res.scalar_one_or_none()


async def _fetch_total_milestone_spent() -> Decimal:
    async with SessionLocal() as session:
        result = await session.execute(
            select(func.sum(Transaction.amount)).where(
                Transaction.transaction_at >= TARGET_START,
                Transaction.transaction_at <= TARGET_END,
            )
        )
        total = result.scalar()
        return total or Decimal("0")


async def _fetch_all_transactions() -> list[dict]:
    async with SessionLocal() as session:
        result = await session.execute(
            select(
                Transaction.transaction_at,
                Transaction.merchant,
                Transaction.amount,
                Transaction.currency,
                Card.card_name,
                Card.last4,
                Transaction.graph_message_id,
            )
            .join(Card, Transaction.card_id == Card.id)
            .order_by(desc(Transaction.transaction_at))
        )
        rows = result.all()

    records = []
    for (
        transaction_at,
        merchant,
        amount,
        currency,
        card_name,
        last4,
        graph_message_id,
    ) in rows:
        records.append(
            {
                "Date & Time": transaction_at,
                "Merchant": merchant,
                "Amount": float(amount),
                "Currency": currency,
                "Card": f"{card_name} (••{last4})",
                "Message ID": graph_message_id,
            }
        )
    return records


async def _fetch_monthly_spend() -> pd.DataFrame:
    async with SessionLocal() as session:
        result = await session.execute(
            select(
                func.date_trunc("month", Transaction.transaction_at).label("month"),
                func.sum(Transaction.amount).label("total_spend"),
                func.count(Transaction.id).label("tx_count"),
            )
            .where(
                Transaction.transaction_at >= TARGET_START,
                Transaction.transaction_at <= TARGET_END,
            )
            .group_by("month")
            .order_by("month")
        )
        rows = result.all()

    if not rows:
        return pd.DataFrame(columns=["Month", "Spend (₹)", "Transactions"])

    data = [
        {
            "Month": r.month.strftime("%b %Y"),
            "Spend (₹)": float(r.total_spend),
            "Transactions": int(r.tx_count),
        }
        for r in rows
    ]
    return pd.DataFrame(data)


async def _fetch_top_merchants(limit: int = 7) -> pd.DataFrame:
    async with SessionLocal() as session:
        result = await session.execute(
            select(
                Transaction.merchant,
                func.sum(Transaction.amount).label("total_spend"),
                func.count(Transaction.id).label("tx_count"),
            )
            .group_by(Transaction.merchant)
            .order_by(desc("total_spend"))
            .limit(limit)
        )
        rows = result.all()

    if not rows:
        return pd.DataFrame(columns=["Merchant", "Total Spend (₹)", "Transactions"])

    data = [
        {
            "Merchant": r.merchant,
            "Total Spend (₹)": float(r.total_spend),
            "Transactions": int(r.tx_count),
        }
        for r in rows
    ]
    return pd.DataFrame(data)


async def _seed_default_card() -> None:
    from app.db.enums import Bank, CardNetwork

    async with SessionLocal() as session:
        res = await session.execute(select(Card).where(Card.last4 == "2677"))
        if not res.scalar_one_or_none():
            c = Card(
                bank_name=Bank.HSBC,
                card_name="TravelOne",
                card_network=CardNetwork.MASTERCARD,
                last4="2677",
                currency="INR",
                active=True,
            )
            session.add(c)
            await session.commit()


# ------------------------------------------------------------
# Fetch initial state
# ------------------------------------------------------------
card = asyncio.run(_fetch_card_info())
total_spent = asyncio.run(_fetch_total_milestone_spent())
transactions = asyncio.run(_fetch_all_transactions())
monthly_df = asyncio.run(_fetch_monthly_spend())
top_merchants_df = asyncio.run(_fetch_top_merchants(limit=7))

# ------------------------------------------------------------
# Header & Navigation
# ------------------------------------------------------------
header_col1, header_col2 = st.columns([3, 1], vertical_alignment="center")

with header_col1:
    st.title("CCGeek")
    if card:
        bank_name = card.bank_name.value if hasattr(card.bank_name, "value") else card.bank_name
        card_label = f"💳 {bank_name} {card.card_name} · •••• {card.last4}"
    else:
        card_label = "💳 Credit Card"
    st.markdown(
        f":blue-badge[{card_label}] :green-badge[● Connected] "
        ":violet-badge[🎯 ₹12L Milestone Tracker]"
    )

with header_col2:
    sync_clicked = st.button(
        "Sync emails",
        icon=":material/sync:",
        type="primary",
        help="Fetch latest transaction emails from Outlook via Microsoft Graph",
    )

if not card:
    with st.container(border=True):
        st.warning(
            "⚠️ No active credit cards found in the database. "
            "Please configure a card to import transactions."
        )
        if st.button("Configure default HSBC Card (••2677)", type="primary"):
            asyncio.run(_seed_default_card())
            st.rerun()

# ------------------------------------------------------------
# Sync Trigger Handling
# ------------------------------------------------------------
if sync_clicked:
    with st.status(
        "Connecting to Microsoft Graph and scanning HSBC emails...", expanded=True
    ) as status_box:
        try:
            token = authenticate()
            with GraphClient(token) as client:
                st.write("Fetching transaction messages...")
                stats = asyncio.run(_run_sync(client))

            status_box.update(
                label=f"Sync complete! Imported {stats['imported']} new transaction(s).",
                state="complete",
                expanded=False,
            )

            if stats["imported"] > 0:
                st.balloons()
                st.toast(
                    f"Successfully imported {stats['imported']} new transaction(s)!",
                    icon=":material/celebration:",
                )
            elif stats.get("unmatched_cards"):
                st.toast(
                    f"Found {len(stats['unmatched_cards'])} transaction(s) for unregistered cards.",
                    icon=":material/warning:",
                )
            else:
                st.toast(
                    f"Already up to date. {stats['skipped']} existing transaction(s) verified.",
                    icon=":material/check_circle:",
                )

            if stats.get("unmatched_cards"):
                with st.expander(
                    f"⚠️ Unmatched Card Diagnostics ({len(stats['unmatched_cards'])} skipped)",
                    expanded=True,
                    icon=":material/warning:",
                ):
                    st.write("Transactions were found for cards not configured in your database:")
                    for item in stats["unmatched_cards"]:
                        st.caption(
                            f"**Card Last 4**: `•••• {item['card_last4']}` "
                            f"| **Merchant**: {item['merchant']} "
                            f"| **Amount**: ₹{item['amount']:,.2f}"
                        )
                    st.info(
                        "Tip: Register cards via CLI with "
                        "`uv run python -m app.cli card add` or seed with "
                        "`uv run python -m app.cli db seed`."
                    )

            if stats.get("failed"):
                with st.expander(
                    f"Parsing diagnostics ({len(stats['failed'])} skipped)",
                    icon=":material/warning:",
                ):
                    for item in stats["failed"]:
                        st.caption(f"**ID**: `{item['id']}` — **Subject**: {item['subject']}")
                        st.code(item["error"], language="text")

            # Refresh data after sync
            total_spent = asyncio.run(_fetch_total_milestone_spent())
            transactions = asyncio.run(_fetch_all_transactions())
            monthly_df = asyncio.run(_fetch_monthly_spend())
            top_merchants_df = asyncio.run(_fetch_top_merchants(limit=7))

        except Exception as err:
            status_box.update(
                label="Sync failed. Check credentials or connection.",
                state="error",
                expanded=True,
            )
            st.error(f"Error during synchronization: {err}")


# ------------------------------------------------------------
# Hero: Milestone Spending Progress Card
# ------------------------------------------------------------
progress_fraction = (
    min(float(total_spent) / float(TARGET_AMOUNT), 1.0) if TARGET_AMOUNT > 0 else 0.0
)
progress_pct = progress_fraction * 100
remaining_amount = max(Decimal("0"), TARGET_AMOUNT - total_spent)

# Date calculations
now = datetime.now(UTC).replace(tzinfo=None)
days_total = max(1, (TARGET_END - TARGET_START).days)
days_elapsed = max(0, min(days_total, (now - TARGET_START).days))
days_remaining = max(0, (TARGET_END - now).days)

# Pace calculations
current_daily_pace = float(total_spent) / max(1, days_elapsed) if days_elapsed > 0 else 0.0
required_daily_pace = (
    float(remaining_amount) / max(1, days_remaining) if days_remaining > 0 else 0.0
)

with st.container(border=True):
    col_target_title, col_target_badge = st.columns([3, 1], vertical_alignment="center")
    with col_target_title:
        st.subheader("Spending milestone target — ₹12,00,000")
        start_str = TARGET_START.strftime("%B %d, %Y")
        end_str = TARGET_END.strftime("%B %d, %Y")
        st.caption(f"Period: **{start_str}** to **{end_str}**")
    with col_target_badge:
        if progress_fraction >= 1.0:
            st.badge("Milestone Achieved! 🏆", color="green")
        else:
            st.badge(f"{progress_pct:.1f}% achieved", color="blue")

    st.progress(progress_fraction)

    # Key KPI metrics row
    with st.container(horizontal=True):
        st.metric(
            label="Total spent in milestone",
            value=f"₹{total_spent:,.2f}",
            delta=f"{progress_pct:.1f}% achieved",
            border=True,
        )
        st.metric(
            label="Remaining to target",
            value=f"₹{remaining_amount:,.2f}",
            delta=f"{days_remaining} days left",
            delta_color="off",
            border=True,
        )
        st.metric(
            label="Current daily spend",
            value=f"₹{current_daily_pace:,.0f} / day",
            delta=f"Need ₹{required_daily_pace:,.0f} / day",
            delta_color="normal" if current_daily_pace >= required_daily_pace else "off",
            border=True,
        )
        st.metric(
            label="Total transactions",
            value=f"{len(transactions)}",
            delta=f"Avg ₹{float(total_spent) / max(1, len(transactions)):,.0f} / txn",
            delta_color="off",
            border=True,
        )

# ------------------------------------------------------------
# Visual Analytics Row
# ------------------------------------------------------------
col_analytics1, col_analytics2 = st.columns(2)

with col_analytics1:
    with st.container(border=True):
        st.subheader("Monthly spend trend")
        if not monthly_df.empty:
            st.bar_chart(
                monthly_df,
                x="Month",
                y="Spend (₹)",
                color="#4F46E5",
            )
        else:
            st.info("No monthly data available yet. Run sync to populate.")

with col_analytics2:
    with st.container(border=True):
        st.subheader("Top merchants by spend")
        if not top_merchants_df.empty:
            st.bar_chart(
                top_merchants_df,
                x="Merchant",
                y="Total Spend (₹)",
                color="#06B6D4",
                horizontal=True,
            )
        else:
            st.info("No merchant data available yet.")

# ------------------------------------------------------------
# Interactive Transactions Explorer
# ------------------------------------------------------------
with st.container(border=True):
    col_tx_header, col_tx_export = st.columns([3, 1], vertical_alignment="center")
    with col_tx_header:
        st.subheader("Transaction history")
        st.caption(f"Showing all verified transactions ({len(transactions)} total)")

    with col_tx_export:
        if transactions:
            df_full = pd.DataFrame(transactions)
            csv_data = df_full.to_csv(index=False).encode("utf-8")
            st.download_button(
                "Export CSV",
                data=csv_data,
                file_name="ccgeek_transactions.csv",
                mime="text/csv",
                icon=":material/download:",
            )

    if transactions:
        df = pd.DataFrame(transactions)

        # Quick filters
        filter_col1, filter_col2 = st.columns([2, 2], vertical_alignment="center")
        with filter_col1:
            search_query = st.text_input(
                "Search merchant",
                placeholder="🔍 Search merchant name (e.g., Apple, Cred, Amazon)...",
                label_visibility="collapsed",
            )
        with filter_col2:
            view_mode = st.segmented_control(
                "Filter",
                options=[
                    "Latest 20",
                    "Latest 50",
                    "All",
                    "Spends > ₹10,000",
                ],
                default="Latest 20",
                label_visibility="collapsed",
            )

        # Apply search filter
        if search_query:
            df = df[df["Merchant"].str.contains(search_query, case=False, na=False)]

        # Apply view filter
        if view_mode == "Latest 20":
            df = df.head(20)
        elif view_mode == "Latest 50":
            df = df.head(50)
        elif view_mode == "Spends > ₹10,000":
            df = df[df["Amount"] >= 10000]

        st.dataframe(
            df,
            column_config={
                "Date & Time": st.column_config.DatetimeColumn(
                    "Date & Time",
                    format="MMM DD, YYYY · hh:mm A",
                ),
                "Merchant": st.column_config.TextColumn(
                    "Merchant / Vendor",
                    width="medium",
                ),
                "Amount": st.column_config.NumberColumn(
                    "Amount (INR)",
                    format="₹%,.2f",
                ),
                "Currency": st.column_config.TextColumn(
                    "Currency",
                    width="small",
                ),
                "Card": st.column_config.TextColumn(
                    "Card",
                    width="medium",
                ),
                "Message ID": st.column_config.TextColumn(
                    "Graph ID",
                    width="small",
                ),
            },
            hide_index=True,
        )
    else:
        st.info("No transactions found in PostgreSQL. Click **Sync emails** above to import.")

# ------------------------------------------------------------
# Footer
# ------------------------------------------------------------
st.caption(
    "CCGeek · Personal Credit Card Milestone Tracker · Powered by Microsoft Graph & PostgreSQL"
)
