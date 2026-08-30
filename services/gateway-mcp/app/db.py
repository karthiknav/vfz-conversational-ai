import asyncio
import os
from urllib.parse import quote

import asyncpg

_pool: asyncpg.Pool | None = None
_pool_lock = asyncio.Lock()

DSN = (
    f"postgresql://{quote(os.environ['POSTGRES_USER'], safe='')}:{quote(os.environ['POSTGRES_PASSWORD'], safe='')}"
    f"@{os.environ['POSTGRES_HOST']}:{os.environ['POSTGRES_PORT']}/{os.environ['POSTGRES_DB']}"
)


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        async with _pool_lock:
            if _pool is None:
                _pool = await asyncpg.create_pool(DSN, min_size=1, max_size=10)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
