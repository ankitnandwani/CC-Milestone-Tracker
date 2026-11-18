from collections.abc import Iterator
from types import TracebackType

import httpx

from app.graph.constants import GRAPH_PAGE_SIZE, HSBC_SENDER, HSBC_TRANSACTION_SUBJECT_PREFIX


class GraphClient:
    BASE_URL = "https://graph.microsoft.com/v1.0"

    def __init__(self, access_token: str) -> None:
        self._client = httpx.Client(
            base_url=self.BASE_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
            },
            timeout=30,
        )

    def get(self, endpoint: str, **kwargs) -> dict:
        response = self._client.get(endpoint, **kwargs)
        response.raise_for_status()
        return response.json()

    def me(self) -> dict:
        return self.get("/me")

    def _is_hsbc_transaction(self, email: dict) -> bool:
        sender = (email.get("from", {}).get("emailAddress", {}).get("address") or "").lower()

        # Flexible match: sender must be HSBC and subject contains configured prefix
        subject = (email.get("subject") or "").lower()
        return sender == HSBC_SENDER and HSBC_TRANSACTION_SUBJECT_PREFIX.lower() in subject

    def get_all_pages(
        self,
        endpoint: str,
        params: dict | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        items: list[dict] = []

        response = self.get(endpoint, params=params)

        while True:
            items.extend(response.get("value", []))

            if limit is not None and len(items) >= limit:
                return items[:limit]

            next_link = response.get("@odata.nextLink")
            if not next_link:
                break

            response = self._client.get(next_link).json()

        return items

    def list_messages(self, top: int = 10) -> list[dict]:
        return self.get_all_pages(
            "/me/messages",
            params={
                "$top": min(top, 50),
                "$orderby": "receivedDateTime desc",
                "$select": ",".join(
                    [
                        "id",
                        "subject",
                        "from",
                        "receivedDateTime",
                    ]
                ),
            },
            limit=top,
        )

    def get_url(self, url: str) -> dict:
        response = self._client.get(url)
        response.raise_for_status()
        return response.json()

    def list_hsbc_transaction_messages(
        self,
        top: int | None = None,
        max_pages: int | None = None,
    ) -> list[dict]:
        return list(self.iter_hsbc_transaction_messages(top=top, max_pages=max_pages))

    def iter_hsbc_transaction_messages(
        self,
        top: int | None = None,
        max_pages: int | None = None,
    ) -> Iterator[dict]:
        if top == 0 or max_pages == 0:
            return

        # Graph requires the ordered property to appear first in the filter.
        params = {
            "$filter": (
                "receivedDateTime ge 1900-01-01T00:00:00Z"
                f" and from/emailAddress/address eq '{HSBC_SENDER}'"
            ),
            "$orderby": "receivedDateTime desc",
            "$top": min(top, GRAPH_PAGE_SIZE) if top is not None else GRAPH_PAGE_SIZE,
            "$select": "id,subject,from,receivedDateTime",
        }
        response = self.get("/me/messages", params=params)
        matches = pages_processed = 0

        while True:
            pages_processed += 1
            for email in response.get("value", []):
                if self._is_hsbc_transaction(email):
                    yield email
                    matches += 1
                    if top is not None and matches >= top:
                        return

            next_link = response.get("@odata.nextLink")
            if not next_link or (max_pages is not None and pages_processed >= max_pages):
                return
            response = self.get(next_link)

    def message_body(self, message_id: str) -> str:
        message = self.get(
            f"/me/messages/{message_id}",
            params={
                "$select": "body",
            },
        )

        return message["body"]["content"]

    def message(self, message_id: str) -> dict:
        return self.get(
            f"/me/messages/{message_id}",
            params={
                "$select": ",".join(
                    [
                        "id",
                        "subject",
                        "body",
                        "bodyPreview",
                        "receivedDateTime",
                        "from",
                    ]
                ),
            },
        )

    def get_message(self, message_id: str) -> dict:
        return self.get(
            f"/me/messages/{message_id}",
            params={
                "$select": ",".join(
                    [
                        "id",
                        "subject",
                        "body",
                        "receivedDateTime",
                    ]
                ),
            },
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "GraphClient":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()
