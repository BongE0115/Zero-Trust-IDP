import json
import logging
from kafka import KafkaConsumer
from pymongo import MongoClient

from app.services.slack_notifier import send_slack_alert
from app.services.dlq_producer import send_to_dlq
from app.recovery.recovery_dispatcher import dispatch_recovery
from app.config.settings import settings

# 로그 최소화
logging.getLogger().setLevel(logging.ERROR)
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

        # Mongo (결과 기록)
        self.mongo_client = MongoClient(settings.MONGO_URI)
        self.mongo_db = self.mongo_client[settings.MONGO_DB]
        self.result_collection = self.mongo_db["redrive_results"]

    def start(self):
        print("🚀 Kafka Consumer started")

        for message in self.consumer:
            event = message.value

            try:
                self.process_event(event)

                # ✅ 성공 기록
                if "redrive_id" in event:
                    self.result_collection.insert_one({
                        "redrive_id": event["redrive_id"],
                        "status": "success"
                    })

            except Exception as e:
                # ❗ DLQ는 여기서만 처리 (단일 진입점)
                send_to_dlq(event, reason=type(e).__name__)

                # ❌ 실패 기록
                if "redrive_id" in event:
                    self.result_collection.insert_one({
                        "redrive_id": event["redrive_id"],
                        "status": "failed"
                    })

    def process_event(self, event: dict):
        severity = event.get("severity")

        if severity == "CRITICAL":
            self.handle_critical(event)

        elif severity == "WARNING":
            self.handle_warning(event)

        else:
            raise ValueError("Unknown severity")

    def handle_critical(self, event: dict):
        # ❗ 여기서는 DLQ 보내지 않는다
        dispatch_recovery(event)

    def handle_warning(self, event: dict):
        # ❗ 여기서도 DLQ 보내지 않는다
        send_slack_alert(event, 0.0)