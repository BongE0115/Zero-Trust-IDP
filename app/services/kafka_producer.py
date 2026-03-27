from kafka import KafkaProducer
import json
from datetime import datetime
from app.config.settings import settings


class KafkaEventProducer:
    def __init__(self):
        self.producer = None

    def _connect(self):
        if self.producer is None:
            self.producer = KafkaProducer(
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                value_serializer=lambda v: json.dumps(v).encode("utf-8")
            )

    def send(self, event: dict):
        try:
            self._connect()

            # 🔥 표준 이벤트 구조
            message = {
                "event_type": event.get("event_type", "unknown"),
                "timestamp": datetime.utcnow().isoformat(),
                "payload": event
            }

            self.producer.send(settings.KAFKA_TOPIC_MAIN, message)
            self.producer.flush()

        except Exception as e:
            print(f"[Kafka ERROR] {e}")


# 🔥 lazy singleton
_kafka_producer = None


def get_kafka_producer():
    global _kafka_producer
    if _kafka_producer is None:
        _kafka_producer = KafkaEventProducer()
    return _kafka_producer