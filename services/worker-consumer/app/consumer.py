from kafka import KafkaConsumer, KafkaProducer
import json
import os
import time
from datetime import datetime, timezone
import pymysql  # MySQL RDS 저장을 위한 라이브러리

def getenv(name: str, default: str = "") -> str:
    return os.getenv(name, default)

# --- [Kafka 설정: 주석 스위치] ---
# 옵션 A: 표준 도메인 (추천)
KAFKA_BOOTSTRAP = getenv("KAFKA_BOOTSTRAP", "kafka.kafka-poc.svc.cluster.local:9092")
# 옵션 B: 기존 오타 수정 버전
# KAFKA_BOOTSTRAP = getenv("KAFKA_BOOTSTRAP", "kafka.kafka-poc.svc.cluster.kafka:9092")

SOURCE_TOPIC = getenv("SOURCE_TOPIC", "orders")
DLQ_TOPIC = getenv("DLQ_TOPIC", "orders-dlq")
GROUP_ID = getenv("GROUP_ID", "orders-consumer-prod")

SERVICE_NAME = getenv("SERVICE_NAME", "worker-consumer")
NAMESPACE = getenv("NAMESPACE", "kafka-poc")
DEPLOYMENT_NAME = getenv("DEPLOYMENT_NAME", "worker-consumer")

IMAGE_REF = getenv("IMAGE_REF", "ghcr.io/your-org/worker-consumer:poc-v1")
CONFIG_VERSION = getenv("CONFIG_VERSION", "v1")
DEPENDENCY_PROFILE = getenv("DEPENDENCY_PROFILE", "prod")

# --- [RDS 및 DB 설정] ---
RDS_HOST = getenv("RDS_HOST", "localhost")
RDS_USER = getenv("RDS_USER", "admin")
RDS_PASSWORD = getenv("RDS_PASSWORD", "password")
RDS_DB = getenv("RDS_DB", "orders_db")
RDS_PORT = int(getenv("RDS_PORT", "3306"))
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

def save_to_rds(payload: dict):
    # RDS 연결 실패를 유도하여 '인프라 장애' 시나리오 테스트
    if not RDS_HOST or RDS_HOST == "localhost":
        raise ConnectionError("RDS_HOST가 설정되지 않았거나 localhost입니다. (인프라 장애 시뮬레이션)")
        
    try:
        connection = pymysql.connect(
            host=RDS_HOST, user=RDS_USER, password=RDS_PASSWORD,
            database=RDS_DB, port=RDS_PORT, cursorclass=pymysql.cursors.DictCursor
        )
        with connection.cursor() as cursor:
            sql = "INSERT INTO orders (order_id, data_payload, status) VALUES (%s, %s, %s)"
            cursor.execute(sql, (payload.get('order_id', 'unknown'), json.dumps(payload), 'processed'))
        connection.commit()
    except pymysql.err.DataError as e:
        raise ValueError(f"DataTruncation: {str(e)}") # 로직 에러(샌드박스행)
    except Exception as e:
        raise ConnectionError(f"OperationalError: {str(e)}") # 리소스 에러(재시도행)
    finally:
        if 'connection' in locals() and connection.open:
            connection.close()

# --- [메인 로직] ---
producer = get_producer()
consumer = get_consumer()

print(f"✅ [INFO] Consumer active on {SOURCE_TOPIC}. Watching for orders...")

for message in consumer:
    payload = message.value
    try:
        print(f"\n📥 [RECEIVED] {payload}")

        # 1. 의도적 실패 필드 체크 (POC용)
        if payload.get(FORCE_FAIL_FIELD) is True:
            raise ValueError("intentional failure for POC (Logic Error)")

        # 2. RDS 저장 시도 (실제 비즈니스 로직)
        save_to_rds(payload)
        print(f"🎉 [SUCCESS] Order {payload.get('order_id')} processed.")

    except Exception as e:
        # 에러 발생 시 '명찰'을 달아서 DLQ 토픽으로 던짐
        failure_event = {
            "source_service": SERVICE_NAME,
            "source_namespace": NAMESPACE,
            "source_deployment": DEPLOYMENT_NAME,
            "error_type": e.__class__.__name__, # Handler가 이 이름을 보고 판단함
            "error_message": str(e),
            "timestamp": utc_now_iso(),
            "original_payload": payload
        }
        print(f"🚨 [DLQ ROUTING] {e.__class__.__name__} occurred. Routing to DLQ.")
        producer.send(DLQ_TOPIC, failure_event)
        producer.flush()