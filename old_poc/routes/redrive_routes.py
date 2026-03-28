from fastapi import APIRouter, HTTPException
import logging
from app.services.redrive_service import RedriveService

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/redrive")
def redrive(limit: int = 50):
    """
    DLQ에 쌓인 데이터를 다시 메인 토픽으로 전송(Redrive)합니다.
    limit: 한 번에 처리할 메시지 수
    """
    try:
        logger.info(f"🔄 Redrive requested (limit: {limit})")
        
        service = RedriveService()
        result = service.redrive(limit)

        # 결과 리턴 (성공/실패 수치 포함)
        return {
            "status": "success",
            "reprocessed": result.get("reprocessed", 0),
            "success": result.get("success", 0),
            "failed": result.get("failed", 0)
        }

    except Exception as e:
        logger.error(f"❌ Redrive operation failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Redrive failed: {str(e)}"
        )