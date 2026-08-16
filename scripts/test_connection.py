import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.async_database_url)


async def main():
    async with engine.begin() as conn:
        result = await conn.execute(text("SELECT version()"))

        print(result.scalar())


asyncio.run(main())
