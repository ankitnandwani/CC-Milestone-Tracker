from collections.abc import Iterator
from types import TracebackType
from urllib.parse import quote

import httpx

from app.graph.constants import (
    GRAPH_PAGE_SIZE,
    HSBC_DATE_ONLY_SENDER,
    HSBC_DATE_ONLY_SUBJECT,
    HSBC_FOLDER_PATH,
    HSBC_SENDER,
    HSBC_TRANSACTION_SUBJECT_PREFIX,
)


class MailFolderError(RuntimeError):
    """The requested Outlook folder could not be resolved."""


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

    def is_expected_hsbc_alert(self, email: dict) -> bool:
        sender = (email.get("from", {}).get("emailAddress", {}).get("address") or "").lower()

        subject = (email.get("subject") or "").lower()
        return (sender == HSBC_SENDER and HSBC_TRANSACTION_SUBJECT_PREFIX.lower() in subject) or (
            sender == HSBC_DATE_ONLY_SENDER and HSBC_DATE_ONLY_SUBJECT.lower() in subject
        )

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

            response = self.get(next_link)

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

    def _resolve_hsbc_folder(self) -> str:
        folders_url = "/me/mailFolders"
        resolved = []
        for name in HSBC_FOLDER_PATH:
            resolved.append(name)
            matches = [
                folder["id"]
                for folder in self.get_all_pages(folders_url, params={"$select": "id,displayName"})
                if folder["displayName"].casefold() == name.casefold()
            ]
            if len(matches) != 1:
                path = " → ".join(resolved)
                if not matches:
                    raise MailFolderError(f"Outlook folder not found: {path}.")
                raise MailFolderError(f"More than one Outlook folder matches {path}.")
            folder_url = f"/me/mailFolders/{quote(matches[0], safe='')}"
            folders_url = f"{folder_url}/childFolders"
        return folder_url

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

        params = {
            "$orderby": "receivedDateTime desc",
            "$top": min(top, GRAPH_PAGE_SIZE) if top is not None else GRAPH_PAGE_SIZE,
            "$select": "id,subject,from,receivedDateTime",
        }
        response = self.get(f"{self._resolve_hsbc_folder()}/messages", params=params)
        scanned = pages_processed = 0

        while True:
            pages_processed += 1
            for email in response.get("value", []):
                yield email
                scanned += 1
                if top is not None and scanned >= top:
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
