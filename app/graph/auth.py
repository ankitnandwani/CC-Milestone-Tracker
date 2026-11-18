from collections.abc import Callable
from pathlib import Path
from time import time

from msal import PublicClientApplication, SerializableTokenCache
from platformdirs import user_data_dir

from app.core.config import get_settings

settings = get_settings()

GRAPH_SCOPES: list[str] = [
    "User.Read",
    "Mail.Read",
]

CACHE_PATH = Path(user_data_dir("CCGeek")) / "token_cache.bin"


class OutlookSignInError(RuntimeError):
    """The mailbox requires attention before sync can continue."""


def load_cache() -> SerializableTokenCache:
    cache = SerializableTokenCache()

    if CACHE_PATH.exists():
        cache.deserialize(CACHE_PATH.read_text())

    return cache


def save_cache(cache: SerializableTokenCache) -> None:
    if cache.has_state_changed:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(cache.serialize())


def create_app() -> tuple[PublicClientApplication, SerializableTokenCache]:
    cache = load_cache()

    app = PublicClientApplication(
        client_id=settings.microsoft_client_id,
        authority=f"https://login.microsoftonline.com/{settings.microsoft_tenant_id}",
        token_cache=cache,
        timeout=15,
    )

    return app, cache


def authenticate(*, show_device_code: Callable[[str], None] | None = None) -> str:
    app, cache = create_app()

    username = settings.microsoft_mailbox_username
    accounts = app.get_accounts(username=username)
    if accounts:
        result = app.acquire_token_silent(
            GRAPH_SCOPES,
            account=accounts[0],
        )

        if result and "access_token" in result:
            save_cache(cache)
            return result["access_token"]

    if show_device_code is None:
        result = app.acquire_token_interactive(GRAPH_SCOPES, port=8765, login_hint=username)
    else:
        if not username:
            raise OutlookSignInError(
                "Outlook needs to be connected again. Set MICROSOFT_MAILBOX_USERNAME to "
                "the Outlook sign-in address in the app's settings, then retry."
            )
        flow = app.initiate_device_flow(scopes=GRAPH_SCOPES)
        if "user_code" not in flow:
            raise OutlookSignInError(
                f"Microsoft could not start device sign-in ({flow.get('error', 'unknown error')})."
            )
        flow["expires_at"] = min(flow["expires_at"], time() + 180)
        show_device_code(flow["message"])
        result = app.acquire_token_by_device_flow(flow)

    if "access_token" not in result:
        raise OutlookSignInError(
            f"Microsoft sign-in did not complete ({result.get('error', 'unknown error')})."
        )
    if username:
        signed_in_username = result.get("id_token_claims", {}).get("preferred_username", "")
        if signed_in_username.casefold() != username.casefold():
            raise OutlookSignInError("Sign in with the Outlook address configured for CCGeek.")

    save_cache(cache)

    return result["access_token"]
