from __future__ import annotations

import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_DATA_DIR = (REPO_ROOT / "data").resolve()
REAL_DEFAULT_DB_PATH = (REAL_DATA_DIR / "goldsense.db").resolve()


def ensure_disposable_audit_db() -> str:
    """Fail-closed guard requiring an explicit disposable DATABASE_URL for standalone audit scripts."""
    env_mode = os.environ.get("ENVIRONMENT", "").strip().lower()
    if env_mode == "production":
        raise RuntimeError(
            "[AUDIT DB GUARD] Refusing to run standalone audit script with ENVIRONMENT=production."
        )

    raw_url = os.environ.get("DATABASE_URL", "").strip()
    if not raw_url:
        raise RuntimeError(
            "[AUDIT DB GUARD] DATABASE_URL is required for standalone audit scripts "
            "(e.g. sqlite:////tmp/audit.db or local localhost PostgreSQL test DSN). "
            "Silent fallback to data/goldsense.db is prohibited."
        )

    lowered = raw_url.lower()
    if lowered.startswith("sqlite"):
        path_part = raw_url.split("?", 1)[0]
        if path_part not in {"sqlite://", "sqlite:///:memory:"} and not path_part.endswith(":memory:"):
            if path_part.startswith("sqlite:///"):
                file_part = path_part[len("sqlite:///"):]
            elif path_part.startswith("sqlite://"):
                file_part = path_part[len("sqlite://"):]
            else:
                file_part = path_part
            resolved = Path(file_part).resolve()
            if resolved == REAL_DEFAULT_DB_PATH or REAL_DATA_DIR == resolved.parent or REAL_DATA_DIR in resolved.parents:
                raise RuntimeError(
                    f"[AUDIT DB GUARD] Refusing to open repository database '{resolved}'."
                )
            temp_roots = (Path(tempfile.gettempdir()).resolve(), Path("/tmp").resolve())
            if not any(root == resolved or root in resolved.parents for root in temp_roots):
                raise RuntimeError(
                    f"[AUDIT DB GUARD] SQLite audit DATABASE_URL must reside in a temporary directory, got '{resolved}'."
                )
    else:
        parsed = urlparse(raw_url)
        host = (parsed.hostname or "").lower()
        if "neon.tech" in host or host not in {"localhost", "127.0.0.1", "::1"}:
            raise RuntimeError(
                f"[AUDIT DB GUARD] Refusing non-local PostgreSQL host '{host}' in standalone audit script."
            )

    os.environ["ENVIRONMENT"] = "test"
    return raw_url
