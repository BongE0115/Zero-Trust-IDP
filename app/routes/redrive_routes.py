from fastapi import APIRouter

from app.services.redrive_service import RedriveService

router = APIRouter()


@router.post("/redrive")
def redrive(limit: int = 50):
    service = RedriveService()
    count = service.redrive(limit)

    return {
        "status": "success",
        "reprocessed": count
    }