import json
import logging
import uuid
from typing import List

from kafka import KafkaProducer
from pymongo import MongoClient

from app.config.settings import settings

logger = logging.getLogger(__name__)


class RedriveService:
    def __init__(self):
        self.producer = KafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )

        self.client = MongoClient(settings.MONGO_URI)
        self.db = self.client[settings.MONGO_DB]

        # 🔥 cases 컬렉션 사용
        self.collection = self.db["cases"]

        # 결과 저장
        self.result_collection = self.db["redrive_results"]

    def fetch_failed_messages(self, limit: int = 50) -> List[dict]:
        return list(self.collection.find().limit(limit))

    def redrive(self, limit: int = 50) -> dict:
        messages = self.fetch_failed_messages(limit)

        if not messages:
            return {"reprocessed": 0, "success": 0, "failed": 0}

        redrive_id = str(uuid.uuid4())
        count = 0

        for msg in messages:
            try:
                payload = msg.get("original_payload")  # 🔥 핵심 변경
                if not payload:
                    continue

                payload = dict(payload)

                payload["is_reprocessed"] = True
                payload["severity"] = "WARNING"
                payload["redrive_id"] = redrive_id

                # 🔥 핵심: replay topic 사용
                self.producer.send(settings.KAFKA_TOPIC_REPLAY, payload)

                count += 1

            except Exception as e:
                logger.error(f"[Redrive] Send error: {e}")

        self.producer.flush()

        logger.info(f"[Redrive] {count} messages re-sent to replay topic")

        import time
        time.sleep(5)

        success = self.result_collection.count_documents({
            "redrive_id": redrive_id,
            "status": "success"
        })

        failed = self.result_collection.count_documents({
            "redrive_id": redrive_id,
            "status": "failed"
        })

        return {
            "reprocessed": count,
            "success": success,
            "failed": failed
        }