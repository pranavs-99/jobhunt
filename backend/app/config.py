import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    adzuna_app_id: str = os.getenv("ADZUNA_APP_ID", "")
    adzuna_app_key: str = os.getenv("ADZUNA_APP_KEY", "")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./jobhunt.db")

    adzuna_queries: list[str] = [
        "ux designer",
        "product designer",
        "interaction designer",
        "haptics designer",
        "spatial computing designer",
    ]

    score_weights: dict = {
        "skills_overlap": 0.45,
        "seniority_match": 0.25,
        "domain_match": 0.30,
    }


settings = Settings()
