from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Generator
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_DEFAULT_DB_PATH = (REPO_ROOT / "data" / "goldsense.db").resolve()
DEFAULT_DB_DIR = Path("data")
SQLITE_PATH = Path(os.environ.get("GOLDSENSE_SQLITE_PATH", str(DEFAULT_DB_DIR / "goldsense.db")))
if os.environ.get("ENVIRONMENT", "development").lower() != "test":
    SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
SQLITE_URL = f"sqlite:///{SQLITE_PATH.resolve()}"

DATABASE_URL = os.environ.get("DATABASE_URL")
ENVIRONMENT = os.environ.get("ENVIRONMENT", "development").lower()
USE_NULLPOOL = os.environ.get("DB_USE_NULLPOOL", "false").lower() in ("true", "1", "yes")
IS_POSTGRES = bool(DATABASE_URL and not str(DATABASE_URL).strip().lower().startswith("sqlite"))


def normalize_database_url(url: str | None) -> str | None:
    """
    Normalize postgres:// and postgresql:// URIs to use psycopg v3 driver.
    Ensures Neon PostgreSQL endpoints default to sslmode=require if unspecified.
    """
    if not url:
        return None
    cleaned = url.strip()
    if cleaned.startswith("postgres://"):
        cleaned = cleaned.replace("postgres://", "postgresql+psycopg://", 1)
    elif cleaned.startswith("postgresql://") and not cleaned.startswith("postgresql+"):
        cleaned = cleaned.replace("postgresql://", "postgresql+psycopg://", 1)

    if cleaned.startswith("postgresql+psycopg://"):
        parsed = urlparse(cleaned)
        qs = parse_qs(parsed.query)
        # Neon Free Tier requires TLS; default to sslmode=require when connecting to Neon or cloud Postgres
        if "sslmode" not in qs and parsed.hostname and "localhost" not in parsed.hostname and "127.0.0.1" not in parsed.hostname:
            qs["sslmode"] = ["require"]
            new_query = urlencode(qs, doseq=True)
            cleaned = urlunparse(parsed._replace(query=new_query))
    return cleaned


def _validate_test_sqlite_target(sqlite_target: str) -> None:
    """Reject non-temporary SQLite paths or the repository's real data/goldsense.db when ENVIRONMENT=test."""
    raw = sqlite_target.split("?", 1)[0]
    if raw in {"sqlite://", "sqlite:///:memory:"} or raw.endswith(":memory:"):
        return
    if raw.startswith("sqlite:///"):
        file_part = raw[len("sqlite:///"):]
    elif raw.startswith("sqlite://"):
        file_part = raw[len("sqlite://"):]
    else:
        file_part = raw

    resolved = Path(file_part).resolve()
    cwd_real_db = Path("data/goldsense.db").resolve()
    if resolved == REAL_DEFAULT_DB_PATH or resolved == cwd_real_db or resolved.parent == REAL_DEFAULT_DB_PATH.parent:
        raise RuntimeError(
            f"[TEST ISOLATION ERROR] Refusing to open repository database '{resolved}' when ENVIRONMENT=test."
        )

    temp_roots = (Path(tempfile.gettempdir()).resolve(), Path("/tmp").resolve())
    if not any(root == resolved or root in resolved.parents for root in temp_roots):
        raise RuntimeError(
            f"[TEST ISOLATION ERROR] Non-temporary SQLite database path '{resolved}' is prohibited when ENVIRONMENT=test."
        )


def build_engine(
    url: str | None = None,
    *,
    use_nullpool: bool | None = None,
    environment: str | None = None,
) -> Engine:
    """Create a configured SQLAlchemy Engine for Neon PostgreSQL or SQLite."""
    target_env = (environment or ENVIRONMENT).lower()
    raw_url = url if url is not None else DATABASE_URL
    norm_url = normalize_database_url(raw_url)
    nullpool_mode = USE_NULLPOOL if use_nullpool is None else use_nullpool

    if norm_url and not norm_url.startswith("sqlite"):
        kwargs: dict = {
            "pool_pre_ping": True,
            "connect_args": {"connect_timeout": 10},
        }
        if nullpool_mode:
            kwargs["poolclass"] = NullPool
        else:
            kwargs["pool_size"] = int(os.environ.get("DB_POOL_SIZE", "5"))
            kwargs["max_overflow"] = int(os.environ.get("DB_MAX_OVERFLOW", "5"))
            kwargs["pool_recycle"] = int(os.environ.get("DB_POOL_RECYCLE", "300"))

        try:
            candidate_engine = create_engine(norm_url, **kwargs)
            with candidate_engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return candidate_engine
        except Exception as exc:
            # F-11: PostgreSQL failure must fail closed in ALL environments when PostgreSQL
            # is configured — never silently degrade to local SQLite.
            raise RuntimeError(
                f"[DATABASE ERROR] Failed to connect to configured PostgreSQL database "
                f"(environment={target_env}). Silent SQLite fallback is prohibited."
            ) from exc

    elif target_env == "production" or os.environ.get("REQUIRE_POSTGRES", "false").lower() in ("true", "1", "yes"):
        raise RuntimeError(
            "[DATABASE ERROR] PostgreSQL DATABASE_URL is required (production / REQUIRE_POSTGRES=true). "
            "SQLite fallback is prohibited."
        )

    # Explicit local development / isolated testing SQLite engine (only when DATABASE_URL is unset or sqlite://)
    sqlite_target = norm_url if (norm_url and norm_url.startswith("sqlite")) else SQLITE_URL
    if target_env == "test":
        _validate_test_sqlite_target(sqlite_target)
    return create_engine(
        sqlite_target,
        connect_args={"check_same_thread": False},
    )


def is_postgres_configured(url: str | None = None) -> bool:
    raw = url if url is not None else os.environ.get("DATABASE_URL")
    return bool(raw and not str(raw).strip().lower().startswith("sqlite"))


engine: Engine = build_engine()

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a bounded database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_database_health() -> dict[str, object]:
    """Probe live database connectivity and report dialect/pool status without swallowing failures."""
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        return {
            "connected": True,
            "dialect": engine.dialect.name,
            "is_postgres": engine.dialect.name == "postgresql",
            "environment": ENVIRONMENT,
        }
    except Exception as exc:
        return {
            "connected": False,
            "dialect": engine.dialect.name,
            "is_postgres": engine.dialect.name == "postgresql",
            "environment": ENVIRONMENT,
            "error": str(exc),
        }
    finally:
        db.close()
