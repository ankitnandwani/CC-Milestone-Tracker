import asyncio

import typer
from sqlalchemy import select

from app.db import SessionLocal
from app.db.enums import Bank, CardNetwork
from app.db.models.card import Card
from app.db.models.transaction import Transaction
from app.graph.auth import authenticate
from app.graph.client import GraphClient
from app.parser.hsbc import parse_transaction
from app.sync import sync_transactions

app = typer.Typer(help="CCGeek CLI")

db_app = typer.Typer(help="Database commands")
graph_app = typer.Typer(help="Microsoft Graph commands")

card_app = typer.Typer(help="Card management commands")

app.add_typer(db_app, name="db")
app.add_typer(graph_app, name="graph")
app.add_typer(card_app, name="card")


@db_app.command("test")
def test_db() -> None:
    async def _test() -> None:
        async with SessionLocal() as session:
            cards_count = (await session.execute(select(Card))).scalars().all()
            tx_count = (await session.execute(select(Transaction))).scalars().all()
            typer.secho("✓ Database connection OK", fg=typer.colors.GREEN)
            typer.echo(f"Cards configured: {len(cards_count)}")
            typer.echo(f"Transactions in DB: {len(tx_count)}")

    asyncio.run(_test())


@db_app.command("seed")
def seed_db() -> None:
    """Seed initial default credit cards if none exist."""

    async def _seed() -> None:
        async with SessionLocal() as session:
            res = await session.execute(
                select(Card).where(Card.bank_name == Bank.HSBC, Card.last4 == "2677")
            )
            card = res.scalar_one_or_none()
            if not card:
                card = Card(
                    bank_name=Bank.HSBC,
                    card_name="TravelOne",
                    card_network=CardNetwork.MASTERCARD,
                    last4="2677",
                    currency="INR",
                    active=True,
                )
                session.add(card)
                await session.commit()
                typer.secho(
                    "✓ Seeded default card: HSBC TravelOne (••2677)",
                    fg=typer.colors.GREEN,
                )
            else:
                typer.echo(
                    f"Card ending in {card.last4} already exists "
                    f"({card.bank_name} {card.card_name})."
                )

    asyncio.run(_seed())


@card_app.command("list")
def list_cards() -> None:
    """List all registered cards in the database."""

    async def _list() -> None:
        async with SessionLocal() as session:
            cards = (await session.execute(select(Card).order_by(Card.created_at))).scalars().all()
            if not cards:
                typer.secho(
                    "No cards found in database. Run 'db seed' or 'card add'.",
                    fg=typer.colors.YELLOW,
                )
                return
            typer.echo(f"Found {len(cards)} card(s):")
            for c in cards:
                status = "Active" if c.active else "Inactive"
                typer.echo(
                    f"- [{c.bank_name}] {c.card_name} · •••• {c.last4} "
                    f"({c.card_network}) [{status}] (ID: {c.id})"
                )

    asyncio.run(_list())


@card_app.command("add")
def add_card(
    bank: str = typer.Option(
        ..., "--bank", "-b", help="Bank name (HSBC, AU, HDFC, ICICI, AXIS, AMEX)"
    ),
    name: str = typer.Option(
        ..., "--name", "-n", help="Card name (e.g. TravelOne, Live+, Premier)"
    ),
    network: str = typer.Option(..., "--network", help="Network (VISA, MASTERCARD, AMEX, RUPAY)"),
    last4: str = typer.Option(..., "--last4", "-l", help="Last 4 digits of card number"),
    currency: str = typer.Option("INR", "--currency", "-c", help="Currency code (e.g. INR)"),
) -> None:
    """Add a new credit card to track."""

    async def _add() -> None:
        async with SessionLocal() as session:
            res = await session.execute(
                select(Card).where(Card.last4 == last4.strip(), Card.bank_name == bank.upper())
            )
            if res.scalar_one_or_none():
                typer.secho(f"Card with last4 {last4} already exists!", fg=typer.colors.RED)
                return

            card = Card(
                bank_name=Bank(bank.upper()),
                card_name=name.strip(),
                card_network=CardNetwork(network.upper()),
                last4=last4.strip(),
                currency=currency.upper().strip(),
                active=True,
            )
            session.add(card)
            await session.commit()
            typer.secho(
                f"✓ Added card: {card.bank_name} {card.card_name} (••{card.last4})",
                fg=typer.colors.GREEN,
            )

    asyncio.run(_add())


@graph_app.command("auth")
def auth() -> None:
    token = authenticate()
    with GraphClient(token) as client:
        me = client.me()

        typer.secho("✓ Authentication successful", fg=typer.colors.GREEN)
        typer.echo(f"Name : {me['displayName']}")
        typer.echo(f"Email: {me['userPrincipalName']}")


@graph_app.command("messages")
def list_messages(
    top: int = typer.Option(
        10,
        "--top",
        "-t",
        help="Number of latest messages to fetch.",
    ),
) -> None:
    token = authenticate()
    with GraphClient(token) as client:
        emails = client.list_messages(top=top)

        typer.echo(f"Fetched {len(emails)} message(s)\n")

        for email in emails:
            sender = email.get("from", {}).get("emailAddress", {}).get("address", "")

            typer.echo(f"{email['receivedDateTime']} | {sender} | {email['subject']}")


@graph_app.command("show")
def show_message(
    message_id: str,
) -> None:
    """Show a single email."""

    token = authenticate()

    with GraphClient(token) as client:
        message = client.message(message_id)

        typer.secho(
            f"Subject : {message['subject']}",
            fg=typer.colors.GREEN,
        )
        typer.echo(f"Date    : {message['receivedDateTime']}")
        typer.echo(f"From    : {message['from']['emailAddress']['address']}")

        typer.echo("\n" + "=" * 80 + "\n")

        body = message.get("body", {}).get("content", "")
        typer.echo(body)


@graph_app.command("parse")
def parse_email(
    message_id: str,
) -> None:
    token = authenticate()

    with GraphClient(token) as client:
        html = client.message_body(message_id)

    transaction = parse_transaction(
        graph_message_id=message_id,
        html=html,
    )

    typer.echo(transaction)


@graph_app.command("hsbc")
def list_hsbc_messages(
    top: int = typer.Option(20),
) -> None:
    typer.secho("START", fg=typer.colors.YELLOW)
    token = authenticate()
    typer.secho("TOKEN OK", fg=typer.colors.YELLOW)
    with GraphClient(token) as client:
        typer.secho("CLIENT CREATED", fg=typer.colors.YELLOW)
        emails = client.list_hsbc_transaction_messages(top=top)
        typer.secho(f"EMAILS = {len(emails)}", fg=typer.colors.YELLOW)

        for email in emails:
            typer.echo(f"ID      : {email['id']}")
            typer.echo(f"Date    : {email['receivedDateTime']}")
            typer.echo(f"Subject : {email['subject']}")
            typer.echo("-" * 80)


@graph_app.command("sync")
def sync() -> None:
    """Synchronize configured card transaction emails into the database."""
    token = authenticate()
    with GraphClient(token) as client:
        stats = asyncio.run(sync_transactions(client))

    typer.secho("Sync complete", fg=typer.colors.GREEN)
    typer.echo(f"Fetched: {stats['fetched']}")
    typer.echo(f"Parsed: {stats['parsed']}")
    typer.echo(f"Imported: {stats['imported']}")
    typer.echo(f"Skipped: {stats['skipped']}")
    typer.echo(f"Emails outside the recognized transaction format: {stats['ignored']}")
    if stats["latest_received_at"]:
        typer.echo(f"Newest HSBC folder email received: {stats['latest_received_at']}")
    if stats.get("unmatched_cards"):
        typer.secho(
            f"⚠️ {len(stats['unmatched_cards'])} transaction(s) skipped "
            f"because the card is not registered in DB:",
            fg=typer.colors.RED,
        )
        for u in stats["unmatched_cards"]:
            typer.echo(f"  - Card •••• {u['card_last4']} | {u['merchant']} | ₹{u['amount']}")
        typer.echo(
            "Tip: Add the card using "
            "'uv run python -m app.cli card add' or seed with "
            "'uv run python -m app.cli db seed'"
        )
    if stats.get("failed"):
        typer.secho("Parsing failures:", fg=typer.colors.YELLOW)
        for f in stats["failed"]:
            typer.echo(f"ID: {f['id']}, Subject: {f['subject']}, Error: {f['error']}")


if __name__ == "__main__":
    app()
