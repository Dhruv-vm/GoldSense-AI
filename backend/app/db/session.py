import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DEFAULT_DB_DIR = Path("data")
DEFAULT_DB_DIR.mkdir(parents=True, exist_ok=True)
SQLITE_URL = f"sqlite:///{DEFAULT_DB_DIR.resolve()}/goldsense.db"

DATABASE_URL = os.environ.get("DATABASE_URL")

engine = None
if DATABASE_URL and not DATABASE_URL.startswith("sqlite"):
    try:
        candidate_engine = create_engine(DATABASE_URL, pool_pre_ping=True)
        with candidate_engine.connect():
            engine = candidate_engine
    except Exception:
        engine = None

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
