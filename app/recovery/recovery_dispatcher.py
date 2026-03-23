from app.recovery.recovery_actions import (
    handle_cpu_recovery,
    handle_memory_recovery,
)

def dispatch_recovery(event: dict):
    # 🔥 테스트용: 일부러 실패 발생
    raise Exception("forced recovery failure for DLQ test")