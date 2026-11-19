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
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx
import pandas as pd
import streamlit as st
from sqlalchemy import desc, func, select

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.db import SessionLocal  # noqa: E402
from app.db.enums import Bank, CardNetwork  # noqa: E402
from app.db.models.card import Card  # noqa: E402
from app.db.models.transaction import Transaction  # noqa: E402
from app.graph.auth import OutlookSignInError, authenticate  # noqa: E402
from app.graph.client import GraphClient, MailFolderError  # noqa: E402
from app.milestones import card_milestones  # noqa: E402
from app.sync import sync_transactions  # noqa: E402

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
# Database queries
# ------------------------------------------------------------
async def _fetch_cards() -> list[Card]:
    async with SessionLocal() as session:
        res = await session.execute(
            select(Card).where(Card.active.is_(True)).order_by(Card.created_at, Card.id)
        )
        return list(res.scalars())


async def _fetch_milestone_spend(card: Card, start: datetime, end: datetime) -> tuple[Decimal, int]:
    async with SessionLocal() as session:
        result = await session.execute(
            select(func.sum(Transaction.amount), func.count(Transaction.id)).where(
                Transaction.card_id == card.id,
                Transaction.currency == card.currency,
                Transaction.transaction_at >= start,
                Transaction.transaction_at < end,
            )
        )
        total, count = result.one()
        return total or Decimal("0"), count


async def _fetch_all_transactions(card: Card) -> list[dict]:
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
            .where(Transaction.card_id == card.id)
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


async def _fetch_monthly_spend(card: Card) -> pd.DataFrame:
    async with SessionLocal() as session:
        result = await session.execute(
            select(
                func.date_trunc("month", Transaction.transaction_at).label("month"),
                func.sum(Transaction.amount).label("total_spend"),
                func.count(Transaction.id).label("tx_count"),
            )
            .where(
                Transaction.card_id == card.id,
                Transaction.currency == card.currency,
            )
            .group_by("month")
            .order_by("month")
        )
        rows = result.all()

    if not rows:
        return pd.DataFrame(columns=["Month", "Spend", "Transactions"])

    data = [
        {
            "Month": r.month.strftime("%b %Y"),
            "Spend": float(r.total_spend),
            "Transactions": int(r.tx_count),
        }
        for r in rows
    ]
    return pd.DataFrame(data)


async def _fetch_top_merchants(card: Card, limit: int = 7) -> pd.DataFrame:
    async with SessionLocal() as session:
        result = await session.execute(
            select(
                Transaction.merchant,
                func.sum(Transaction.amount).label("total_spend"),
                func.count(Transaction.id).label("tx_count"),
            )
            .where(Transaction.card_id == card.id, Transaction.currency == card.currency)
            .group_by(Transaction.merchant)
            .order_by(desc("total_spend"))
            .limit(limit)
        )
        rows = result.all()

    if not rows:
        return pd.DataFrame(columns=["Merchant", "Total Spend", "Transactions"])

    data = [
        {
            "Merchant": r.merchant,
            "Total Spend": float(r.total_spend),
            "Transactions": int(r.tx_count),
        }
        for r in rows
    ]
    return pd.DataFrame(data)


async def _seed_default_card() -> None:
    async with SessionLocal() as session:
        res = await session.execute(
            select(Card).where(Card.bank_name == Bank.HSBC, Card.last4 == "2677")
        )
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


async def _configure_au_card() -> None:
    async with SessionLocal.begin() as session:
        result = await session.execute(
            select(Card).where(Card.bank_name == Bank.AU, Card.last4 == "3052")
        )
        card = result.scalar_one_or_none()
        if card is None:
            session.add(
                Card(
                    bank_name=Bank.AU,
                    card_name="Zenith⁺",
                    card_network=CardNetwork.VISA,
                    last4="3052",
                    currency="INR",
                    active=True,
                )
            )
        else:
            card.active = True


cards = asyncio.run(_fetch_cards())

# ------------------------------------------------------------
# Header & Navigation
# ------------------------------------------------------------
header_col1, header_col2 = st.columns([3, 1], vertical_alignment="center")

with header_col1:
    st.title("CCGeek")
    cards_by_id = {item.id: item for item in cards}
    labels = {item.id: f"{item.bank_name} {item.card_name} · •••• {item.last4}" for item in cards}
    selected_id = st.selectbox("Card", list(cards_by_id), format_func=labels.__getitem__)
    card = cards_by_id.get(selected_id)

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

if not any(item.bank_name == Bank.AU and item.last4 == "3052" for item in cards):
    if st.button("Add AU Zenith⁺ (••3052)"):
        asyncio.run(_configure_au_card())
        st.rerun()

# ------------------------------------------------------------
# Sync Trigger Handling
# ------------------------------------------------------------
if sync_clicked:
    with st.status("Connecting to Outlook...", expanded=True) as status_box:
        stage = "Outlook sign-in"
        try:
            token = authenticate(show_device_code=st.info)
            stage = "Transaction import"
            with GraphClient(token) as client:
                st.write("Scanning the Outlook folders for configured cards.")
                stats = asyncio.run(sync_transactions(client))

            if received_at := stats["latest_received_at"]:
                st.write(f"Newest email received: {received_at[:10]}.")
            if stats["ignored"]:
                st.write(f"{stats['ignored']} email(s) did not match the transaction format.")

            status_box.update(
                label=(
                    f"Sync complete. Checked {stats['fetched']} email(s) and imported "
                    f"{stats['imported']} transaction(s)."
                ),
                state="complete",
                expanded=not stats["imported"] or bool(stats["failed"] or stats["unmatched_cards"]),
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
            elif stats["skipped"] and not (stats["failed"] or stats["ignored"]):
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
                    st.write("Some transactions could not be assigned to a single active card.")
                    for item in stats["unmatched_cards"]:
                        st.caption(
                            f"**Card**: {item['bank']} •••• {item['card_last4']} "
                            f"({item['reason']}) "
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

        except Exception as err:
            status_box.update(
                label=f"{stage} failed.",
                state="error",
                expanded=True,
            )
            if isinstance(err, (OutlookSignInError, MailFolderError)):
                st.error(str(err))
            elif isinstance(err, httpx.HTTPStatusError):
                st.error(f"Microsoft Graph returned HTTP {err.response.status_code}.")
            else:
                st.error(f"{stage} failed with {type(err).__name__}.")


if card is None:
    st.stop()

now = datetime.now(ZoneInfo("Asia/Kolkata")).replace(tzinfo=None)
symbol = "₹" if card.currency == "INR" else f"{card.currency} "
if card.bank_name == Bank.AU:
    st.caption("Milestone progress uses imported INR purchase alerts.")
period_spend = {}
for title, target, start, end in card_milestones(card.bank_name, card.last4, now.date()):
    if (start, end) not in period_spend:
        period_spend[start, end] = asyncio.run(_fetch_milestone_spend(card, start, end))
    total, count = period_spend[start, end]
    progress = max(0.0, min(float(total / target), 1.0))
    remaining = max(Decimal("0"), target - total)
    close_date = (end - timedelta(days=1)).date()
    days_left = max(0, (end.date() - now.date()).days) if now >= start else (end - start).days
    elapsed = max(0, (min(now.date(), close_date) - start.date()).days + 1)
    with st.container(border=True):
        st.subheader(f"{title} · {symbol}{target:,.0f}")
        st.caption(f"{start:%b %d, %Y} – {close_date:%b %d, %Y}")
        st.progress(progress)
        columns = st.columns(4)
        columns[0].metric("Spend in period", f"{symbol}{total:,.2f}", f"{progress:.1%} achieved")
        columns[1].metric(
            "Remaining to target",
            f"{symbol}{remaining:,.2f}",
            f"{days_left} days left",
            delta_color="off",
        )
        columns[2].metric(
            "Current daily spend",
            f"{symbol}{total / max(1, elapsed):,.0f} / day",
            f"Need {symbol}{remaining / days_left:,.0f} / day" if days_left else None,
            delta_color="off",
        )
        columns[3].metric("Transactions in period", count)

transactions = asyncio.run(_fetch_all_transactions(card))
monthly_df = asyncio.run(_fetch_monthly_spend(card))
top_merchants_df = asyncio.run(_fetch_top_merchants(card))

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
                y="Spend",
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
                y="Total Spend",
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
                file_name=f"ccgeek_transactions_{card.last4}.csv",
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
                    "Amount",
                    format="%,.2f",
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
