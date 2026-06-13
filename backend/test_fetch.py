"""
Standalone script: run the fetcher twice against real boards and report row counts.
Run from the backend/ directory:  python test_fetch.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.database import Base, SessionLocal, engine
from app.models import Company, Job
from app.fetch_service import run_fetch


def _seed():
    import yaml
    yaml_path = Path(__file__).parent.parent / "companies.yaml"
    if not yaml_path.exists():
        print("companies.yaml not found")
        return
    with open(yaml_path) as f:
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
    finally:
        db.close()


def _print_counts(db):
    total = db.query(Job).count()
    by_source: dict[str, int] = {}
    for company in db.query(Company).all():
        count = db.query(Job).filter_by(company_id=company.id).count()
        if count:
            label = f"{company.name} ({company.source})"
            by_source[label] = count
    print(f"  Total job rows: {total}")
    for label, n in sorted(by_source.items()):
        print(f"    {label}: {n}")
    return total


async def main():
    Base.metadata.create_all(bind=engine)
    _seed()

    db = SessionLocal()
    try:
        print("\n=== Run 1 ===")
        results1 = await run_fetch(db)
        print("\nPer-company results:")
        for name, r in results1.items():
            print(f"  {name}: {r}")
        count1 = _print_counts(db)

        print("\n=== Run 2 (dedupe check) ===")
        results2 = await run_fetch(db)
        print("\nPer-company results:")
        for name, r in results2.items():
            print(f"  {name}: {r}")
        count2 = _print_counts(db)

        print(f"\n{'='*40}")
        print(f"Run 1 total rows : {count1}")
        print(f"Run 2 total rows : {count2}")
        print(f"Dedupe : {'PASS — no new rows' if count1 == count2 else 'FAIL — row count changed'}")
        run2_new = sum(r.get("new", 0) for r in results2.values())
        print(f"Run 2 new inserts: {run2_new} (should be 0)")
    finally:
        db.close()


asyncio.run(main())
