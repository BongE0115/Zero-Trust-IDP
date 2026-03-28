import json
import logging
import os
from datetime import datetime
from kafka import KafkaProducer
from app.config.settings import settings

logger = logging.getLogger(__name__)

def get_producer():
    try:
        # settings에 설정된 KAFKA_BOOTSTRAP_SERVERS를 사용하도록 수정 (충돌 마커 제거)
        return KafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            acks=1 # 메시지 전송 보장
        )
    except Exception as e:
        logger.error(f"[DLQ] Producer creation failed: {e}")
        return None

def send_to_dlq(event: dict, reason: str = "unknown", service_name: str = "consumer"):
    """
    장애 데이터를 DLQ 토픽으로 전송합니다.
    시나리오 A를 위해 DB 관련 메타데이터를 포함합니다.
    """
    dlq_event = {
        "source_service": service_name,
        "source_topic": settings.KAFKA_TOPIC_MAIN,
        "image_tag": os.getenv("IMAGE_TAG", "latest"), # 배포 시 지정된 이미지 태그
        "error_type": reason,
        "timestamp": datetime.utcnow().isoformat(),
        "original_payload": event,
        
        # [시나리오 A 핵심] 의존성 컨텍스트 추가
        "dependency_context": {
            "type": "mongodb",           # 현재 사용 중인 DB 타입
            "db_name": settings.MONGO_DB,
            "collection": settings.MONGO_COLLECTION,
            "operation": "insert_one"    # 실패한 작업 종류 (추후 동적으로 변경 가능)
        }
    }

    producer = get_producer()

    if producer is None:
        logger.error("[DLQ] Producer not available, skipping send")
        return

    try:
        producer.send(settings.KAFKA_TOPIC_DLQ, value=dlq_event)
        producer.flush()
        logger.info(f"✅ Sent to DLQ (Topic: {settings.KAFKA_TOPIC_DLQ})")

    except Exception as e:
        logger.error(f"[DLQ] Send FAILED: {e}")