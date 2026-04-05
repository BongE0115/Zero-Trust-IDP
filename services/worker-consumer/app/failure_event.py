from datetime import datetime, timezone
import hashlib
import json
import os
from typing import Any, Dict
from runtime_context import settings


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def payload_hash(payload: Dict[str, Any]) -> str:
    raw = stable_json_dumps(payload).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def sanitize_case_id(case_id: str) -> str:
    return "".join(c if c.isalnum() or c == "-" else "-" for c in case_id).lower()


def build_case_id(payload: Dict[str, Any]) -> str:
    order_id = str(payload.get("order_id", "unknown-order"))
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    digest = payload_hash(payload)[:8]
    
    raw_id = f"{settings.SERVICE_NAME}-{order_id}-{ts}-{digest}"
    
    return raw_id[:63].rstrip("-")


def load_normal_fixture() -> Dict[str, Any]:
    if not settings.NORMAL_FIXTURE_PATH:
        return {}

    if not os.path.exists(settings.NORMAL_FIXTURE_PATH):
        print(f"[WARN] NORMAL_FIXTURE_PATH not found: {settings.NORMAL_FIXTURE_PATH}")
        return {}

    try:
        with open(settings.NORMAL_FIXTURE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[WARN] failed to load normal fixture: {e}")
        return {}


def build_failure_event(payload: Dict[str, Any], error: Exception) -> Dict[str, Any]:
    case_id = build_case_id(payload)
    replay_topic = f"orders-replay-{sanitize_case_id(case_id)}"
    normal_fixture = load_normal_fixture()

    return {
        "event_type": "consumer_failure",
        "case_id": case_id,
        "detected_at": utc_now_iso(),
        "source": {
            "service": settings.SERVICE_NAME,
            "namespace": settings.NAMESPACE,
            "deployment": settings.DEPLOYMENT_NAME,
            "topic": settings.SOURCE_TOPIC,
            "consumer_group": settings.GROUP_ID
        },
        "runtime": {
            "image_ref": settings.IMAGE_REF,
            "config_version": settings.CONFIG_VERSION,
            "dependency_profile": settings.DEPENDENCY_PROFILE
        },
        "repro_config": {
            "force_fail_field": settings.FORCE_FAIL_FIELD,
            "db_mode": settings.DB_MODE,
            "db_host": settings.DB_HOST,
            "cache_mode": settings.CACHE_MODE,
            "cache_host": settings.CACHE_HOST,
            "external_api_mode": settings.EXTERNAL_API_MODE,
            "external_api_base_url": settings.EXTERNAL_API_BASE_URL
        },
        "replay": {
            "target_topic": replay_topic,
            "failure_payload_hash": payload_hash(payload)
        },
        "validation": {
            "normal_fixture_available": bool(normal_fixture),
            "normal_fixture_path": settings.NORMAL_FIXTURE_PATH,
            "normal_payload_hash": payload_hash(normal_fixture) if normal_fixture else ""
        },
        "error": {
            "type": error.__class__.__name__,
            "message": str(error)
        },
        "original_payload": payload,
        "normal_validation_payload": normal_fixture,
    }