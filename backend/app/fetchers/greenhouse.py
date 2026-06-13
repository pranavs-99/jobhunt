import logging
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup

from .base import NormalizedJob, get_json

log = logging.getLogger(__name__)

_BASE = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"


class GreenhouseFetcher:
    async def fetch(self, board_token: str) -> list[NormalizedJob]:
        url = _BASE.format(token=board_token)
        async with httpx.AsyncClient(timeout=30) as client:
            data = await get_json(client, url)

        jobs: list[NormalizedJob] = []
        for raw in data.get("jobs", []):
            description: str | None = None
            if raw.get("content"):
                description = BeautifulSoup(raw["content"], "html.parser").get_text("\n")

            loc_obj = raw.get("location") or {}
            location: str | None = loc_obj.get("name") if isinstance(loc_obj, dict) else None
            remote: bool | None = ("remote" in location.lower()) if location else None

            posted_at: datetime | None = None
            if raw.get("updated_at"):
                posted_at = datetime.fromisoformat(
                    raw["updated_at"].replace("Z", "+00:00")
                )

            jobs.append(NormalizedJob(
                external_id=str(raw["id"]),
                title=raw["title"],
                url=raw["absolute_url"],
                location=location,
                remote=remote,
                description=description,
                posted_at=posted_at,
            ))

        return jobs
