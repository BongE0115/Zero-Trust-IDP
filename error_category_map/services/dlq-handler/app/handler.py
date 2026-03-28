# trigger
from kafka import KafkaConsumer, KafkaProducer
from kubernetes import client, config
import json
import os
import time
import sys

# 프로젝트 구조에 따른 slack_notifier 임포트 (경로는 환경에 맞게 조정 필요)
# 만약 파일이 같은 위치에 없다면 sys.path 추가가 필요할 수 있습니다.
try:
    from app.services.slack_notifier import send_slack_alert
except ImportError:
    # 임포트 실패 시 에러만 출력하고 더미 함수 정의 (중단 방지)
    def send_slack_alert(event, score=0.0):
        print(f"[DUMMY SLACK] Alert would be sent for: {event.get('error_type')}")

def getenv(name: str, default: str = "") -> str:
    return os.getenv(name, default)

# --- [설정 및 상수] ---
KAFKA_BOOTSTRAP = getenv("KAFKA_BOOTSTRAP", "kafka.kafka-poc.svc.cluster.kafka:9092")
DLQ_TOPIC = getenv("DLQ_TOPIC", "orders-dlq")
REPLAY_TOPIC = getenv("REPLAY_TOPIC", "orders-replay")
GROUP_ID = getenv("GROUP_ID", "orders-dlq-handler")

SANDBOX_NAMESPACE = getenv("SANDBOX_NAMESPACE", "forensic-sandbox")
SANDBOX_DEPLOYMENT = getenv("SANDBOX_DEPLOYMENT", "forensic-sandbox-app")
MONGO_DEPLOYMENT = getenv("MONGO_DEPLOYMENT", "mongodb-temp")

AUTO_SCALE_SANDBOX = getenv("AUTO_SCALE_SANDBOX", "true").lower() == "true"
AUTO_REPLAY = getenv("AUTO_REPLAY", "true").lower() == "true"

# --- [에러 카테고리 맵 정의] ---
# 리소스 문제: 재시도(Replay)로 해결 가능한 그룹
RESOURCE_ERRORS = [
    "TimeoutError", "ConnectionError", "ServiceUnavailable", 
    "OperationalError", "NetworkError", "RemoteDisconnected"
]

# 로직 문제: 사람의 수정(Sandbox)이 필요한 그룹
LOGIC_ERRORS = [
    "DataTruncation", "KeyError", "ValueError", 
    "JSONDecodeError", "TypeError", "IntegrityError"
]

# --- [유틸리티 함수] ---
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
    for _ in range(30):
        try:
            # 쿠버네티스 클러스터 내부에서 실행될 때의 설정
            config.load_incluster_config()
            return client.AppsV1Api()
        except Exception as e:
            print(f"[WARN] Kubernetes API init failed: {e}")
            time.sleep(2)
    raise RuntimeError("Kubernetes API init failed")

def scale_deployment(apps_api: client.AppsV1Api, namespace: str, name: str, replicas: int):
    try:
        body = {"spec": {"replicas": replicas}}
        apps_api.patch_namespaced_deployment_scale(
            name=name,
            namespace=namespace,
            body=body
        )
        print(f"🚀 [SCALE] {namespace}/{name} -> replicas={replicas}")
    except Exception as e:
        print(f"❌ [SCALE ERROR] {name} 스케일링 실패: {e}")

# --- [메인 실행 로직] ---
producer = get_producer()
consumer = get_consumer()
apps_api = get_apps_api()

print(f"✅ [INFO] DLQ handler started. Monitoring {DLQ_TOPIC}...")

for message in consumer:
    failure_event = message.value
    error_type = failure_event.get("error_type", "UnknownError")
    original_payload = failure_event.get("original_payload", {})
    
    print(f"\n📥 [DLQ DETECTED] Error: {error_type}")

    # 1️⃣ [Resource Path] 일시적 오류 -> 재시도(Replay) 수행
    if error_type in RESOURCE_ERRORS:
        print(f"♻️ [RESOURCE PATH] '{error_type}' 감지. 리소스 문제로 판단하여 재시도 진행.")
        if AUTO_REPLAY:
            try:
                producer.send(REPLAY_TOPIC, original_payload)
                producer.flush()
                print(f"✅ [REPLAY] Sent message to {REPLAY_TOPIC}")
            except Exception as e:
                print(f"❌ [REPLAY ERROR] 전송 실패: {e}")
        # 리소스 문제일 때는 샌드박스를 켜지 않고 종료

    # 2️⃣ [Logic Path] 데이터/코드 오류 -> 샌드박스 격리 및 슬랙 알림
    elif error_type in LOGIC_ERRORS or error_type == "UnknownError":
        print(f"🚨 [LOGIC PATH] '{error_type}' 감지. 코드/데이터 결함으로 판단하여 격리 수행.")
        
        # A. 샌드박스 리소스 활성화
        if AUTO_SCALE_SANDBOX:
            print(f"🛠️ [SANDBOX] 전용 분석 환경(Sandbox) 부활 시도...")
            scale_deployment(apps_api, SANDBOX_NAMESPACE, MONGO_DEPLOYMENT, 1)
            scale_deployment(apps_api, SANDBOX_NAMESPACE, SANDBOX_DEPLOYMENT, 1)

        # B. 슬랙 알림 전송 (버튼 포함)
        try:
            send_slack_alert(failure_event, score=1.0) # 로직 에러이므로 신뢰도 100%
            print(f"💬 [SLACK] 운영자에게 장애 분석 요청 알림 전송 완료.")
        except Exception as e:
            print(f"❌ [SLACK ERROR] 알림 전송 실패: {e}")

    # 3️⃣ [Unknown Path] 정의되지 않은 에러
    else:
        print(f"❓ [SKIP] 정책에 정의되지 않은 에러 패턴: {error_type}. 수동 확인이 필요합니다.")