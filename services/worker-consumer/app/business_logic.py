# 트리거 1
from typing import Dict, Any
from runtime_context import settings


def process_order(payload: Dict[str, Any]) -> None:
    """
    실제 비즈니스 로직이 들어갈 자리.
    지금은 기존 intentional failure POC 로직만 유지.
    """
    if payload.get(settings.FORCE_FAIL_FIELD) is True:
        raise ValueError("intentional failure for POC")

    # 여기에 실제 주문 처리 로직이 들어가면 됨.
    # 예:
    # - 주문 유효성 검사
    # - 재고 확인
    # - 결제 요청
    # - 주문 상태 저장
    return