import json
import logging
from typing import List

from kafka import KafkaProducer
from pymongo import MongoClient

from app.config.settings import settings

logger = logging.getLogger(__name__)


class RedriveService:
    def __init__(self):
        # Kafka Producer
        self.producer = KafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )

        # Mongo
        self.client = MongoClient(settings.MONGO_URI)
        self.db = self.client[settings.MONGO_DB]
        self.collection = self.db[settings.MONGO_COLLECTION]

    def fetch_failed_messages(self, limit: int = 50) -> List[dict]:
        """
        Mongo에서 실패 데이터 조회
        """
        docs = list(self.collection.find().limit(limit))
        return docs

    def redrive(self, limit: int = 50) -> int:
        """
        Mongo → Kafka 재전송
        """
        messages = self.fetch_failed_messages(limit)

        if not messages:
            logger.warning("[Redrive] No messages found")
            return 0

        count = 0

        for msg in messages:
            try:
                # Mongo _id 제거
                msg.pop("_id", None)

                # Kafka로 전송
                self.producer.send(settings.KAFKA_TOPIC_MAIN, msg)
                count += 1

            except Exception as e:
                logger.error(f"[Redrive] Send error: {e}")

        self.producer.flush()

        logger.info(f"[Redrive] {count} messages re-sent to Kafka")

        return count