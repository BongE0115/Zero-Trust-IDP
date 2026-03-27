from app.recovery.recovery_actions import (
    handle_cpu_recovery,
    handle_memory_recovery,
)


def dispatch_recovery(event: dict):
    payload = event.get("payload") or event.get("original_payload") or {}

    metric_name = payload.get("metric_name")

    if not metric_name:
        raise Exception("No metric_name in event")

    # 🔥 CPU
    if metric_name == "cpu_usage":
        return handle_cpu_recovery(event)

    # 🔥 Memory
    elif metric_name == "memory_usage":
        return handle_memory_recovery(event)

    else:
        raise Exception(f"No recovery handler for metric: {metric_name}")