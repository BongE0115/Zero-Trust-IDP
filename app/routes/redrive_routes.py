<<<<<<< HEAD
from fastapi import APIRouter, HTTPException
=======
from fastapi import APIRouter
>>>>>>> c56df95f91839c06e4d9c285fda960a4e249b796

from app.services.redrive_service import RedriveService

router = APIRouter()


@router.post("/redrive")
def redrive(limit: int = 50):
<<<<<<< HEAD
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
=======
    service = RedriveService()
    count = service.redrive(limit)

    return {
        "status": "success",
        "reprocessed": count
    }
>>>>>>> c56df95f91839c06e4d9c285fda960a4e249b796
