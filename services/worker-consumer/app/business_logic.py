from typing import Dict, Any
from runtime_context import settings

def process_order(payload: Dict[str, Any]) -> None:

    fail_flag = payload.get(settings.FORCE_FAIL_FIELD)
    
    if str(fail_flag).lower() == "true":
        raise ValueError("intentional failure for POC")

    return