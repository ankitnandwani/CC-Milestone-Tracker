import asyncio

import typer
from sqlalchemy import select

from app.db import SessionLocal
from app.db.models.card import Card
from app.db.models.transaction import Transaction
from app.graph.auth import authenticate
from app.graph.client import GraphClient
from app.parser.hsbc import parse_transaction

app = typer.Typer(help="CCGeek CLI")

db_app = typer.Typer(help="Database commands")
graph_app = typer.Typer(help="Microsoft Graph commands")

app.add_typer(db_app, name="db")
app.add_typer(graph_app, name="graph")


@db_app.command("test")
def test_db() -> None:
    typer.secho("✓ Database OK", fg=typer.colors.GREEN)


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


async def _run_sync(client: GraphClient) -> dict[str, int]:
    """Core sync logic used by the ``graph sync`` CLI command."""
    fetched = 0
    parsed = 0
    imported = 0
    skipped = 0

    # Retrieve HSBC transaction messages (increase top to fetch more)
    messages = client.list_hsbc_transaction_messages()
    fetched = len(messages)

    failed = []  # keep track of messages that could not be parsed
    async with SessionLocal() as session:
        for msg in messages:
            # Get full HTML body of the message
            html = client.message_body(msg["id"])
            try:
                tx = parse_transaction(graph_message_id=msg["id"], html=html)
            except Exception as e:
                # Parsing failed – skip this email, record the failure
                failed.append({"id": msg["id"], "subject": msg.get("subject", ""), "error": str(e)})
                continue
            parsed += 1

            # Find the Card by its last4 digits
            card_res = await session.execute(select(Card).where(Card.last4 == tx.card_last4))
            card = card_res.scalar_one_or_none()
            if not card:
                # No matching card configured – skip
                skipped += 1
                continue

            # Check whether this message has already been imported
            dup_res = await session.execute(
                select(Transaction).where(Transaction.graph_message_id == tx.graph_message_id)
            )
            if dup_res.scalar_one_or_none():
                skipped += 1
                continue

            # Create and persist the Transaction
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


@graph_app.command("sync")
def sync() -> None:
    """Synchronize HSBC transaction emails into the database."""
    token = authenticate()
    with GraphClient(token) as client:
        stats = asyncio.run(_run_sync(client))

    typer.secho("Sync complete", fg=typer.colors.GREEN)
    typer.echo(f"Fetched: {stats['fetched']}")
    typer.echo(f"Parsed: {stats['parsed']}")
    typer.echo(f"Imported: {stats['imported']}")
    typer.echo(f"Skipped: {stats['skipped']}")
    if stats.get("failed"):
        typer.secho("Parsing failures:", fg=typer.colors.YELLOW)
        for f in stats["failed"]:
            typer.echo(f"ID: {f['id']}, Subject: {f['subject']}, Error: {f['error']}")


if __name__ == "__main__":
    app()
