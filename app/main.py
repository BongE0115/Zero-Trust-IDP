from fastapi import FastAPI
<<<<<<< HEAD
from app.routes import test_routes, redrive_routes, slack_routes
=======
from app.routes import test_routes
from app.routes import redrive_routes  # ✅ 추가
>>>>>>> c56df95f91839c06e4d9c285fda960a4e249b796

import logging
from pymongo import MongoClient

<<<<<<< HEAD
=======
from app.services.kafka_consumer import AnomalyKafkaConsumer
from app.services.dlq_consumer import DLQKafkaConsumer
from app.services.aiops_service import run_aiops_loop
>>>>>>> c56df95f91839c06e4d9c285fda960a4e249b796
from app.config.settings import settings

# 🔥 Uvicorn access log 제거 (터미널을 깔끔하게 유지합니다)
logging.getLogger("uvicorn.access").disabled = True

app = FastAPI()

# ==============================
# ✅ 라우터 등록
# ==============================
# API 엔드포인트와 Slack 대화형 버튼 처리를 담당합니다.
app.include_router(test_routes.router)
<<<<<<< HEAD
app.include_router(redrive_routes.router)
app.include_router(slack_routes.router)


# ==============================
# 🧹 DB 초기화 (개발용)
# ==============================
def reset_db_if_needed():
    if settings.RESET_DB_ON_START:
        try:
            client = MongoClient(settings.MONGO_URI)
            db = client[settings.MONGO_DB]
            db[settings.MONGO_COLLECTION].delete_many({})
            print("🧹 MongoDB 초기화 완료 (Backend)")
        except Exception as e:
            print(f"❌ DB 초기화 실패: {e}")


# ==============================
# 🚀 Startup
# ==============================
@app.on_event("startup")
def start_services():
    print("🔥 Backend Service startup called")
    
    # DB 초기화는 API 서버가 시작될 때 수행하도록 유지합니다.
    reset_db_if_needed()
    
    # 💡 [변경사항] 
    # 기존에 여기서 실행되던 AIOps(run_aiops_loop) 쓰레드는 삭제되었습니다.
    # 이제 이 로직은 aiops_runner.py가 담당하여 독립된 파드로 실행됩니다.
    print("✅ Backend API Gateway is ready")


# ==============================
# Root
# ==============================
=======
app.include_router(redrive_routes.router)  # ✅ 추가


@app.on_event("startup")
def start_services():
    print("🔥 Service startup called")

    # 🔹 Main Kafka Consumer
    try:
        consumer = AnomalyKafkaConsumer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            topic=settings.KAFKA_TOPIC_MAIN,
            group_id="anomaly-consumer-group",
        )
        threading.Thread(target=consumer.start, daemon=True).start()
        print("✅ Main Kafka Consumer started")

    except Exception as e:
        print(f"❌ Main Kafka Consumer error: {e}")

    # 🔥 DLQ Consumer
    try:
        dlq_consumer = DLQKafkaConsumer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            topic=settings.KAFKA_TOPIC_DLQ,
            group_id="dlq-consumer-group-v2",
        )
        threading.Thread(target=dlq_consumer.start, daemon=True).start()
        print("✅ DLQ Kafka Consumer started")

    except Exception as e:
        print(f"❌ DLQ Kafka Consumer error: {e}")

    # 🧠 AIOps (MongoDB → Merlion)
    try:
        threading.Thread(
            target=run_aiops_loop,
            kwargs={"interval_seconds": 30, "minutes": 10},
            daemon=True,
        ).start()
        print("✅ AIOps loop started")

    except Exception as e:
        print(f"❌ AIOps loop error: {e}")


>>>>>>> c56df95f91839c06e4d9c285fda960a4e249b796
@app.get("/")
def root():
    return {"message": "Error Recovery System Backend is running"}