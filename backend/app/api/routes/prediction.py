from fastapi import APIRouter

from app.services.prediction.predictor import predict

router = APIRouter(
    prefix="/api/predictions",
    tags=["predictions"],
)


@router.get("/latest")
def latest_prediction():
    return predict()
