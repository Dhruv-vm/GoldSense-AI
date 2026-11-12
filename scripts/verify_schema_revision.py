from __future__ import annotations

from pathlib import Path
import sys

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy import text

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.session import SessionLocal


def main() -> int:
    cfg = AlembicConfig(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    expected_heads = set(ScriptDirectory.from_config(cfg).get_heads())
    db = SessionLocal()
    try:
        rows = {str(r[0]) for r in db.execute(text("SELECT version_num FROM alembic_version")).fetchall()}
    finally:
        db.close()
    if rows != expected_heads:
        raise RuntimeError(f"Database revision mismatch: db={sorted(rows)} expected={sorted(expected_heads)}")
    print(f"[DB SCHEMA CHECK] Verified head revision: {sorted(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
