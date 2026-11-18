from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.db import SessionLocal
from app.db.models.card import Card
from app.db.models.transaction import Transaction
from app.graph.client import GraphClient
from app.parser.hsbc import parse_transaction


async def sync_transactions(client: GraphClient) -> dict:
    """Import HSBC alerts through the CLI or dashboard."""
    fetched = 0
    parsed = 0
    imported = 0
    skipped = 0
    failed = []
    unmatched_cards = []

    async with SessionLocal() as session:
        # Prefetch existing transaction IDs for fast duplicate checking
        existing_tx_res = await session.execute(select(Transaction.graph_message_id))
        existing_ids = set(existing_tx_res.scalars().all())

        # Prefetch active cards mapped by last4
        cards_res = await session.execute(select(Card).where(Card.active.is_(True)))
        card_ids = {card.last4: card.id for card in cards_res.scalars()}

    for msg in client.iter_hsbc_transaction_messages():
        fetched += 1
        msg_id = msg["id"]

        # Quick duplicate check: skip without fetching HTML body
        if msg_id in existing_ids:
            skipped += 1
            continue

        # Get full HTML body of the message
        html = client.message_body(msg_id)
        try:
            tx = parse_transaction(graph_message_id=msg_id, html=html)
        except ValueError as e:
            failed.append({"id": msg_id, "subject": msg.get("subject", ""), "error": str(e)})
            continue
        parsed += 1

        # Match card
        card_id = card_ids.get(tx.card_last4)
        if card_id is None:
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

        statement = (
            insert(Transaction)
            .values(
                card_id=card_id,
                graph_message_id=tx.graph_message_id,
                merchant=tx.merchant,
                amount=tx.amount,
                currency=tx.currency,
                transaction_at=tx.transaction_at,
                pending=False,
            )
            .on_conflict_do_nothing(index_elements=[Transaction.graph_message_id])
            .returning(Transaction.id)
        )
        async with SessionLocal.begin() as session:
            inserted = (await session.execute(statement)).scalar_one_or_none()
        existing_ids.add(msg_id)
        if inserted is None:
            skipped += 1
        else:
            imported += 1

    return {
        "fetched": fetched,
        "parsed": parsed,
        "imported": imported,
        "skipped": skipped,
        "failed": failed,
        "unmatched_cards": unmatched_cards,
    }
