from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Query

from app.services.bullion_service import (
    get_data_monitor_status,
    get_collector_runs_history,
)

router = APIRouter(prefix="/api/data-monitor", tags=["Data Monitor"])


@router.get("/status")
def get_monitor_status() -> dict[str, Any]:
    """
    Get live health and operational status of all data pipelines, database engines,
    and 5-city freshness metrics.
    """
    return get_data_monitor_status()


@router.get("/collectors")
def get_collector_runs(
    limit: int = Query(50, ge=1, le=200, description="Max collector run logs to return"),
) -> list[dict[str, Any]]:
    """
    Retrieve historical collector execution records, execution duration, and record deltas.
    """
    return get_collector_runs_history(limit=limit)
