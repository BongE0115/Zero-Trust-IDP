from fastapi import APIRouter, HTTPException

from app.services.redrive_service import RedriveService

router = APIRouter()


@router.post("/redrive")
def redrive(limit: int = 50):
    try:
        service = RedriveService()
        result = service.redrive(limit)

        return {
            "status": "success",
            "reprocessed": result.get("reprocessed", 0),
            "success": result.get("success", 0),
            "failed": result.get("failed", 0)
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Redrive failed: {str(e)}"
        )