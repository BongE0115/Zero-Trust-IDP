# trigger
from kafka import KafkaConsumer, KafkaProducer
import json
import os
import time
from datetime import datetime, timezone
import pymysql  # MySQL RDS 저장을 위한 라이브러리 추가

def getenv(name: str, default: str = "") -> str:
    return os.getenv(name, default)

# --- [Kafka 및 시스템 설정] ---
KAFKA_BOOTSTRAP = getenv("KAFKA_BOOTSTRAP", "kafka.kafka-poc.svc.cluster.kafka:9092")
SOURCE_TOPIC = getenv("SOURCE_TOPIC", "orders")
DLQ_TOPIC = getenv("DLQ_TOPIC", "orders-dlq")
GROUP_ID = getenv("GROUP_ID", "orders-consumer-prod")

SERVICE_NAME = getenv("SERVICE_NAME", "worker-consumer")
NAMESPACE = getenv("NAMESPACE", "kafka-poc")
DEPLOYMENT_NAME = getenv("DEPLOYMENT_NAME", "worker-consumer")

IMAGE_REF = getenv("IMAGE_REF", "ghcr.io/your-org/worker-consumer:poc-v1")
CONFIG_VERSION = getenv("CONFIG_VERSION", "v1")
DEPENDENCY_PROFILE = getenv("DEPENDENCY_PROFILE", "prod")

# --- [DB 및 기타 설정] ---
DB_MODE = getenv("DB_MODE", "mongo") 
DB_HOST = getenv("DB_HOST", "")
CACHE_MODE = getenv("CACHE_MODE", "disabled")
CACHE_HOST = getenv("CACHE_HOST", "")
EXTERNAL_API_MODE = getenv("EXTERNAL_API_MODE", "disabled")
EXTERNAL_API_BASE_URL = getenv("EXTERNAL_API_BASE_URL", "")
FORCE_FAIL_FIELD = getenv("FORCE_FAIL_FIELD", "should_fail")

# --- [RDS 전용 추가 설정] ---
RDS_HOST = getenv("RDS_HOST", "localhost")
RDS_USER = getenv("RDS_USER", "admin")
RDS_PASSWORD = getenv("RDS_PASSWORD", "password")
RDS_DB = getenv("RDS_DB", "orders_db")
RDS_PORT = int(getenv("RDS_PORT", "3306"))

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
    """
    Kafka에서 읽어온 데이터를 MySQL RDS에 저장하는 함수.
    로직 에러(DataTruncation 등)나 리소스 에러(ConnectionError) 발생 시 
    except로 던져서 DLQ로 빠지게 만듭니다.
    """
    # 아직 RDS 세팅이 완벽하지 않아 연결할 수 없다면 에러를 던져 DLQ로 보냅니다.
    if not RDS_HOST or RDS_HOST == "localhost":
        raise ConnectionError("RDS_HOST가 설정되지 않았거나 연결할 수 없습니다.")
        
    try:
        connection = pymysql.connect(
            host=RDS_HOST,
            user=RDS_USER,
            password=RDS_PASSWORD,
            database=RDS_DB,
            port=RDS_PORT,
            cursorclass=pymysql.cursors.DictCursor
        )
        with connection.cursor() as cursor:
            # 예시 쿼리입니다. 실제 테이블 스키마에 맞게 변경하세요.
            sql = "INSERT INTO orders (order_id, data_payload, status) VALUES (%s, %s, %s)"
            cursor.execute(sql, (
                payload.get('order_id', 'unknown_id'), 
                json.dumps(payload), 
                'processed'
            ))
        connection.commit()
    except pymysql.err.DataError as e:
        # 데이터 길이 초과 등의 규격 에러 (DataTruncation)
        raise ValueError(f"DataTruncation: {str(e)}")
    except pymysql.err.OperationalError as e:
        # DB 서버 죽음 등의 리소스 에러
        raise ConnectionError(f"OperationalError: {str(e)}")
    finally:
        if 'connection' in locals() and connection.open:
            connection.close()


# --- [메인 실행 로직] ---
producer = get_producer()
consumer = get_consumer()

print(
    f"✅ [INFO] Consumer started topic={SOURCE_TOPIC}, dlq={DLQ_TOPIC}, "
    f"group={GROUP_ID}, image_ref={IMAGE_REF}"
)

for message in consumer:
    payload = message.value

    try:
        print(f"\n📥 [INFO] Received: {payload}")

        # POC용 의도적 실패 조건 (가장 먼저 체크)
        if payload.get(FORCE_FAIL_FIELD) is True:
            raise ValueError("intentional failure for POC")

        # [추가됨] MySQL RDS에 저장 시도
        save_to_rds(payload)

        # 성공 시 로그만 찍고 넘어갑니다. (에러가 없었으므로 DLQ로 가지 않음)
        print(f"🎉 [SUCCESS] processed order_id={payload.get('order_id')}")

    except Exception as e:
        # RDS 저장 실패 혹은 의도적 실패 시 DLQ로 보낼 서류(명찰) 작성
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
            "error_type": e.__class__.__name__,  # 이 명찰이 판사(handler)에게 전달됨
            "error_message": str(e),
            "timestamp": utc_now_iso(),
            "original_payload": payload
        }

        print(f"🚨 [DLQ ROUTING] Error occurred: {e.__class__.__name__}. Sending to DLQ.")
        producer.send(DLQ_TOPIC, failure_event)
        producer.flush()