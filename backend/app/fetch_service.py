import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .fetchers.ashby import AshbyFetcher
from .fetchers.greenhouse import GreenhouseFetcher
from .fetchers.lever import LeverFetcher
from .models import Company, Job

log = logging.getLogger(__name__)

_FETCHERS = {
    "greenhouse": GreenhouseFetcher(),
    "lever": LeverFetcher(),
    "ashby": AshbyFetcher(),
}


async def _fetch_company(db: Session, company: Company) -> dict:
    fetcher = _FETCHERS.get(company.source)
    if fetcher is None:
        log.warning("No fetcher for source '%s', skipping %s", company.source, company.name)
        return {"found": 0, "new": 0, "archived": 0}

    try:
        jobs = await fetcher.fetch(company.board_token)
    except Exception as exc:
        log.error("Fetch failed for %s (%s): %s", company.name, company.source, exc)
        return {"found": 0, "new": 0, "archived": 0, "error": str(exc)}

    now = datetime.now(timezone.utc)
    fetched_ids: set[str] = set()
    new_count = 0

    for job in jobs:
        fetched_ids.add(job.external_id)
        existing = (
            db.query(Job)
            .filter_by(company_id=company.id, external_id=job.external_id)
            .first()
        )
        if existing:
            existing.fetched_at = now
            if existing.status == "archived":
                existing.status = "new"
        else:
            db.add(Job(
                company_id=company.id,
                external_id=job.external_id,
                title=job.title,
                location=job.location,
                remote=job.remote,
                description=job.description,
                url=job.url,
                posted_at=job.posted_at,
                fetched_at=now,
                status="new",
            ))
            new_count += 1

    # Archive jobs that are no longer on the board
    active_jobs = (
        db.query(Job)
        .filter(Job.company_id == company.id, Job.status != "archived")
        .all()
    )
    archived_count = sum(
        1 for j in active_jobs
        if j.external_id not in fetched_ids
        and not _set_archived(j)
    )

    db.commit()

    result = {"found": len(jobs), "new": new_count, "archived": archived_count}
    log.info(
        "%s (%s): found=%d new=%d archived=%d",
        company.name, company.source,
        result["found"], result["new"], result["archived"],
    )
    return result


def _set_archived(job: Job) -> bool:
    """Set job status to archived. Returns False so it counts in sum(...)."""
    job.status = "archived"
    return False


async def run_fetch(db: Session) -> dict[str, dict]:
    """Fetch all companies, rate-limited at 1 req/s per source."""
    companies: list[Company] = db.query(Company).all()

    by_source: dict[str, list[Company]] = {}
    for c in companies:
        by_source.setdefault(c.source, []).append(c)

    results: dict[str, dict] = {}
    for source, comps in by_source.items():
        for i, company in enumerate(comps):
            if i > 0:
                await asyncio.sleep(1)
            results[company.name] = await _fetch_company(db, company)

    return results
