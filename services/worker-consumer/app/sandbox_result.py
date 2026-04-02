from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Dict
from kafka import KafkaProducer
from runtime_context import settings


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def payload_hash(payload: Dict[str, Any]) -> str:
    raw = stable_json_dumps(payload).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def detect_phase(current_payload: Dict[str, Any]) -> str:
    current_hash = payload_hash(current_payload)

    if settings.REPLAY_PAYLOAD_HASH and current_hash == settings.REPLAY_PAYLOAD_HASH:
        return "failure_replay"

    if settings.NORMAL_PAYLOAD_HASH and current_hash == settings.NORMAL_PAYLOAD_HASH:
        return "normal_validation"

    return "unknown"


def build_result_event(
    current_payload: Dict[str, Any],
    phase: str,
    status: str,
    error: Exception | None = None,
) -> Dict[str, Any]:
    event = {
        "event_type": "sandbox_result",
        "case_id": settings.CASE_ID,
        "phase": phase,
        "status": status,
        "payload_hash": payload_hash(current_payload),
        "order_id": current_payload.get("order_id", ""),
        "source_topic": settings.SOURCE_TOPIC,
        "service": settings.SERVICE_NAME,
        "namespace": settings.NAMESPACE,
        "deployment": settings.DEPLOYMENT_NAME,
        "image_ref": settings.IMAGE_REF,
        "processed_at": utc_now_iso(),
        "validation_mode": settings.VALIDATION_MODE,
        "validation_run_id": settings.VALIDATION_RUN_ID,
        "revalidation_generation": settings.REVALIDATION_GENERATION,
        "expected_failure_status": settings.EXPECTED_FAILURE_STATUS,
        "expected_normal_status": settings.EXPECTED_NORMAL_STATUS,
        "observed_error_type": "" if error is None else error.__class__.__name__,
        "observed_error_message": "" if error is None else str(error),
    }
    return event


def emit_result_event(producer: KafkaProducer, event: Dict[str, Any]):
    if not settings.EMIT_RESULT_EVENT:
        return
    if not settings.RESULT_TOPIC:
        print("[WARN] EMIT_RESULT_EVENT=true but RESULT_TOPIC is empty")
        return

    producer.send(settings.RESULT_TOPIC, event)
    producer.flush()
    print(f"[RESULT] published topic={settings.RESULT_TOPIC} event={json.dumps(event, ensure_ascii=False)}")