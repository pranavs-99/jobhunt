import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

import httpx

log = logging.getLogger(__name__)


@dataclass
class NormalizedJob:
    external_id: str
    title: str
    url: str
    location: str | None = None
    remote: bool | None = None
    description: str | None = None
    posted_at: datetime | None = None


async def get_json(client: httpx.AsyncClient, url: str) -> object:
    """GET with up to 3 retries on 429."""
    for attempt in range(3):
        resp = await client.get(url)
        if resp.status_code == 429:
            wait = 2 ** attempt
            log.warning("429 rate-limit at %s, retrying in %ss", url, wait)
            await asyncio.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()
    resp.raise_for_status()
