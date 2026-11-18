# CCGeek agent guide

## Project and direction

CCGeek is a personal credit card tracker for one user. It imports transaction alerts from Outlook or Hotmail, records spending, and answers how much more the user needs to spend before a card's milestone deadline.

The current workflow covers one HSBC TravelOne card. The broader goal is to manage more cards and add tracking features as requirements are defined. Update this guide as those decisions are made and features ship.

## Current behavior

- The Streamlit dashboard tracks a fixed ₹12,00,000 milestone from June 13, 2026 through June 12, 2027. It shows progress, remaining spend, days left, and daily spend pace.
- The dashboard also offers manual email sync, a monthly spend chart, top merchants, searchable transaction history, and CSV export.
- The CLI can seed the default card and add or list card records. Email discovery and parsing are specific to HSBC alerts.
- The dashboard displays one active card in its header. The milestone total and monthly chart sum transactions in the milestone window across all cards and currencies as stored. Per-card milestones and currency conversion are future capabilities. Scope the queries before using the dashboard to track a second card's milestone.
- Both sync entry points are manual. The Streamlit path requests up to 100 matching messages per sync. The CLI path calls Graph without an explicit message cap.

## Stack and code map

Python 3.14 and `uv` manage the runtime and dependencies. Streamlit and pandas power the dashboard, and Typer provides the CLI. PostgreSQL 17 stores data through SQLAlchemy 2 async sessions and psycopg. Alembic manages schema changes. MSAL authenticates to Microsoft Graph, httpx makes requests, and BeautifulSoup helps parse HTML alerts. Pydantic Settings loads configuration. Docker Compose runs PostgreSQL and Adminer locally, and Ruff and pre-commit provide development checks.

| Area | Where to start |
| --- | --- |
| Dashboard, milestone constants, SQL queries, and CSV export | `app/ui/streamlit_app.py` |
| CLI commands for database checks, card enrollment, and mail sync | `app/cli.py` |
| Microsoft sign-in, local token cache, mail search, and pagination | `app/graph/auth.py`, `app/graph/client.py`, and `app/graph/constants.py` |
| HSBC alert parsing and normalized transaction fields | `app/parser/hsbc.py` and `app/parser/models.py` |
| Connection settings, async session factory, models, and migrations | `app/core/config.py`, `app/db/session.py`, `app/db/models/`, and `alembic/versions/` |

## Import and data model

1. MSAL tries a cached sign-in first, then falls back to interactive sign-in on localhost port 8765. It requests delegated `User.Read` and `Mail.Read` scopes and stores its token cache in the platform-specific CCGeek user data directory.
2. The Graph client discovers HSBC transaction messages using the configured sender and subject match and follows pagination. Sync skips known Graph message IDs before retrieving and parsing the remaining HTML bodies.
3. The parser returns the card's last four digits, merchant, decimal amount, currency, transaction date and time, and Graph message ID. Sync matches an active card by its last four digits, reports unmatched cards and parsing failures, and writes matched transactions.
4. The migrated tables are `cards` and `transactions`. Each transaction references a card, and a unique `graph_message_id` prevents repeat imports of the same message ID. The `SyncState` model exists in the source and has no checked-in migration or active role in sync.

## Local development

Run commands from the repository root. Use Python 3.14, `uv`, and Docker Compose. Configure `.env` or process environment variables before running the CLI or migrations. Required settings are `DB_HOST`, `DB_USER`, `DB_PASSWORD`, and `MICROSOFT_CLIENT_ID`. For the bundled local PostgreSQL service, use host `localhost`, port `5432`, database `ccgeek`, the credentials in `docker-compose.yml`, and `DB_SSL_MODE=disable`. `MICROSOFT_TENANT_ID` defaults to `common`. Graph sync requires a Microsoft app registration and mailbox sign-in.

```bash
uv sync
docker compose up -d
uv run alembic upgrade head
uv run python -m app.cli db seed
uv run python -m app.cli db test
uv run streamlit run app/ui/streamlit_app.py
```

Use `uv run python -m app.cli --help` to discover commands, `graph auth` to verify sign-in, and `graph sync` to import from the CLI. Use `uv run ruff check .` and `uv run ruff format --check .` for static checks. The repository currently has a database connection smoke script in `scripts/test_connection.py`.

## Working on the project

- Keep changes simple and use the existing Python functions, SQLAlchemy models, and Streamlit entry point.
- Check both sync implementations in `app/cli.py` and `app/ui/streamlit_app.py` when changing import behavior. The default card can also be seeded from either entry point.
- Check the models and existing migrations before changing schema. Preserve decimal amounts, the original currency, and message-ID deduplication when changing ingestion. Transaction timestamps currently use timezone-naive values from the parsed alerts.
- Use synthetic or redacted transaction alerts for examples and fixtures. Keep mailbox data, database credentials, and token caches out of version control.
