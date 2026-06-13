import logging
import yaml
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import Base, SessionLocal, engine
from .fetch_service import run_fetch
from .models import Company

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

COMPANIES_YAML = Path(__file__).parent.parent.parent / "companies.yaml"

scheduler = AsyncIOScheduler()


def seed_companies():
    if not COMPANIES_YAML.exists():
        log.warning("companies.yaml not found, skipping seed")
        return
    with open(COMPANIES_YAML) as f:
        data = yaml.safe_load(f)
    db = SessionLocal()
    try:
        for entry in data.get("companies", []):
            exists = db.query(Company).filter_by(
                name=entry["name"], source=entry["source"]
            ).first()
            if not exists:
                db.add(Company(
                    name=entry["name"],
                    source=entry["source"],
                    board_token=entry.get("board_token"),
                    url=entry.get("url"),
                ))
        db.commit()
        log.info("Companies seeded from companies.yaml")
    finally:
        db.close()


async def _scheduled_fetch():
    db = SessionLocal()
    try:
        await run_fetch(db)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    seed_companies()
    scheduler.add_job(_scheduled_fetch, "interval", hours=24, id="daily_fetch")
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="Jobhunt API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/fetch")
async def trigger_fetch():
    db = SessionLocal()
    try:
        results = await run_fetch(db)
        totals = {
            "companies": len(results),
            "found": sum(r.get("found", 0) for r in results.values()),
            "new": sum(r.get("new", 0) for r in results.values()),
            "archived": sum(r.get("archived", 0) for r in results.values()),
        }
        return {"status": "ok", "totals": totals, "by_company": results}
    finally:
        db.close()
