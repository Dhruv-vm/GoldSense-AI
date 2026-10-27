from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.auth import get_current_user
from app.services.alert_service import AlertService

router = APIRouter(prefix="/api/alerts", tags=["Alerts"])


class AlertCreateSchema(BaseModel):
    alert_type: str = Field(description="'PRICE_ABOVE', 'PRICE_BELOW', 'PREMIUM_ABOVE', 'DAILY_CHANGE_PCT'")
    target_metric: str = Field(default="KJPL_GOLD")
    threshold: float
    notes: str | None = None


@router.get("")
def list_alerts(current_user: str = Depends(get_current_user)):
    return AlertService.list_alerts(user_id=current_user)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_alert(
    payload: AlertCreateSchema,
    current_user: str = Depends(get_current_user),
):
    return AlertService.create_alert(payload.model_dump(), user_id=current_user)


@router.delete("/{alert_id}")
def delete_alert(
    alert_id: int,
    current_user: str = Depends(get_current_user),
):
    success = AlertService.delete_alert(alert_id, user_id=current_user)
    if not success:
        raise HTTPException(status_code=404, detail="Alert rule not found.")
    return {"status": "SUCCESS", "message": f"Alert rule {alert_id} deleted."}


@router.get("/evaluate")
def evaluate_alerts(current_user: str = Depends(get_current_user)):
    return AlertService.evaluate_alerts(user_id=current_user)
