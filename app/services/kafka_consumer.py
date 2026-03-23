import json
import logging
from kafka import KafkaConsumer

from app.services.slack_notifier import send_slack_alert
from app.services.dlq_producer import send_to_dlq
from app.recovery.recovery_dispatcher import dispatch_recovery

# 🔥 로그 최소화
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

    def start(self):
        print("🚀 Kafka Consumer started")

        for message in self.consumer:

            event = message.value

            try:
                self.process_event(event)

            except Exception as e:
                # 🔥 실패 시 DLQ만 처리 (로그 제거)
                send_to_dlq(event, reason=str(e))

    def process_event(self, event: dict):
        severity = event.get("severity")

        if severity == "CRITICAL":
            self.handle_critical(event)

        elif severity == "WARNING":
            self.handle_warning(event)

    def handle_critical(self, event: dict):
        try:
            dispatch_recovery(event)

        except Exception as e:
            # 🔥 Recovery 실패 → DLQ만
            send_to_dlq(event, reason=f"recovery_failed")

    def handle_warning(self, event: dict):
        try:
            send_slack_alert(event)

        except Exception as e:
            # 🔥 Slack 실패 → DLQ만
            send_to_dlq(event, reason=f"slack_failed")