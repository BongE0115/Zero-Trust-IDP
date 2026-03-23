import json
import logging
from kafka import KafkaProducer

logger = logging.getLogger(__name__)

DLQ_TOPIC = "anomaly-dlq"


def get_producer():
    try:
        return KafkaProducer(
            bootstrap_servers="localhost:9092",
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
    except Exception as e:
        logger.error(f"[DLQ] Producer creation failed: {e}")
        return None


def send_to_dlq(event: dict, reason: str = "unknown"):
    dlq_event = {
        "original_event": event,
        "reason": reason,
    }

    producer = get_producer()

    if producer is None:
        logger.error("[DLQ] Producer not available, skipping send")
        return

    try:
        producer.send(DLQ_TOPIC, value=dlq_event)
        producer.flush()
        print("✅ Sent to DLQ")

    except Exception as e:
        logger.error(f"[DLQ] Send FAILED: {e}")