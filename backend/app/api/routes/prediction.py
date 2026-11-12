from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db, is_postgres_configured
from app.services.prediction.predictor import (
    get_mjdta_research_shadow_payload,
    predict,
)

router = APIRouter(
    prefix="/api/predictions",
    tags=["predictions"],
)


@router.get("/latest")
def latest_prediction(db: Session = Depends(get_db)):
    try:
        return predict(db=db)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/research-shadow")
def research_shadow_prediction(db: Session = Depends(get_db)):
    """
    MJDTA-only research output (`EXPERIMENT_PROTOCOL_V1`) separating the immutable
    PROSPECTIVE shadow ledger from the historical BACKTEST study. Fails closed if DB fails.
    """
    try:
        return get_mjdta_research_shadow_payload(db=db)
    except Exception as exc:
        if is_postgres_configured():
            raise HTTPException(status_code=503, detail=f"Research DB unavailable: {exc}") from exc
        raise HTTPException(status_code=500, detail=f"Research summary error: {exc}") from exc
