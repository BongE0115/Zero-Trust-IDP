from kafka import KafkaConsumer
import json
import os
import time
from datetime import datetime, timezone


def getenv(name: str, default: str = "") -> str:
    return os.getenv(name, default)


KAFKA_BOOTSTRAP = getenv("KAFKA_BOOTSTRAP", "kafka.kafka-poc.svc.cluster.local:9092")
DLQ_TOPIC = getenv("DLQ_TOPIC", "orders-dlq")
GROUP_ID = getenv("GROUP_ID", "orders-dlq-handler")

ENABLE_REPLAY = getenv("ENABLE_REPLAY", "false").lower() == "true"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_case_id(event: dict) -> str:
    source_service = event.get("source_service", "unknown-service")
    original_payload = event.get("original_payload", {}) or {}
    order_id = original_payload.get("order_id", "unknown-order")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{source_service}-{order_id}-{timestamp}"


def get_consumer():
    for _ in range(60):
        try:
            return KafkaConsumer(
                DLQ_TOPIC,
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


def print_alert(event: dict):
    case_id = build_case_id(event)

    source_service = event.get("source_service", "unknown")
    source_namespace = event.get("source_namespace", "unknown")
    source_deployment = event.get("source_deployment", "unknown")
    source_topic = event.get("source_topic", "unknown")
    consumer_group = event.get("consumer_group", "unknown")

    error_type = event.get("error_type", "unknown")
    error_message = event.get("error_message", "unknown")

    image_ref = event.get("image_ref", "unknown")
    config_version = event.get("config_version", "unknown")
    dependency_profile = event.get("dependency_profile", "unknown")

    original_payload = event.get("original_payload", {}) or {}

    print("=" * 80)
    print("[ALERT] DLQ failure event detected")
    print(f"[ALERT] detected_at={utc_now_iso()}")
    print(f"[ALERT] case_id={case_id}")
    print(f"[ALERT] source_service={source_service}")
    print(f"[ALERT] source_namespace={source_namespace}")
    print(f"[ALERT] source_deployment={source_deployment}")
    print(f"[ALERT] source_topic={source_topic}")
    print(f"[ALERT] consumer_group={consumer_group}")
    print(f"[ALERT] image_ref={image_ref}")
    print(f"[ALERT] config_version={config_version}")
    print(f"[ALERT] dependency_profile={dependency_profile}")
    print(f"[ALERT] error_type={error_type}")
    print(f"[ALERT] error_message={error_message}")
    print(f"[ALERT] original_payload={json.dumps(original_payload, ensure_ascii=False)}")
    print("[ALERT] next_action=manual_git_update_for_sandbox_enable")
    print("=" * 80)


def main():
    consumer = get_consumer()
    print(
        f"[INFO] DLQ handler started. dlq={DLQ_TOPIC}, "
        f"group={GROUP_ID}, replay_enabled={ENABLE_REPLAY}"
    )

    for message in consumer:
        event = message.value

        try:
            print_alert(event)

            if ENABLE_REPLAY:
                print("[WARN] ENABLE_REPLAY=true but replay logic is intentionally disabled in this POC stage.")
                print("[WARN] Replay should be triggered only after sandbox is created via GitOps.")
        except Exception as e:
            print(f"[ERROR] Failed to process DLQ event: {e}")
            print(f"[ERROR] raw_event={event}")


if __name__ == "__main__":
    main()