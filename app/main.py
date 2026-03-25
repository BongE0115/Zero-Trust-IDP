from fastapi import FastAPI
from app.routes import test_routes
from app.routes import redrive_routes  # ✅ 추가

import threading
import logging

from app.services.kafka_consumer import AnomalyKafkaConsumer
from app.services.dlq_consumer import DLQKafkaConsumer
from app.services.aiops_service import run_aiops_loop
from app.config.settings import settings

# 🔥 Uvicorn access log 제거
logging.getLogger("uvicorn.access").disabled = True

app = FastAPI()

# 라우터 등록
app.include_router(test_routes.router)
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


@app.get("/")
def root():
    return {"message": "Error Recovery System is running"}