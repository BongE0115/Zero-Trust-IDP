# trigger
from kafka import KafkaConsumer, KafkaProducer
import json
import os
import time
from datetime import datetime, timezone


def getenv(name: str, default: str = "") -> str:
    return os.getenv(name, default)


KAFKA_BOOTSTRAP = getenv("KAFKA_BOOTSTRAP", "kafka.kafka-poc.svc.cluster.kafka:9092") # 메시지 전송 확인 방법 1 (ssm에서 확인)로 확인하기 위해 local -> kafka로 변경함.
SOURCE_TOPIC = getenv("SOURCE_TOPIC", "orders")
DLQ_TOPIC = getenv("DLQ_TOPIC", "orders-dlq")
GROUP_ID = getenv("GROUP_ID", "orders-consumer-prod")

SERVICE_NAME = getenv("SERVICE_NAME", "worker-consumer")
NAMESPACE = getenv("NAMESPACE", "kafka-poc")
DEPLOYMENT_NAME = getenv("DEPLOYMENT_NAME", "worker-consumer")

IMAGE_REF = getenv("IMAGE_REF", "ghcr.io/your-org/worker-consumer:poc-v1")
CONFIG_VERSION = getenv("CONFIG_VERSION", "v1")
DEPENDENCY_PROFILE = getenv("DEPENDENCY_PROFILE", "prod")

DB_MODE = getenv("DB_MODE", "mongo")
DB_HOST = getenv("DB_HOST", "")
CACHE_MODE = getenv("CACHE_MODE", "disabled")
CACHE_HOST = getenv("CACHE_HOST", "")
EXTERNAL_API_MODE = getenv("EXTERNAL_API_MODE", "disabled")
EXTERNAL_API_BASE_URL = getenv("EXTERNAL_API_BASE_URL", "")

FORCE_FAIL_FIELD = getenv("FORCE_FAIL_FIELD", "should_fail")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_producer():
    for _ in range(60):
        try:
            return KafkaProducer(
                bootstrap_servers=KAFKA_BOOTSTRAP,
                value_serializer=lambda v: json.dumps(v).encode("utf-8")
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


producer = get_producer()
consumer = get_consumer()

print(
    f"[INFO] Consumer started topic={SOURCE_TOPIC}, dlq={DLQ_TOPIC}, "
    f"group={GROUP_ID}, image_ref={IMAGE_REF}"
)

for message in consumer:
    payload = message.value

    try:
        print(f"[INFO] Received: {payload}")

        # POC용 의도적 실패 조건
        if payload.get(FORCE_FAIL_FIELD) is True:
            raise ValueError("intentional failure for POC")

        print(f"[SUCCESS] processed order_id={payload.get('order_id')}")

    except Exception as e:
        failure_event = {
            "source_service": SERVICE_NAME,
            "source_namespace": NAMESPACE,
            "source_deployment": DEPLOYMENT_NAME,
            "source_topic": SOURCE_TOPIC,
            "consumer_group": GROUP_ID,
            "image_ref": IMAGE_REF,
            "config_version": CONFIG_VERSION,
            "dependency_profile": DEPENDENCY_PROFILE,
            "db_mode": DB_MODE,
            "db_host": DB_HOST,
            "cache_mode": CACHE_MODE,
            "cache_host": CACHE_HOST,
            "external_api_mode": EXTERNAL_API_MODE,
            "external_api_base_url": EXTERNAL_API_BASE_URL,
            "error_type": e.__class__.__name__,
            "error_message": str(e),
            "timestamp": utc_now_iso(),
            "original_payload": payload
        }

        print(f"[DLQ] {failure_event}")
        producer.send(DLQ_TOPIC, failure_event)
        producer.flush()