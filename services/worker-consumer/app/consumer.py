from kafka import KafkaConsumer, KafkaProducer
import json
import os
import time
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict


def getenv(name: str, default: str = "") -> str:
    return os.getenv(name, default)


KAFKA_BOOTSTRAP = getenv("KAFKA_BOOTSTRAP", "kafka.kafka-poc.svc.cluster.local:9092")
SOURCE_TOPIC = getenv("SOURCE_TOPIC", "orders")
DLQ_TOPIC = getenv("DLQ_TOPIC", "orders-dlq")
GROUP_ID = getenv("GROUP_ID", "orders-consumer-prod")

SERVICE_NAME = getenv("SERVICE_NAME", "worker-consumer")
NAMESPACE = getenv("NAMESPACE", "kafka-poc")
DEPLOYMENT_NAME = getenv("DEPLOYMENT_NAME", "worker-consumer")

IMAGE_REF = getenv("IMAGE_REF", "ghcr.io/bonge0115/worker-consumer:unset")
CONFIG_VERSION = getenv("CONFIG_VERSION", "v1")
DEPENDENCY_PROFILE = getenv("DEPENDENCY_PROFILE", "prod")

DB_MODE = getenv("DB_MODE", "mongo")
DB_HOST = getenv("DB_HOST", "")
CACHE_MODE = getenv("CACHE_MODE", "disabled")
CACHE_HOST = getenv("CACHE_HOST", "")
EXTERNAL_API_MODE = getenv("EXTERNAL_API_MODE", "disabled")
EXTERNAL_API_BASE_URL = getenv("EXTERNAL_API_BASE_URL", "")

FORCE_FAIL_FIELD = getenv("FORCE_FAIL_FIELD", "should_fail")
ENABLE_DLQ_PUBLISH = getenv("ENABLE_DLQ_PUBLISH", "true").lower() == "true"

NORMAL_FIXTURE_PATH = getenv("NORMAL_FIXTURE_PATH", "")

CASE_ID = getenv("CASE_ID", "")
RUN_MODE = getenv("RUN_MODE", "prod")
RESULT_TOPIC = getenv("RESULT_TOPIC", "")
EMIT_RESULT_EVENT = getenv("EMIT_RESULT_EVENT", "false").lower() == "true"
REPLAY_PAYLOAD_HASH = getenv("REPLAY_PAYLOAD_HASH", "")
NORMAL_PAYLOAD_HASH = getenv("NORMAL_PAYLOAD_HASH", "")
READY_FILE_PATH = getenv("READY_FILE_PATH", "")
ISOLATION_MODE = getenv("ISOLATION_MODE", "disabled")
ALLOWED_REPLAY_TOPIC = getenv("ALLOWED_REPLAY_TOPIC", "")
ALLOWED_RESULT_TOPIC = getenv("ALLOWED_RESULT_TOPIC", "")

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
    return f"{SERVICE_NAME}-{order_id}-{ts}-{digest}"


def load_normal_fixture() -> Dict[str, Any]:
    if not NORMAL_FIXTURE_PATH:
        return {}

    if not os.path.exists(NORMAL_FIXTURE_PATH):
        print(f"[WARN] NORMAL_FIXTURE_PATH not found: {NORMAL_FIXTURE_PATH}")
        return {}

    try:
        with open(NORMAL_FIXTURE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                print("[WARN] normal fixture must be a JSON object")
                return {}
            return data
    except Exception as e:
        print(f"[WARN] failed to load normal fixture: {e}")
        return {}


def get_producer():
    for _ in range(60):
        try:
            return KafkaProducer(
                bootstrap_servers=KAFKA_BOOTSTRAP,
                value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8")
            )
        except Exception as e:
            print(f"[WARN] Kafka producer init failed: {e}")
            time.sleep(2)
    raise RuntimeError("Kafka producer init failed")


def get_consumer():
    for _ in range(60):
        try:
            return KafkaConsumer(
                SOURCE_TOPIC,
                bootstrap_servers=KAFKA_BOOTSTRAP,
                group_id=GROUP_ID,
                auto_offset_reset="earliest",
                enable_auto_commit=True,
                value_deserializer=lambda m: json.loads(m.decode("utf-8"))
            )
        except Exception as e:
            print(f"[WARN] Kafka consumer init failed: {e}")
            time.sleep(2)
    raise RuntimeError("Kafka consumer init failed")


def build_failure_event(payload: Dict[str, Any], error: Exception) -> Dict[str, Any]:
    case_id = build_case_id(payload)
    replay_topic = f"orders-replay-{sanitize_case_id(case_id)}"

    normal_fixture = load_normal_fixture()

    return {
        "event_type": "consumer_failure",
        "case_id": case_id,
        "detected_at": utc_now_iso(),
        "source": {
            "service": SERVICE_NAME,
            "namespace": NAMESPACE,
            "deployment": DEPLOYMENT_NAME,
            "topic": SOURCE_TOPIC,
            "consumer_group": GROUP_ID
        },
        "runtime": {
            "image_ref": IMAGE_REF,
            "config_version": CONFIG_VERSION,
            "dependency_profile": DEPENDENCY_PROFILE
        },
        "repro_config": {
            "force_fail_field": FORCE_FAIL_FIELD,
            "db_mode": DB_MODE,
            "db_host": DB_HOST,
            "cache_mode": CACHE_MODE,
            "cache_host": CACHE_HOST,
            "external_api_mode": EXTERNAL_API_MODE,
            "external_api_base_url": EXTERNAL_API_BASE_URL
        },
        "replay": {
            "target_topic": replay_topic,
            "failure_payload_hash": payload_hash(payload)
        },
        "validation": {
            "normal_fixture_available": bool(normal_fixture),
            "normal_fixture_path": NORMAL_FIXTURE_PATH,
            "normal_payload_hash": payload_hash(normal_fixture) if normal_fixture else ""
        },
        "error": {
            "type": error.__class__.__name__,
            "message": str(error)
        },
        "original_payload": payload,
        "normal_validation_payload": normal_fixture,
    }


def detect_phase(current_payload: Dict[str, Any]) -> str:
    current_hash = payload_hash(current_payload)

    if REPLAY_PAYLOAD_HASH and current_hash == REPLAY_PAYLOAD_HASH:
        return "failure_replay"

    if NORMAL_PAYLOAD_HASH and current_hash == NORMAL_PAYLOAD_HASH:
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
        "case_id": CASE_ID,
        "phase": phase,
        "status": status,
        "payload_hash": payload_hash(current_payload),
        "order_id": current_payload.get("order_id", ""),
        "source_topic": SOURCE_TOPIC,
        "service": SERVICE_NAME,
        "namespace": NAMESPACE,
        "deployment": DEPLOYMENT_NAME,
        "image_ref": IMAGE_REF,
        "processed_at": utc_now_iso(),
    }

    if error is None:
        event["observed_error_type"] = ""
        event["observed_error_message"] = ""
    else:
        event["observed_error_type"] = error.__class__.__name__
        event["observed_error_message"] = str(error)

    return event


def emit_result_event(producer: KafkaProducer, event: Dict[str, Any]):
    if not EMIT_RESULT_EVENT:
        return
    if not RESULT_TOPIC:
        print("[WARN] EMIT_RESULT_EVENT=true but RESULT_TOPIC is empty")
        return

    producer.send(RESULT_TOPIC, event)
    producer.flush()
    print(f"[RESULT] published topic={RESULT_TOPIC} event={json.dumps(event, ensure_ascii=False)}")


def write_ready_file():
    if RUN_MODE != "sandbox":
        return
    if not READY_FILE_PATH:
        print("[WARN] RUN_MODE=sandbox but READY_FILE_PATH is empty")
        return

    ready_data = {
        "case_id": CASE_ID,
        "source_topic": SOURCE_TOPIC,
        "group_id": GROUP_ID,
        "service": SERVICE_NAME,
        "namespace": NAMESPACE,
        "deployment": DEPLOYMENT_NAME,
        "image_ref": IMAGE_REF,
        "ready_at": utc_now_iso(),
    }

    os.makedirs(os.path.dirname(READY_FILE_PATH), exist_ok=True)
    with open(READY_FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(ready_data, f, ensure_ascii=False, indent=2)

    print(f"[READY] ready file written path={READY_FILE_PATH} data={json.dumps(ready_data, ensure_ascii=False)}")

def validate_sandbox_isolation():
    if RUN_MODE != "sandbox":
        return

    if ISOLATION_MODE != "sandbox_strict":
        print(f"[WARN] sandbox run_mode but isolation mode is not strict: {ISOLATION_MODE}")
        return

    if not CASE_ID:
        raise ValueError("sandbox isolation requires CASE_ID")

    if not ALLOWED_REPLAY_TOPIC:
        raise ValueError("sandbox isolation requires ALLOWED_REPLAY_TOPIC")

    if not ALLOWED_RESULT_TOPIC:
        raise ValueError("sandbox isolation requires ALLOWED_RESULT_TOPIC")

    if SOURCE_TOPIC != ALLOWED_REPLAY_TOPIC:
        raise ValueError(
            f"sandbox SOURCE_TOPIC mismatch expected={ALLOWED_REPLAY_TOPIC} actual={SOURCE_TOPIC}"
        )

    if RESULT_TOPIC != ALLOWED_RESULT_TOPIC:
        raise ValueError(
            f"sandbox RESULT_TOPIC mismatch expected={ALLOWED_RESULT_TOPIC} actual={RESULT_TOPIC}"
        )

    if ENABLE_DLQ_PUBLISH:
        raise ValueError("sandbox isolation forbids ENABLE_DLQ_PUBLISH=true")

    print(
        f"[ISOLATION] consumer strict sandbox isolation validated "
        f"case_id={CASE_ID} replay_topic={ALLOWED_REPLAY_TOPIC} result_topic={ALLOWED_RESULT_TOPIC}"
    )

producer = get_producer()
consumer = get_consumer()
validate_sandbox_isolation()
write_ready_file()

print(
    f"[INFO] Consumer started topic={SOURCE_TOPIC}, dlq={DLQ_TOPIC}, "
    f"group={GROUP_ID}, image_ref={IMAGE_REF}, enable_dlq_publish={ENABLE_DLQ_PUBLISH}, "
    f"run_mode={RUN_MODE}, emit_result_event={EMIT_RESULT_EVENT}, result_topic={RESULT_TOPIC}, "
    f"ready_file_path={READY_FILE_PATH}, isolation_mode={ISOLATION_MODE}, "
    f"allowed_replay_topic={ALLOWED_REPLAY_TOPIC}, allowed_result_topic={ALLOWED_RESULT_TOPIC}"
)

for message in consumer:
    payload = message.value
    phase = detect_phase(payload)

    try:
        print(f"[INFO] Received: {payload}")

        if payload.get(FORCE_FAIL_FIELD) is True:
            raise ValueError("intentional failure for POC")

        print(f"[SUCCESS] processed order_id={payload.get('order_id')}")

        if RUN_MODE == "sandbox":
            emit_result_event(
                producer,
                build_result_event(
                    current_payload=payload,
                    phase=phase,
                    status="success",
                    error=None,
                ),
            )

    except Exception as e:
        if RUN_MODE == "sandbox":
            emit_result_event(
                producer,
                build_result_event(
                    current_payload=payload,
                    phase=phase,
                    status="failed",
                    error=e,
                ),
            )
            print("[INFO] sandbox mode: failure captured only in result topic")
            continue

        failure_event = build_failure_event(payload, e)
        print(f"[FAILURE] {json.dumps(failure_event, ensure_ascii=False)}")

        if ENABLE_DLQ_PUBLISH:
            producer.send(DLQ_TOPIC, failure_event)
            producer.flush()
            print(
                f"[DLQ] published to {DLQ_TOPIC} "
                f"case_id={failure_event['case_id']} "
                f"image_ref={failure_event['runtime']['image_ref']}"
            )
        else:
            print("[INFO] DLQ publish disabled, failure captured only")