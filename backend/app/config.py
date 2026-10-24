from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"


class Settings(BaseSettings):
    # Resolved from this file, not the cwd, so tests and dev.py read the same .env.
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    base_currency: str = "INR"
    starting_cash: Decimal = Decimal("1000000")  # Rs 10,00,000
    market_data_provider: Literal["yahoo", "fake"] = "yahoo"
    quote_cache_ttl_seconds: int = 30
    bars_cache_ttl_seconds: int = 300
    # Company ratios move with quarterly filings, not ticks, so 15 minutes is plenty.
    fundamentals_cache_ttl_seconds: int = 900
    run_migrations: bool = True
    # The 60-second loop that fills limit orders. Tests switch it off.
    background_jobs: bool = True
    # Set true behind HTTPS so the session cookie is never sent over plain HTTP.
    cookie_secure: bool = False
    database_url: str = f"sqlite:///{(DATA_DIR / 'app.db').as_posix()}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
