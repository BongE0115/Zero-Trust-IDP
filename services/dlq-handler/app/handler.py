from kafka import KafkaConsumer, KafkaProducer
import json
import os
import time
import sys

# 📍 1. 임포트 경로 최적화 (slack_notifier 참조)
try:
    from slack_notifier import send_slack_alert
except ImportError:
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    try:
        from slack_notifier import send_slack_alert
    except ImportError:
        def send_slack_alert(event, score=0.0, category="UNKNOWN", action="NONE"):
            print(f"[DUMMY SLACK] Alert: {category} | Action: {action}")

def getenv(name: str, default: str = "") -> str:
    return os.getenv(name, default)

# --- [설정 및 상수: Kafka 접속 스위치] ---
# 옵션 A: 표준 인프라 네임스페이스(kafka)의 서비스를 사용할 경우
KAFKA_BOOTSTRAP = getenv("KAFKA_BOOTSTRAP", "kafka.kafka.svc.cluster.local:9092")

# 옵션 B: POC 전용 네임스페이스(kafka-poc)의 서비스를 사용할 경우
# KAFKA_BOOTSTRAP = getenv("KAFKA_BOOTSTRAP", "kafka.kafka-poc.svc.cluster.local:9092")

DLQ_TOPIC = getenv("DLQ_TOPIC", "orders-dlq")
REPLAY_TOPIC = getenv("REPLAY_TOPIC", "orders-replay")
GROUP_ID = getenv("GROUP_ID", "orders-dlq-handler")

AUTO_REPLAY = getenv("AUTO_REPLAY", "true").lower() == "true"

# --- [📍 2. 지능형 Error Category Map 정의] ---
ERROR_POLICY_MAP = {
    "TimeoutError": {"category": "NETWORK_TIMEOUT", "action": "REPLAY"},
    "ConnectionError": {"category": "CONNECTION_FAILURE", "action": "REPLAY"},
    "ServiceUnavailable": {"category": "INFRA_DOWN", "action": "REPLAY"},
    "OperationalError": {"category": "DB_TRANSIENT_ISSUE", "action": "REPLAY"},
    "RemoteDisconnected": {"category": "PEER_DISCONNECTED", "action": "REPLAY"},
    "KeyError": {"category": "DATA_MISMATCH", "action": "SANDBOX"},
    "ValueError": {"category": "INVALID_FORMAT", "action": "SANDBOX"},
    "JSONDecodeError": {"category": "PAYLOAD_CORRUPT", "action": "SANDBOX"},
    "TypeError": {"category": "CODE_LOGIC_ERROR", "action": "SANDBOX"},
    "IntegrityError": {"category": "DB_CONSTRAINT_VIOLATION", "action": "SANDBOX"},
}

def classify_error(error_type):
    policy = ERROR_POLICY_MAP.get(error_type)
    if policy:
        return policy["category"], policy["action"]
    return "UNKNOWN_CATEGORY", "MANUAL_CHECK"

# --- [유틸리티 함수: Kafka] ---
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

# --- [메인 실행 로직] ---
try:
    producer = get_producer()
    consumer = get_consumer()
except Exception as e:
    print(f"💀 [CRITICAL] System Init Failed: {e}")
    sys.exit(1)

print(f"✅ [INFO] Error Category Map Handler active. Monitoring {DLQ_TOPIC}...")

for message in consumer:
    failure_event = message.value
    error_type = failure_event.get("error_type", "UnknownError")
    original_payload = failure_event.get("original_payload", {})
    
    category, action = classify_error(error_type)
    print(f"\n📥 [DLQ DETECTED] Type: {error_type} | Category: {category} | Action: {action}")

    if action == "REPLAY":
        if AUTO_REPLAY:
            producer.send(REPLAY_TOPIC, original_payload)
            producer.flush()
            print(f"✅ [REPLAY] Message sent to {REPLAY_TOPIC}")

    elif action == "SANDBOX":
        # [수정됨] K8s 직접 제어를 걷어내고, 오직 슬랙으로 명세서를 발송합니다.
        # 실제 샌드박스 기동은 엔지니어의 슬랙 버튼 클릭 -> producer-api -> GitHub Actions를 통해 이루어집니다.
        print(f"🚨 [ACTION: SANDBOX] '{category}' 감지. 관리자에게 Slack 알림을 발송합니다.")
        # 🌟 파라미터로 category와 action을 확실하게 전달!
        send_slack_alert(failure_event, category=category, action=action)

    else:
        print(f"❓ [ACTION: MANUAL] 정의되지 않은 패턴. 카탈로그 업데이트가 필요합니다.")
        # 🌟 여기도 마찬가지로 전달!
        send_slack_alert(failure_event, category="UNDEFINED", action="MANUAL_CHECK")