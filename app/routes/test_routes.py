from fastapi import APIRouter
from app.models.event_models import AnomalyEvent
from app.services.kafka_producer import get_kafka_producer
from app.config.settings import settings

router = APIRouter()


@router.post("/test/anomaly")
def create_test_event(event: AnomalyEvent):
    event_dict = event.model_dump(mode="json")

    # 🔥 Kafka 전송 (lazy connect)
    producer = get_kafka_producer()
    producer.send(settings.KAFKA_TOPIC_MAIN, event_dict)

    return {
        "status": "sent",
        "event": event_dict
    }

@router.post("/test/anomaly/batch")
def create_test_events_batch(count: int = 10):
    """
    테스트용: 이벤트 여러 개 한 번에 전송
    """
    producer = get_kafka_producer()

    for i in range(count):
        event = {
            "event_id": f"test-{i}",
            "timestamp": "2026-03-19T12:00:00",
            "source": "server-1",
            "metric_name": "cpu_usage",
            "metric_value": 95.5,
            "threshold": 80.0,
            "anomaly_score": 0.92,
            "severity": "CRITICAL",
            "message": "DLQ test"
        }

        producer.send(settings.KAFKA_TOPIC_MAIN, event)

    return {
        "status": "sent",
        "count": count
    }