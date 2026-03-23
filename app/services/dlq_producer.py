import json
import logging
from kafka import KafkaProducer

logger = logging.getLogger(__name__)

DLQ_TOPIC = "anomaly-dlq"

producer = KafkaProducer(
    bootstrap_servers="localhost:9092",
    value_serializer=lambda v: json.dumps(v).encode("utf-8"),
)


def send_to_dlq(event: dict, reason: str = "unknown"):
    dlq_event = {
        "original_event": event,
        "reason": reason,
    }

    try:
        producer.send(DLQ_TOPIC, value=dlq_event)
        producer.flush()
        ## logger.error(f"[DLQ] Sent | reason={reason} | event={event}")

    except Exception as e:
        logger.error(f"[DLQ] Send FAILED: {e}")