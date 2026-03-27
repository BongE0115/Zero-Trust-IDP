import json
import logging
<<<<<<< HEAD
import uuid
=======
>>>>>>> c56df95f91839c06e4d9c285fda960a4e249b796
from typing import List

from kafka import KafkaProducer
from pymongo import MongoClient

from app.config.settings import settings

logger = logging.getLogger(__name__)


class RedriveService:
    def __init__(self):
<<<<<<< HEAD
=======
        # Kafka Producer
>>>>>>> c56df95f91839c06e4d9c285fda960a4e249b796
        self.producer = KafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )

<<<<<<< HEAD
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
=======
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

>>>>>>> c56df95f91839c06e4d9c285fda960a4e249b796
        count = 0

        for msg in messages:
            try:
<<<<<<< HEAD
                payload = msg.get("original_payload")  # 🔥 핵심 변경
                if not payload:
                    continue

                payload = dict(payload)

                payload["is_reprocessed"] = True
                payload["severity"] = "WARNING"
                payload["redrive_id"] = redrive_id

                # 🔥 핵심: replay topic 사용
                self.producer.send(settings.KAFKA_TOPIC_REPLAY, payload)

=======
                # Mongo _id 제거
                msg.pop("_id", None)

                # Kafka로 전송
                self.producer.send(settings.KAFKA_TOPIC_MAIN, msg)
>>>>>>> c56df95f91839c06e4d9c285fda960a4e249b796
                count += 1

            except Exception as e:
                logger.error(f"[Redrive] Send error: {e}")

        self.producer.flush()

<<<<<<< HEAD
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
=======
        logger.info(f"[Redrive] {count} messages re-sent to Kafka")

        return count
>>>>>>> c56df95f91839c06e4d9c285fda960a4e249b796
