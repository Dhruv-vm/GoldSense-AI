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

engine = None
if DATABASE_URL and not DATABASE_URL.startswith("sqlite"):
    try:
        candidate_engine = create_engine(DATABASE_URL, pool_pre_ping=True)
        with candidate_engine.connect():
            engine = candidate_engine
    except Exception as exc:
        if ENVIRONMENT == "production":
            raise RuntimeError(
                f"[DATABASE ERROR] In production environment, failed to connect to specified "
                f"DATABASE_URL (Supabase PostgreSQL): {exc}. Production must never silently fall back to local SQLite."
            ) from exc
        engine = None
elif ENVIRONMENT == "production":
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
