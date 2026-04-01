from kafka import KafkaProducer, KafkaConsumer
import json
import os
import time

from runtime_context import settings
from business_logic import process_order
from failure_event import build_failure_event
from sandbox_result import detect_phase, build_result_event, emit_result_event


def get_producer():
    for _ in range(60):
        try:
            return KafkaProducer(
                bootstrap_servers=settings.KAFKA_BOOTSTRAP,
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
                settings.SOURCE_TOPIC,
                bootstrap_servers=settings.KAFKA_BOOTSTRAP,
                group_id=settings.GROUP_ID,
                auto_offset_reset="earliest",
                enable_auto_commit=True,
                value_deserializer=lambda m: json.loads(m.decode("utf-8"))
            )
        except Exception as e:
            print(f"[WARN] Kafka consumer init failed: {e}")
            time.sleep(2)
    raise RuntimeError("Kafka consumer init failed")


def utc_now_iso():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def write_ready_file():
    if settings.RUN_MODE != "sandbox":
        return
    if not settings.READY_FILE_PATH:
        raise ValueError("RUN_MODE=sandbox requires READY_FILE_PATH")

    ready_data = {
        "case_id": settings.CASE_ID,
        "source_topic": settings.SOURCE_TOPIC,
        "group_id": settings.GROUP_ID,
        "service": settings.SERVICE_NAME,
        "namespace": settings.NAMESPACE,
        "deployment": settings.DEPLOYMENT_NAME,
        "image_ref": settings.IMAGE_REF,
        "ready_at": utc_now_iso(),
        "validation_mode": settings.VALIDATION_MODE,
        "validation_run_id": settings.VALIDATION_RUN_ID,
        "revalidation_generation": settings.REVALIDATION_GENERATION,
    }

    os.makedirs(os.path.dirname(settings.READY_FILE_PATH), exist_ok=True)
    with open(settings.READY_FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(ready_data, f, ensure_ascii=False, indent=2)

    print(f"[READY] ready file written path={settings.READY_FILE_PATH}")


def validate_sandbox_isolation():
    if settings.RUN_MODE != "sandbox":
        return

    if settings.ISOLATION_MODE != "sandbox_strict":
        raise ValueError(f"sandbox requires sandbox_strict isolation but got: {settings.ISOLATION_MODE}")

    if not settings.CASE_ID:
        raise ValueError("sandbox isolation requires CASE_ID")

    if not settings.ALLOWED_REPLAY_TOPIC:
        raise ValueError("sandbox isolation requires ALLOWED_REPLAY_TOPIC")

    if not settings.ALLOWED_RESULT_TOPIC:
        raise ValueError("sandbox isolation requires ALLOWED_RESULT_TOPIC")

    if settings.SOURCE_TOPIC != settings.ALLOWED_REPLAY_TOPIC:
        raise ValueError(
            f"sandbox SOURCE_TOPIC mismatch expected={settings.ALLOWED_REPLAY_TOPIC} actual={settings.SOURCE_TOPIC}"
        )

    if settings.RESULT_TOPIC != settings.ALLOWED_RESULT_TOPIC:
        raise ValueError(
            f"sandbox RESULT_TOPIC mismatch expected={settings.ALLOWED_RESULT_TOPIC} actual={settings.RESULT_TOPIC}"
        )

    if settings.ENABLE_DLQ_PUBLISH:
        raise ValueError("sandbox isolation forbids ENABLE_DLQ_PUBLISH=true")

    print(
        f"[ISOLATION] consumer strict sandbox isolation validated "
        f"case_id={settings.CASE_ID} replay_topic={settings.ALLOWED_REPLAY_TOPIC} "
        f"result_topic={settings.ALLOWED_RESULT_TOPIC}"
    )


producer = get_producer()
consumer = get_consumer()
validate_sandbox_isolation()
write_ready_file()

print(
    f"[INFO] Consumer started topic={settings.SOURCE_TOPIC}, dlq={settings.DLQ_TOPIC}, "
    f"group={settings.GROUP_ID}, image_ref={settings.IMAGE_REF}, "
    f"run_mode={settings.RUN_MODE}, validation_mode={settings.VALIDATION_MODE}"
)

for message in consumer:
    payload = message.value
    phase = detect_phase(payload)

    try:
        print(f"[INFO] Received: {payload}")

        # 실제 핵심 비즈니스 로직
        process_order(payload)

        print(f"[SUCCESS] processed order_id={payload.get('order_id')}")

        if settings.RUN_MODE == "sandbox":
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
        if settings.RUN_MODE == "sandbox":
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

        if settings.ENABLE_DLQ_PUBLISH:
            producer.send(settings.DLQ_TOPIC, failure_event)
            producer.flush()
            print(
                f"[DLQ] published to {settings.DLQ_TOPIC} "
                f"case_id={failure_event['case_id']} "
                f"image_ref={failure_event['runtime']['image_ref']}"
            )
        else:
            print("[INFO] DLQ publish disabled, failure captured only")