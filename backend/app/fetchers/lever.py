import logging
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup

from .base import NormalizedJob, get_json

log = logging.getLogger(__name__)

_BASE = "https://api.lever.co/v0/postings/{token}?mode=json"


class LeverFetcher:
    async def fetch(self, board_token: str) -> list[NormalizedJob]:
        url = _BASE.format(token=board_token)
        async with httpx.AsyncClient(timeout=30) as client:
            data = await get_json(client, url)

        jobs: list[NormalizedJob] = []
        for raw in data:
            html = (raw.get("description") or "") + (raw.get("additional") or "")
            description: str | None = (
                BeautifulSoup(html, "html.parser").get_text("\n") if html else None
            )

            cats = raw.get("categories") or {}
            location: str | None = cats.get("location") if isinstance(cats, dict) else None
            remote: bool | None = ("remote" in location.lower()) if location else None

            posted_at: datetime | None = None
            if raw.get("createdAt"):
                posted_at = datetime.fromtimestamp(raw["createdAt"] / 1000, tz=timezone.utc)

            jobs.append(NormalizedJob(
                external_id=raw["id"],
                title=raw["text"],
                url=raw["hostedUrl"],
                location=location,
                remote=remote,
                description=description,
                posted_at=posted_at,
            ))

        return jobs
