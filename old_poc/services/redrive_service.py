import json
import logging
import uuid
import time
from typing import List
from kafka import KafkaProducer
from pymongo import MongoClient
from app.config.settings import settings

logger = logging.getLogger(__name__)

class RedriveService:
    def __init__(self):
        # 1. Kafka Producer 설정
        self.producer = KafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )

        # 2. MongoDB 설정
        self.client = MongoClient(settings.MONGO_URI)
        self.db = self.client[settings.MONGO_DB]
        
        # 장애 데이터가 쌓인 'cases' 컬렉션 (샌드박스용)
        self.collection = self.db["cases"]
        # 재처리 결과를 기록하는 컬렉션
        self.result_collection = self.db["redrive_results"]

    def fetch_failed_messages(self, limit: int = 50) -> List[dict]:
        """
        분석을 위해 MongoDB에 보관 중인 실패 메시지들을 가져옵니다.
        """
        return list(self.collection.find().limit(limit))

    def redrive(self, limit: int = 50) -> dict:
        """
        실패한 데이터를 수정/보완하여 다시 Replay 토픽으로 전송합니다.
        """
        messages = self.fetch_failed_messages(limit)

        if not messages:
            logger.warning("[Redrive] 재처리할 메시지가 없습니다.")
            return {"reprocessed": 0, "success": 0, "failed": 0}

        # 이번 재처리 세션을 식별할 고유 ID 생성
        redrive_id = str(uuid.uuid4())
        count = 0

        for msg in messages:
            try:
                # MongoDB의 _id 제거 (JSON 직렬화 및 중복 방지)
                msg.pop("_id", None)
                
                # DLQ 메타데이터에서 원본 데이터(payload) 추출
                payload = msg.get("original_payload")
                if not payload:
                    continue

                # 데이터 변환: 재처리 플래그 및 ID 삽입
                payload = dict(payload)
                payload["is_reprocessed"] = True
                payload["redrive_id"] = redrive_id
                
                # 시나리오 A를 위해 위험도를 낮춰서 재시도 (선택 사항)
                payload["severity"] = "WARNING" 

                # ✅ 핵심: 운영 토픽이 아닌 REPLAY 토픽으로 전송하여 안전하게 검증
                self.producer.send(settings.KAFKA_TOPIC_REPLAY, payload)
                count += 1

            except Exception as e:
                logger.error(f"[Redrive] 전송 실패: {e}")

        self.producer.flush()
        logger.info(f"[Redrive] {count}개의 메시지를 {settings.KAFKA_TOPIC_REPLAY} 토픽으로 전송 완료 (ID: {redrive_id})")

        # 3. 결과 집계 (Consumer가 처리할 시간을 잠시 기다림)
        # 실제 운영 환경에서는 비동기로 확인하지만, PoC를 위해 잠시 대기합니다.
        time.sleep(3)

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