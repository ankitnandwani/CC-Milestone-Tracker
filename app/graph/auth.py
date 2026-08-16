from pathlib import Path

from msal import PublicClientApplication, SerializableTokenCache
from platformdirs import user_data_dir

from app.core.config import get_settings

settings = get_settings()

GRAPH_SCOPES: list[str] = [
    "User.Read",
    "Mail.Read",
]

CACHE_PATH = Path(user_data_dir("CCGeek")) / "token_cache.bin"


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
    )

    return app, cache


def authenticate() -> str:
    app, cache = create_app()

    accounts = app.get_accounts()

    if accounts:
        result = app.acquire_token_silent(
            GRAPH_SCOPES,
            account=accounts[0],
        )

        if result and "access_token" in result:
            save_cache(cache)
            return result["access_token"]

    result = app.acquire_token_interactive(
        GRAPH_SCOPES,
        port=8765,
    )

    if "access_token" not in result:
        raise RuntimeError(result.get("error_description"))

    save_cache(cache)

    return result["access_token"]
