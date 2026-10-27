from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.auth import get_current_user
from app.services.portfolio_service import PortfolioService

router = APIRouter(prefix="/api/portfolio", tags=["Portfolio"])


class HoldingCreateSchema(BaseModel):
    metal_type: str = Field(description="'GOLD' or 'SILVER'")
    product_name: str = Field(min_length=1, max_length=150)
    purity: float = Field(default=0.999, gt=0.0, le=1.0)
    gross_weight: float = Field(gt=0.0)
    weight_unit: str = Field(default="g", description="'g' or 'kg'")
    quantity: int = Field(default=1, ge=1)
    acquisition_date: str | None = None
    acquisition_cost_inr: float | None = None
    notes: str | None = None


class HoldingUpdateSchema(BaseModel):
    metal_type: str | None = None
    product_name: str | None = None
    purity: float | None = None
    gross_weight: float | None = None
    weight_unit: str | None = None
    quantity: int | None = None
    acquisition_date: str | None = None
    acquisition_cost_inr: float | None = None
    notes: str | None = None


@router.get("/summary")
def get_portfolio_summary(current_user: str = Depends(get_current_user)):
    return PortfolioService.get_portfolio_summary(user_id=current_user)


@router.get("/holdings")
def list_holdings(current_user: str = Depends(get_current_user)):
    return PortfolioService.list_holdings(user_id=current_user)


@router.get("/history")
def get_portfolio_history(current_user: str = Depends(get_current_user)):
    return PortfolioService.get_historical_valuation(user_id=current_user)


@router.post("/holdings", status_code=status.HTTP_201_CREATED)
def create_holding(
    payload: HoldingCreateSchema,
    current_user: str = Depends(get_current_user),
):
    try:
        holding = PortfolioService.create_holding(payload.model_dump(), user_id=current_user)
        return holding
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/holdings/{holding_id}")
def update_holding(
    holding_id: int,
    payload: HoldingUpdateSchema,
    current_user: str = Depends(get_current_user),
):
    updated = PortfolioService.update_holding(holding_id, payload.model_dump(exclude_unset=True), user_id=current_user)
    if not updated:
        raise HTTPException(status_code=404, detail="Holding not found.")
    return updated


@router.delete("/holdings/{holding_id}")
def delete_holding(
    holding_id: int,
    current_user: str = Depends(get_current_user),
):
    success = PortfolioService.delete_holding(holding_id, user_id=current_user)
    if not success:
        raise HTTPException(status_code=404, detail="Holding not found.")
    return {"status": "SUCCESS", "message": f"Holding {holding_id} deleted."}
