import json
import logging
from datetime import datetime

from kafka import KafkaConsumer
from pymongo import MongoClient

<<<<<<< HEAD
from app.config.settings import settings
=======
from app.config.settings import settings  # ✅ 환경 통일
>>>>>>> c56df95f91839c06e4d9c285fda960a4e249b796

logging.getLogger().setLevel(logging.ERROR)
logger = logging.getLogger(__name__)


class DLQKafkaConsumer:
    def __init__(self, bootstrap_servers: str, topic: str, group_id: str):
        self.topic = topic
<<<<<<< HEAD

        # Kafka Consumer
=======
        self.total_count = 0
        self.last_printed = 0

        # 🔥 Kafka Consumer (offset 문제 해결 포함)
>>>>>>> c56df95f91839c06e4d9c285fda960a4e249b796
        self.consumer = KafkaConsumer(
            self.topic,
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
<<<<<<< HEAD
            auto_offset_reset="latest",
=======
            auto_offset_reset="latest",  # ✅ 과거 데이터 무시
>>>>>>> c56df95f91839c06e4d9c285fda960a4e249b796
            enable_auto_commit=True,
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        )

<<<<<<< HEAD
        # Mongo
        self.mongo_client = MongoClient(settings.MONGO_URI)
        self.mongo_db = self.mongo_client[settings.MONGO_DB]
        self.mongo_collection = self.mongo_db["cases"]  # 🔥 핵심 변경
=======
        # 🔥 Mongo (settings 기반 통일)
        self.mongo_client = MongoClient(settings.MONGO_URI)
        self.mongo_db = self.mongo_client[settings.MONGO_DB]
        self.mongo_collection = self.mongo_db[settings.MONGO_COLLECTION]
>>>>>>> c56df95f91839c06e4d9c285fda960a4e249b796

    def start(self):
        print("🔥 DLQ Consumer started")
        print(f"📦 MongoDB URI: {settings.MONGO_URI}")
        print(f"📂 DB: {self.mongo_db.name}, Collection: {self.mongo_collection.name}")

        for message in self.consumer:
            try:
                data = message.value

<<<<<<< HEAD
                # 🔥 DLQ 구조 그대로 사용
                case_id = self.generate_case_id()

                case_doc = {
                    "case_id": case_id,
                    "status": "detected",
                    "source_service": data.get("source_service"),
                    "source_topic": data.get("source_topic"),
                    "consumer_group": data.get("consumer_group"),
                    "image_tag": data.get("image_tag"),
                    "error_type": data.get("error_type"),
                    "timestamp": data.get("timestamp"),
                    "original_payload": data.get("original_payload"),
                    "created_at": datetime.utcnow(),
                    "sandbox_namespace": None,
                }

                self.mongo_collection.insert_one(case_doc)

                print(f"🚨 Case Created: {case_id}", flush=True)

            except Exception as e:
                logger.error(f"[DLQ Consumer] Error: {e}")

    def generate_case_id(self):
        now = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        return f"case-{now}"
=======
                # 🔥 success 필터링
                if "success" in data and data["success"] is not False:
                    continue

                doc = {
                    "service": data.get("service", "unknown"),
                    "error_type": data.get("error_type", "unknown"),
                    "payload": data.get("payload", {}),
                    "created_at": datetime.utcnow(),
                }

                self.mongo_collection.insert_one(doc)

                self.total_count += 1

                # 🔥 로그 간격 출력
                if self.total_count // 10 > self.last_printed:
                    self.last_printed = self.total_count // 10
                    print(f"📥 MongoDB 저장 완료: {self.last_printed * 10}", flush=True)

            except Exception as e:
                logger.error(f"[DLQ Consumer] Error: {e}")
>>>>>>> c56df95f91839c06e4d9c285fda960a4e249b796
