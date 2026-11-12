from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

_TEMP_DB_DIR = Path(tempfile.mkdtemp(prefix="vmd_pytest_")).resolve()
_TEMP_DB_PATH = (_TEMP_DB_DIR / "vmd_pytest.db").resolve()
_REAL_DATA_DIR = (REPO_ROOT / "data").resolve()

if _REAL_DATA_DIR in _TEMP_DB_PATH.parents:
    raise RuntimeError(f"Test database path '{_TEMP_DB_PATH}' must not reside inside '{_REAL_DATA_DIR}'.")

# Unconditionally override environment BEFORE any app.* module is imported.
os.environ["ENVIRONMENT"] = "test"
os.environ["GOLDSENSE_SQLITE_PATH"] = str(_TEMP_DB_PATH)
os.environ["DATABASE_URL"] = f"sqlite:///{_TEMP_DB_PATH}"
os.environ.pop("MIGRATION_DATABASE_URL", None)


def _init_temp_schema() -> None:
    prev_mig = os.environ.get("MIGRATION_DATABASE_URL")
    os.environ["MIGRATION_DATABASE_URL"] = f"sqlite:///{_TEMP_DB_PATH}"
    try:
        alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        alembic_cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
        alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{_TEMP_DB_PATH}")
        command.upgrade(alembic_cfg, "head")
    finally:
        if prev_mig is None:
            os.environ.pop("MIGRATION_DATABASE_URL", None)
        else:
            os.environ["MIGRATION_DATABASE_URL"] = prev_mig


_init_temp_schema()


def _cleanup_temp_db() -> None:
    try:
        import app.db.session as db_session

        db_session.engine.dispose()
    except Exception:
        pass
    shutil.rmtree(_TEMP_DB_DIR, ignore_errors=True)


atexit.register(_cleanup_temp_db)
