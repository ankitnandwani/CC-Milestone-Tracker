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
        matches: list[dict] = []

        params: dict = {
            "$search": f'"{HSBC_TRANSACTION_SUBJECT_PREFIX}"',
            "$top": min(top, GRAPH_PAGE_SIZE) if top is not None else GRAPH_PAGE_SIZE,
            "$select": ",".join(
                [
                    "id",
                    "subject",
                    "from",
                    "receivedDateTime",
                ]
            ),
        }

        url: str | None = "/me/messages"
        pages_processed = 0

        while url:
            try:
                response = self.get(
                    url,
                    params=params,
                    headers={"ConsistencyLevel": "eventual"},
                )
            except Exception:
                # Fallback to standard paging if $search fails
                if url == "/me/messages" and "$search" in params:
                    params.pop("$search", None)
                    response = self.get(url, params=params)
                else:
                    raise

            emails = response.get("value", [])
            for email in emails:
                if self._is_hsbc_transaction(email):
                    matches.append(email)
                    if top is not None and len(matches) >= top:
                        return matches

            pages_processed += 1
            if max_pages is not None and pages_processed >= max_pages:
                break

            url = response.get("@odata.nextLink")
            params = None

        return matches if top is None else matches[:top]

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
