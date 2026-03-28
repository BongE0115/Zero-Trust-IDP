import logging
import time
<<<<<<< HEAD
=======
import os
>>>>>>> c56df95f91839c06e4d9c285fda960a4e249b796
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from pymongo import MongoClient
from app.aiops.merlion_detector import MerlionAnomalyDetector
<<<<<<< HEAD
from app.config.settings import settings
=======
from app.config.settings import settings  # ✅ 추가
>>>>>>> c56df95f91839c06e4d9c285fda960a4e249b796

logger = logging.getLogger(__name__)


# ==============================
# 🔥 Mongo Repository
# ==============================
class MongoDLQRepository:
    def __init__(
        self,
        mongo_uri: Optional[str] = None,
<<<<<<< HEAD
        db_name: str = settings.MONGO_DB,
        collection_name: str = "cases",  # 🔥 핵심 변경
    ):
        if mongo_uri is None:
            mongo_uri = settings.MONGO_URI
=======
        db_name: str = settings.MONGO_DB,              # ✅ 변경
        collection_name: str = settings.MONGO_COLLECTION,  # ✅ 변경
    ):
        if mongo_uri is None:
            mongo_uri = settings.MONGO_URI  # ✅ 변경
>>>>>>> c56df95f91839c06e4d9c285fda960a4e249b796

        self.client = MongoClient(mongo_uri)
        self.db = self.client[db_name]
        self.collection = self.db[collection_name]

    def _floor_time(self, dt: datetime, interval_seconds: int) -> datetime:
        ts = int(dt.timestamp())
        floored = ts - (ts % interval_seconds)
        return datetime.utcfromtimestamp(floored)

    def get_aggregated_errors(
        self,
        minutes: int = 10,
        interval_seconds: int = 30,
    ) -> List[Dict]:

        now = datetime.utcnow()
        start_time = now - timedelta(minutes=minutes)

        pipeline = [
            {
                "$match": {
                    "created_at": {"$gte": start_time}
                }
            },
            {
                "$group": {
                    "_id": {
                        "$toDate": {
                            "$subtract": [
                                {"$toLong": "$created_at"},
                                {
                                    "$mod": [
                                        {"$toLong": "$created_at"},
                                        interval_seconds * 1000
                                    ]
                                }
                            ]
                        }
                    },
                    "count": {"$sum": 1}
                }
            },
            {"$sort": {"_id": 1}}
        ]

        results = list(self.collection.aggregate(pipeline))

<<<<<<< HEAD
=======
        # ✅ 🔥 핵심 수정: Mongo 데이터 없으면 바로 return
>>>>>>> c56df95f91839c06e4d9c285fda960a4e249b796
        if not results:
            return []

        result_map = {
            r["_id"].replace(tzinfo=None): r["count"]
            for r in results
        }

        current = self._floor_time(start_time, interval_seconds)
        end = self._floor_time(now, interval_seconds)

        aggregated_data = []
        while current <= end:
            aggregated_data.append({
                "timestamp": current,
                "value": result_map.get(current, 0)
            })
            current += timedelta(seconds=interval_seconds)

        return aggregated_data


# ==============================
# 🔥 Slack 알림
# ==============================
def send_slack_alert(result: Dict):
<<<<<<< HEAD
    slack_token = settings.SLACK_BOT_TOKEN
    channel = settings.SLACK_CHANNEL

    if not slack_token or not channel:
        logger.warning("[Slack] Bot token or channel not set")
        return

    url = "https://slack.com/api/chat.postMessage"

    headers = {
        "Authorization": f"Bearer {slack_token}",
        "Content-Type": "application/json"
    }

    text = (
        f"🚨 *AIOps Anomaly Detected!*\n"
        f"- Score: {result['score']}\n"
        f"- Data Points: {result['data_points']}\n"
        f"- Status: {'ANOMALY' if result['is_anomaly'] else 'NORMAL'}"
    )

    data = {
        "channel": channel,
        "text": text,
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": text
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "🔁 재처리 실행"
                        },
                        "style": "primary",
                        "value": "redrive",
                        "action_id": "redrive_button"
                    }
                ]
            }
        ]
    }

    try:
        response = requests.post(url, headers=headers, json=data, timeout=3)
        logger.info(f"[Slack] response: {response.text}")
=======
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")

    if not webhook_url:
        logger.warning("[Slack] Webhook URL not set")
        return

    message = {
        "text": (
            f"🚨 *AIOps Anomaly Detected!*\n"
            f"- Score: {result['score']}\n"
            f"- Data Points: {result['data_points']}\n"
            f"- Status: {'ANOMALY' if result['is_anomaly'] else 'NORMAL'}"
        )
    }

    try:
        requests.post(webhook_url, json=message, timeout=3)
>>>>>>> c56df95f91839c06e4d9c285fda960a4e249b796
    except Exception as e:
        logger.error(f"[Slack] Send error: {e}")


# ==============================
# 🔥 AIOps Service
# ==============================
class AIOpsService:
    def __init__(self, persistence: int = 1):
        self.detector = MerlionAnomalyDetector(persistence=persistence)
        self.prev_anomaly = False
        self.last_alert_time = 0

    def run_detection(self, time_series_data: List[Dict]) -> Dict[str, Optional[float]]:

        if len(time_series_data) < 5:
<<<<<<< HEAD
            logger.warning("[AIOps] Not enough data")
=======
            logger.warning("[AIOps] Not enough data to run detection")
>>>>>>> c56df95f91839c06e4d9c285fda960a4e249b796
            return {
                "trained": False,
                "score": None,
                "is_anomaly": False,
                "data_points": len(time_series_data),
            }

        if not self.detector.is_trained:
<<<<<<< HEAD
            logger.info("[AIOps] Training model...")
=======
            logger.info("[AIOps] Training Merlion model...")
>>>>>>> c56df95f91839c06e4d9c285fda960a4e249b796
            self.detector.train(time_series_data)

        score = self.detector.detect(time_series_data)
        is_anomaly = self.detector.is_anomaly(score)

        return {
            "trained": self.detector.is_trained,
            "score": score,
            "is_anomaly": is_anomaly,
            "data_points": len(time_series_data),
        }


# ==============================
# 🔥 Loop
# ==============================
def run_aiops_loop(interval_seconds: int = 30, minutes: int = 10):

<<<<<<< HEAD
    logger.info("[AIOps] Starting loop...")

    repo = MongoDLQRepository()
    aiops = AIOpsService()

    COOLDOWN = 60
    last_data_count = 0
=======
    logger.info("[AIOps] Starting AIOps loop...")

    # 🔥 Mongo 연결 보호 (추가 안정성)
    try:
        repo = MongoDLQRepository()
    except Exception as e:
        logger.error(f"[Mongo] Connection error: {e}")
        return

    aiops = AIOpsService()

    COOLDOWN = 60
>>>>>>> c56df95f91839c06e4d9c285fda960a4e249b796

    while True:
        try:
            data = repo.get_aggregated_errors(
                minutes=minutes,
                interval_seconds=interval_seconds,
            )

<<<<<<< HEAD
            if len(data) == last_data_count:
                time.sleep(interval_seconds)
                continue

            last_data_count = len(data)

            if data:
=======
            logger.info(f"[AIOps] Aggregated data count: {len(data)}")

            if not data:
                logger.warning("[AIOps] No DLQ data found in MongoDB")
            else:
>>>>>>> c56df95f91839c06e4d9c285fda960a4e249b796
                result = aiops.run_detection(data)

                print("\n===== AIOps Detection Result =====")
                print(f"Data points : {result['data_points']}")
<<<<<<< HEAD
=======
                print(f"Trained     : {result['trained']}")
>>>>>>> c56df95f91839c06e4d9c285fda960a4e249b796
                print(f"Score       : {result['score']}")
                print(f"Is Anomaly  : {result['is_anomaly']}")
                print("==================================\n")

                now = time.time()

                if result["is_anomaly"]:
                    state_changed = not aiops.prev_anomaly
                    cooldown_ok = (now - aiops.last_alert_time) > COOLDOWN

                    if state_changed or cooldown_ok:
                        send_slack_alert(result)
                        aiops.last_alert_time = now

                aiops.prev_anomaly = result["is_anomaly"]

        except Exception as e:
            logger.error(f"[AIOps] Loop error: {e}")

        time.sleep(interval_seconds)