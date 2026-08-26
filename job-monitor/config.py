"""Environment-backed configuration for the ATS monitor."""

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def _int(name: str, default: int, minimum: int = 1) -> int:
    value = int(os.getenv(name, str(default)))
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def _path(name: str, default: str) -> Path:
    value = Path(os.getenv(name, default)).expanduser()
    return value if value.is_absolute() else (BASE_DIR / value).resolve()


@dataclass(frozen=True)
class Settings:
    webhook_url: str
    companies_json: Path
    database_path: Path
    high_priority_interval_minutes: int
    normal_priority_interval_minutes: int
    scheduler_wake_seconds: int
    max_workers: int
    send_existing_on_first_run: bool
    request_timeout_seconds: int


def load_settings() -> Settings:
    load_dotenv(BASE_DIR / ".env")
    return Settings(
        webhook_url=os.getenv("DISCORD_WEBHOOK_URL", "").strip(),
        companies_json=_path("COMPANIES_JSON", "../companies.json"),
        database_path=_path("DATABASE_PATH", "jobs.db"),
        high_priority_interval_minutes=_int("HIGH_PRIORITY_INTERVAL_MINUTES", 5),
        normal_priority_interval_minutes=_int("NORMAL_PRIORITY_INTERVAL_MINUTES", 30),
        scheduler_wake_seconds=_int("SCHEDULER_WAKE_SECONDS", 60),
        max_workers=_int("MAX_WORKERS", 8),
        send_existing_on_first_run=_bool("SEND_EXISTING_ON_FIRST_RUN", False),
        request_timeout_seconds=_int("REQUEST_TIMEOUT_SECONDS", 15),
    )
