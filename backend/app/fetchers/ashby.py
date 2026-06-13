import logging
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from .base import NormalizedJob, get_json

log = logging.getLogger(__name__)

_BASE = "https://api.ashbyhq.com/posting-api/job-board/{token}"


class AshbyFetcher:
    async def fetch(self, board_token: str) -> list[NormalizedJob]:
        url = _BASE.format(token=board_token)
        async with httpx.AsyncClient(timeout=30) as client:
            data = await get_json(client, url)

        jobs: list[NormalizedJob] = []
        for raw in data.get("jobPostings", []):
            description: str | None = None
            if raw.get("descriptionHtml"):
                description = BeautifulSoup(
                    raw["descriptionHtml"], "html.parser"
                ).get_text("\n")

            location: str | None = raw.get("locationName")
            remote: bool | None = raw.get("isRemote")

            posted_at: datetime | None = None
            if raw.get("publishedAt"):
                posted_at = datetime.fromisoformat(
                    raw["publishedAt"].replace("Z", "+00:00")
                )

            jobs.append(NormalizedJob(
                external_id=raw["id"],
                title=raw["title"],
                url=raw["jobUrl"],
                location=location,
                remote=remote,
                description=description,
                posted_at=posted_at,
            ))

        return jobs
