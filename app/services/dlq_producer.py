import json
import logging
from datetime import datetime
from kafka import KafkaProducer
from app.config.settings import settings

logger = logging.getLogger(__name__)


def get_producer():
    try:
        return KafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
    except Exception as e:
        logger.error(f"[DLQ] Producer creation failed: {e}")
        return None


def send_to_dlq(event: dict, reason: str = "unknown"):
    dlq_event = {
        "source_service": "consumer",  # 추후 수정 가능
        "source_topic": settings.KAFKA_TOPIC_MAIN,
        "consumer_group": "events-consumer-prod",
        "image_tag": "dev",  # 추후 env로 변경 가능
        "error_type": reason,
        "timestamp": datetime.utcnow().isoformat(),
        "original_payload": event,
    }

    producer = get_producer()

    if producer is None:
        logger.error("[DLQ] Producer not available, skipping send")
        return

    try:
        producer.send(settings.KAFKA_TOPIC_DLQ, value=dlq_event)
        producer.flush()
        print("✅ Sent to DLQ")

    except Exception as e:
        logger.error(f"[DLQ] Send FAILED: {e}")