from kafka import KafkaProducer
import json
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

    def send(self, topic: str, event: dict):
        try:
            self._connect()
            self.producer.send(topic, event)
            self.producer.flush()
            # print(f"[Kafka] Event sent to {topic}")
        except Exception as e:
            print(f"[Kafka ERROR] {e}")


# 🔥 lazy singleton
_kafka_producer = None


def get_kafka_producer():
    global _kafka_producer
    if _kafka_producer is None:
        _kafka_producer = KafkaEventProducer()
    return _kafka_producer