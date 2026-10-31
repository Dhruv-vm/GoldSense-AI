import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DEFAULT_DB_DIR = Path("data")
DEFAULT_DB_DIR.mkdir(parents=True, exist_ok=True)
SQLITE_URL = f"sqlite:///{DEFAULT_DB_DIR.resolve()}/goldsense.db"

DATABASE_URL = os.environ.get("DATABASE_URL")
ENVIRONMENT = os.environ.get("ENVIRONMENT", "development").lower()
IS_POSTGRES = bool(DATABASE_URL and not str(DATABASE_URL).startswith("sqlite"))


def normalize_database_url(url: str | None) -> str | None:
    """Normalize postgres:// and postgresql:// URIs to use psycopg v3 driver."""
    if not url:
        return None
    url = url.strip()
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://") and not url.startswith("postgresql+"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


engine = None
normalized_url = normalize_database_url(DATABASE_URL)
if normalized_url and not normalized_url.startswith("sqlite"):
    try:
        candidate_engine = create_engine(normalized_url, pool_pre_ping=True)
        with candidate_engine.connect():
            engine = candidate_engine
    except Exception as exc:
        if ENVIRONMENT == "production" and os.environ.get("RENDER"):
            raise RuntimeError(
                f"[DATABASE ERROR] In production environment, failed to connect to specified "
                f"DATABASE_URL (Supabase PostgreSQL): {exc}. Production must never silently fall back to local SQLite."
            ) from exc
        engine = None
elif ENVIRONMENT == "production" and os.environ.get("RENDER"):
    raise RuntimeError(
        "[DATABASE ERROR] In production environment, DATABASE_URL must be configured with a valid "
        "Supabase PostgreSQL connection string. Production must never fall back to local SQLite."
    )

if engine is None:
    # Resilient fallback: SQLite database for local and testing operations
    engine = create_engine(
        SQLITE_URL,
        connect_args={"check_same_thread": False},
    )

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)
