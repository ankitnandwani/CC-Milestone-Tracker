# CCGeek — Project Context & Development Guide

## 1. Project Overview

CCGeek is a personal credit-card spend tracker.

The goal is to automatically read credit-card transaction emails from Microsoft Outlook/Hotmail using Microsoft Graph,
parse the transaction information, store it in PostgreSQL, and provide a simple UI for tracking spending and milestones.

This is a **personal project used by one person only**.

### Most important architectural principle

Keep the application simple.

Do NOT introduce abstractions, patterns, services, repositories, factories, dependency injection, event buses, CQRS,
etc. unless there is a genuine need.

Prefer:

* simple Python functions
* straightforward SQLAlchemy models
* simple service functions/classes only when useful
* direct database access where appropriate
* small modules
* readable code over clever code

Do not over-engineer this project for hypothetical future scale.

---

# 2. Current Technology Stack

* Python 3.14+
* `uv` for Python/package management
* Typer for CLI
* SQLAlchemy 2.0 (async engine & sessionmaker with psycopg)
* Alembic for database migrations
* PostgreSQL 17
* psycopg (binary)
* httpx
* MSAL & msal-extensions (token caching)
* Microsoft Graph API
* BeautifulSoup4 for HTML parsing
* Pydantic Settings
* Streamlit for the UI
* Render planned for hosting

Local development currently uses Docker for PostgreSQL and Adminer.

---

# 3. Local Development Environment

PostgreSQL:

```text
Docker container: ccgeek-postgres
```

Adminer:

```text
Docker container: ccgeek-adminer
```

PostgreSQL connectivity has been tested successfully.

---

# 4. High-Level Architecture

Current directory structure:

```text
app/
├── cli.py
├── core/
│   ├── config.py
│   └── logger.py
├── db/
│   ├── base.py
│   ├── enums.py
│   ├── models/
│   │   ├── card.py
│   │   ├── sync_state.py
│   │   └── transaction.py
│   ├── session.py
│   └── types.py
├── graph/
│   ├── auth.py
│   ├── client.py
│   └── constants.py
├── parser/
│   ├── hsbc.py
│   ├── models.py
│   └── utils.py
└── ui/
    └── streamlit_app.py
```

The architecture should evolve only when needed.

---

# 5. Database

Alembic is used for migrations.

### `cards` table

Revision: `35e11d06c43b` (create cards table)

Schema:

```text
bank_name       VARCHAR(20)       NOT NULL
card_name       VARCHAR(100)      NOT NULL
card_network    VARCHAR(20)       NOT NULL
last4           VARCHAR(4)        NOT NULL
currency        VARCHAR(3)        NOT NULL
active          BOOLEAN           NOT NULL
id              UUID              NOT NULL PRIMARY KEY
created_at      TIMESTAMP WITH TZ NOT NULL
updated_at      TIMESTAMP WITH TZ NOT NULL
```

### `transactions` table

Revision: `5936c985c875` (create transactions table)

Schema:

```text
id                UUID              NOT NULL PRIMARY KEY
card_id           UUID              NOT NULL (FK -> cards.id)
graph_message_id  VARCHAR(255)      NOT NULL UNIQUE
merchant          VARCHAR(255)      NOT NULL
amount            NUMERIC(12, 2)    NOT NULL
currency          VARCHAR(3)        NOT NULL
transaction_at    TIMESTAMP         NOT NULL
pending           BOOLEAN           NOT NULL DEFAULT FALSE
created_at        TIMESTAMP WITH TZ NOT NULL
updated_at        TIMESTAMP WITH TZ NOT NULL
```

Before implementing anything that changes the schema, inspect existing models and migrations first.

---

# 6. Card Strategy

Currently tracking **one HSBC credit card**.

The card ends in: `2677`

Adding a second card later should require only adding another card record in the database.

---

# 7. Microsoft Graph Authentication

MSAL is used for authentication with token caching.

Flow:
1. Acquire token silently from token cache.
2. If silent acquisition fails, interactive authentication on `http://localhost:8765`.
3. Cache the resulting token.

Microsoft Graph scopes:
* `User.Read`
* `Mail.Read`

Authentication CLI command:

```bash
uv run python -m app.cli graph auth
```

---

# 8. GraphClient

`GraphClient` (`app/graph/client.py`) uses `httpx`.

Base URL: `https://graph.microsoft.com/v1.0`

Provides:
* `/me`
* `list_messages()`
* `list_hsbc_transaction_messages()` (with `@odata.nextLink` pagination)
* `message(message_id)`
* `message_body(message_id)`

---

# 9. HSBC Email Details & Parsing

* Sender: `hsbc@mail.hsbc.co.in`
* Subject prefix configured in `app/graph/constants.py`
* Parser located in `app/parser/hsbc.py`
* Returns `ParsedTransaction` dataclass (`app/parser/models.py`):
  * `graph_message_id`
  * `card_last4`
  * `merchant`
  * `amount` (Decimal)
  * `currency`
  * `transaction_at` (datetime)

---

# 10. CLI Commands

The CLI uses Typer (`app/cli.py`).

Command hierarchy:

```text
ccgeek
├── db
│   └── test
└── graph
    ├── auth
    ├── messages [--top N]
    ├── hsbc [--top N]
    ├── show <message-id>
    ├── parse <message-id>
    └── sync
```

### Key CLI Commands:

```bash
# Test DB connectivity
uv run python -m app.cli db test

# Authenticate with Microsoft Graph
uv run python -m app.cli graph auth

# List latest HSBC transaction emails
uv run python -m app.cli graph hsbc --top 20

# Parse a single email for testing
uv run python -m app.cli graph parse "<message-id>"

# Synchronize HSBC transaction emails into PostgreSQL (idempotent)
uv run python -m app.cli graph sync
```

---

# 11. Transaction Persistence & Sync Flow

The sync process (`_run_sync`):
1. Fetches HSBC transaction emails from Microsoft Graph.
2. Parses transaction data (HTML body → `ParsedTransaction`).
3. Looks up the card by `card_last4`.
4. Checks `graph_message_id` for duplicate prevention.
5. Persists new transactions to PostgreSQL.
6. Returns summary statistics (`fetched`, `parsed`, `imported`, `skipped`, `failed`).

Sync is fully **idempotent** — running it repeatedly will not create duplicate records.

---

# 12. Streamlit UI

The UI is built with **Streamlit** (`app/ui/streamlit_app.py`).

### How to Run:

```bash
uv run streamlit run app/ui/streamlit_app.py
```

### Current UI Features:
1. **Spending Target Progress Bar & Metric**:
   - Target amount: ₹12,00,000 (Rs 12 Lakhs milestone)
   - Target period: June 13, 2026 – June 12, 2027
   - Shows progress bar, total amount spent, and remaining balance delta.
2. **Sync Now Button**:
   - Manually triggers email synchronization with Microsoft Graph.
   - Shows live progress spinner, success notification, summary stats JSON, and any parsing failures.
3. **Recent Transactions Table**:
   - Displays latest 20 transactions sorted by date descending.
   - Columns: Date, Card last4, Merchant, Amount, Message ID.

*(Note: Old NiceGUI code and dependencies have been removed in favor of Streamlit).*

---

# 13. Current Project Status

Completed:

* [x] Project setup with `uv` & Python 3.14+
* [x] PostgreSQL 17 and Adminer in Docker
* [x] SQLAlchemy models and Alembic migrations (`cards`, `transactions`)
* [x] Microsoft App Registration & MSAL authentication with token cache
* [x] GraphClient with `@odata.nextLink` pagination
* [x] HSBC email discovery and HTML parser (`app/parser/hsbc.py`)
* [x] Idempotent transaction persistence and deduplication via `graph_message_id`
* [x] CLI `graph sync` command
* [x] Streamlit UI (`app/ui/streamlit_app.py`) with:
  * [x] Milestone spending target bar & remaining metric
  * [x] Recent transactions table
  * [x] Interactive "Sync now" button
* [x] NiceGUI removal and cleanup

---

# 14. Roadmap & Future Features

1. **Transaction Categorization**: Simple rule-based merchant categorization (Food, Shopping, Travel, Bills, etc.).
2. **Monthly Spend Visualizations**: Monthly breakdown chart in Streamlit.
3. **Multi-Card Support**: Adding additional cards and card-wise filter/breakdown.
4. **Scheduled Sync**: Daily background synchronization.
5. **Deployment**: Hosting on Render.

---

# 15. Important Development Rules

* **Keep things simple**: This is a personal project. Avoid unnecessary design patterns or enterprise abstractions.
* **Streamlit for UI**: All UI work is in Streamlit (`app/ui/streamlit_app.py`).
* **Preserve working code**: Inspect existing models, functions, and migrations before proposing changes.
* **Source of Truth**: The repository is always the source of truth.
