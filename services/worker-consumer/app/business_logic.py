from typing import Dict, Any
from runtime_context import settings

def process_order(payload: Dict[str, Any]) -> None:
    """
    실제 비즈니스 로직이 들어갈 자리.
    지금은 기존 intentional failure POC 로직만 유지.
    """
    # 👇 어떤 데이터 타입(문자, 불리언, 대소문자)이 오든 
    # 무조건 소문자 문자열로 깎아서 'true'인지 검사하는 무적의 판독기
    fail_flag = payload.get(settings.FORCE_FAIL_FIELD)
    
    if str(fail_flag).lower() == "true":
        raise ValueError("intentional failure for POC")

    # 여기에 실제 주문 처리 로직이 들어가면 됨.
    # 예:
    # - 주문 유효성 검사
    # - 재고 확인
    # - 결제 요청
    # - 주문 상태 저장
    return