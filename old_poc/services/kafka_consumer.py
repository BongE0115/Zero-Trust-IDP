import json
import logging
from kafka import KafkaConsumer
from pymongo import MongoClient

from app.services.slack_notifier import send_slack_alert
from app.services.dlq_producer import send_to_dlq
from app.recovery.recovery_dispatcher import dispatch_recovery
from app.config.settings import settings

# 로그 설정 (운영 환경에 맞게 정리)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AnomalyKafkaConsumer:
    def __init__(self, bootstrap_servers: str, topic: str, group_id: str):
        self.topic = topic

        self.consumer = KafkaConsumer(
            self.topic,
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
            auto_offset_reset="earliest",
            enable_auto_commit=True,
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        )

        # Mongo (실제 운영 데이터 및 결과 기록용)
        self.mongo_client = MongoClient(settings.MONGO_URI)
        self.mongo_db = self.mongo_client[settings.MONGO_DB]
        self.result_collection = self.mongo_db["redrive_results"]
        # 시나리오 A를 위한 운영 데이터 컬렉션
        self.main_collection = self.mongo_db["main_events"]

    def start(self):
        logger.info(f"🚀 Kafka Consumer started on topic: {self.topic}")

        for message in self.consumer:
            event = message.value
            logger.info(f"📥 Received event: {event}")

            try:
                # 1. 이벤트 처리 (시나리오 A 장애 재현 포함)
                self.process_event(event)

                # 2. 성공 시 운영 DB 저장 및 기록
                self.main_collection.insert_one(event)
                
                if "redrive_id" in event:
                    self.result_collection.insert_one({
                        "redrive_id": event["redrive_id"],
                        "status": "success",
                        "processed_at": settings.APP_ENV
                    })
                logger.info("✅ Event processed and saved to main DB")

            except Exception as e:
                # ❗ 3단계의 핵심: 모든 에러는 여기서 감지되어 DLQ로 전송됨
                error_reason = str(e)
                logger.error(f"❌ Processing failed: {error_reason}")
                
                # DLQ 전송 (원본 데이터 + 에러 이유)
                send_to_dlq(event, reason=error_reason, service_name="aiops-backend-consumer")

                # 실패 기록
                if "redrive_id" in event:
                    self.result_collection.insert_one({
                        "redrive_id": event["redrive_id"],
                        "status": "failed",
                        "error": error_reason
                    })

    def process_event(self, event: dict):
        """
        비즈니스 로직 처리 및 시나리오 A 장애 상황 시뮬레이션
        """
        # [시나리오 A 재현] 
        # 'message' 필드의 길이가 20자를 넘으면 DB Column Overflow 에러 발생 시뮬레이션
        content = event.get("message", "")
        if len(content) > 20:
            raise ValueError(f"Database Error: String data right truncation. Content length ({len(content)}) exceeds column limit (20).")

        severity = event.get("severity", "INFO")

        if severity == "CRITICAL":
            self.handle_critical(event)
        elif severity == "WARNING":
            self.handle_warning(event)
        else:
            logger.info(f"📝 Normal event processed: {severity}")

    def handle_critical(self, event: dict):
        # 중요 장애는 복구 디스패처로 전달
        dispatch_recovery(event)

    def handle_warning(self, event: dict):
        # 경고 알림 전송 (DLQ로 가지 않는 일반 알림)
        send_slack_alert(event, 0.0)

# ==============================
# 🚀 실전 실행 로직 (Step 5의 핵심)
# ==============================
if __name__ == "__main__":
    # settings에 정의된 값을 사용하여 컨슈머 실행
    consumer = AnomalyKafkaConsumer(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        topic=settings.KAFKA_TOPIC_MAIN,
        group_id="anomaly-consumer-group"
    )
    consumer.start()