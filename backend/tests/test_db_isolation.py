from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

import pytest
from starlette.testclient import TestClient

import app.db.session as db_session
from app.main import app


def test_config_selects_temporary_database():
    """1. Test configuration selects a temporary database outside data/."""
    assert os.environ.get("ENVIRONMENT") == "test"
    db_url = os.environ.get("DATABASE_URL", "")
    sqlite_path = Path(os.environ.get("GOLDSENSE_SQLITE_PATH", "")).resolve()
    temp_roots = (Path(tempfile.gettempdir()).resolve(), Path("/tmp").resolve())
    assert db_url.startswith("sqlite:///")
    assert any(root in sqlite_path.parents for root in temp_roots)
    assert sqlite_path != db_session.REAL_DEFAULT_DB_PATH


def test_app_imports_do_not_bind_to_real_database():
    """2. Application imports do not bind engine to data/goldsense.db."""
    engine_db = Path(str(db_session.engine.url.database)).resolve()
    assert engine_db != db_session.REAL_DEFAULT_DB_PATH
    assert engine_db.parent != db_session.REAL_DEFAULT_DB_PATH.parent


def test_testclient_lifespan_cannot_initialize_real_database():
    """3. TestClient lifespan runs without modifying data/goldsense.db."""
    real_db = db_session.REAL_DEFAULT_DB_PATH
    before_sha = hashlib.sha256(real_db.read_bytes()).hexdigest() if real_db.exists() else None
    with TestClient(app) as client:
        res = client.get("/health")
        assert res.status_code == 200
    after_sha = hashlib.sha256(real_db.read_bytes()).hexdigest() if real_db.exists() else None
    assert before_sha == after_sha


def test_real_or_nontemp_database_rejected_in_test_environment(tmp_path: Path):
    """4. Attempts to configure data/goldsense.db or non-temp SQLite during tests fail."""
    real_db = db_session.REAL_DEFAULT_DB_PATH
    with pytest.raises(RuntimeError, match="TEST ISOLATION ERROR"):
        db_session.build_engine(url=f"sqlite:///{real_db}", environment="test")

    non_temp_db = db_session.REPO_ROOT / "backend" / "non_temp_test.db"
    with pytest.raises(RuntimeError, match="TEST ISOLATION ERROR"):
        db_session.build_engine(url=f"sqlite:///{non_temp_db}", environment="test")

    # Temporary SQLite paths under pytest tmp_path remain allowed
    allowed = db_session.build_engine(url=f"sqlite:///{tmp_path / 'allowed.db'}", environment="test")
    allowed.dispose()


def test_app_startup_works_with_isolated_test_database():
    """5. Existing application startup works with the isolated test database."""
    with TestClient(app) as client:
        res = client.get("/health")
        assert res.status_code == 200
        payload = res.json()
        assert payload["status"] == "ok"
        assert payload["database"]["connected"] is True
        assert payload["database"]["environment"] == "test"


def test_production_database_configuration_unchanged():
    """6. Production database configuration remains strict (no SQLite fallback)."""
    with pytest.raises(RuntimeError, match="SQLite fallback is prohibited"):
        db_session.build_engine(url="", environment="production")
