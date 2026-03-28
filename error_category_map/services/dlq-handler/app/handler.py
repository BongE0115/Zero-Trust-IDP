from kafka import KafkaConsumer, KafkaProducer
from kubernetes import client, config
import json
import os
import time
import sys

# 📍 1. 임포트 경로 최적화 (handler.py와 같은 폴더에 있는 slack_notifier 참조)
try:
    from slack_notifier import send_slack_alert
except ImportError:
    # 경로가 꼬일 경우를 대비해 현재 디렉토리를 path에 추가
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    try:
        from slack_notifier import send_slack_alert
    except ImportError:
        def send_slack_alert(event, category="UNKNOWN", action="NONE"):
            print(f"[DUMMY SLACK] Alert: {category} | Action: {action}")

def getenv(name: str, default: str = "") -> str:
    return os.getenv(name, default)

# --- [설정 및 상수] ---
KAFKA_BOOTSTRAP = getenv("KAFKA_BOOTSTRAP", "kafka-cluster-kafka-bootstrap.kafka-stack.svc.cluster.local:9092")
DLQ_TOPIC = getenv("DLQ_TOPIC", "orders-dlq")
REPLAY_TOPIC = getenv("REPLAY_TOPIC", "orders-replay")
GROUP_ID = getenv("GROUP_ID", "orders-dlq-handler")

SANDBOX_NAMESPACE = getenv("SANDBOX_NAMESPACE", "forensic-sandbox")
SANDBOX_DEPLOYMENT = getenv("SANDBOX_DEPLOYMENT", "forensic-sandbox-app")
MONGO_DEPLOYMENT = getenv("MONGO_DEPLOYMENT", "mongodb-temp")

AUTO_SCALE_SANDBOX = getenv("AUTO_SCALE_SANDBOX", "true").lower() == "true"
AUTO_REPLAY = getenv("AUTO_REPLAY", "true").lower() == "true"

# --- [📍 2. 지능형 Error Category Map 정의] ---
# 에러명뿐만 아니라 '어떤 행동(Action)'을 할지도 맵에 포함시켰습니다.
ERROR_POLICY_MAP = {
    # [RESOURCE_PATH] 재시도(Replay)가 필요한 그룹
    "TimeoutError": {"category": "NETWORK_TIMEOUT", "action": "REPLAY"},
    "ConnectionError": {"category": "CONNECTION_FAILURE", "action": "REPLAY"},
    "ServiceUnavailable": {"category": "INFRA_DOWN", "action": "REPLAY"},
    "OperationalError": {"category": "DB_TRANSIENT_ISSUE", "action": "REPLAY"},
    "RemoteDisconnected": {"category": "PEER_DISCONNECTED", "action": "REPLAY"},

    # [LOGIC_PATH] 샌드박스 격리 및 사람의 개입이 필요한 그룹
    "KeyError": {"category": "DATA_MISMATCH", "action": "SANDBOX"},
    "ValueError": {"category": "INVALID_FORMAT", "action": "SANDBOX"},
    "JSONDecodeError": {"category": "PAYLOAD_CORRUPT", "action": "SANDBOX"},
    "TypeError": {"category": "CODE_LOGIC_ERROR", "action": "SANDBOX"},
    "IntegrityError": {"category": "DB_CONSTRAINT_VIOLATION", "action": "SANDBOX"},
}

def classify_error(error_type):
    """에러 타입을 분석하여 카테고리와 권장 액션을 반환"""
    policy = ERROR_POLICY_MAP.get(error_type)
    if policy:
        return policy["category"], policy["action"]
    return "UNKNOWN_CATEGORY", "MANUAL_CHECK"

# --- [유틸리티 함수: Kafka & K8s] --- (기존과 동일하되 가독성 개선)
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

def get_apps_api():
    try:
        config.load_incluster_config()
        return client.AppsV1Api()
    except:
        try:
            config.load_kube_config() # 로컬 테스트용
            return client.AppsV1Api()
        except:
            print("❌ Kubernetes API init failed")
            return None

def scale_deployment(apps_api, namespace, name, replicas):
    if not apps_api: return
    try:
        body = {"spec": {"replicas": replicas}}
        apps_api.patch_namespaced_deployment_scale(name=name, namespace=namespace, body=body)
        print(f"🚀 [SCALE] {namespace}/{name} -> {replicas}")
    except Exception as e:
        print(f"❌ [SCALE ERROR] {e}")

# --- [메인 실행 로직] ---
try:
    producer = get_producer()
    consumer = get_consumer()
    apps_api = get_apps_api()
except Exception as e:
    print(f"💀 [CRITICAL] System Init Failed: {e}")
    sys.exit(1)

print(f"✅ [INFO] Error Category Map Handler active. Monitoring {DLQ_TOPIC}...")

for message in consumer:
    failure_event = message.value
    error_type = failure_event.get("error_type", "UnknownError")
    original_payload = failure_event.get("original_payload", {})
    
    # 📍 3. 알고리즘 적용: 카테고리 분류
    category, action = classify_error(error_type)
    print(f"\n📥 [DLQ DETECTED] Type: {error_type} | Category: {category} | Action: {action}")

    # 1️⃣ [REPLAY PATH]
    if action == "REPLAY":
        print(f"♻️  [ACTION: REPLAY] '{category}' 감지. 자동 재시도를 수행합니다.")
        if AUTO_REPLAY:
            producer.send(REPLAY_TOPIC, original_payload)
            producer.flush()
            print(f"✅ [REPLAY] Message sent to {REPLAY_TOPIC}")

    # 2️⃣ [SANDBOX PATH]
    elif action == "SANDBOX":
        print(f"🚨 [ACTION: SANDBOX] '{category}' 감지. 격리 분석을 시작합니다.")
        if AUTO_SCALE_SANDBOX:
            scale_deployment(apps_api, SANDBOX_NAMESPACE, MONGO_DEPLOYMENT, 1)
            scale_deployment(apps_api, SANDBOX_NAMESPACE, SANDBOX_DEPLOYMENT, 1)
        
        # 슬랙 알림 시 카테고리 정보 포함
        failure_event["category"] = category
        send_slack_alert(failure_event)

    # 3️⃣ [MANUAL PATH]
    else:
        print(f"❓ [ACTION: MANUAL] 정의되지 않은 패턴. 카탈로그 업데이트가 필요합니다.")
        send_slack_alert(failure_event, category="UNDEFINED")