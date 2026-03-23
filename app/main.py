from fastapi import FastAPI
from app.routes import test_routes

import threading
import logging

from app.services.kafka_consumer import AnomalyKafkaConsumer
from app.services.dlq_consumer import DLQKafkaConsumer

# 🔥 Uvicorn access log 제거
logging.getLogger("uvicorn.access").disabled = True

app = FastAPI()

# 라우터 등록
app.include_router(test_routes.router)


@app.on_event("startup")
def start_kafka_consumer():
    print("🔥 Consumer startup called")

    # 🔹 Main Kafka Consumer
    try:
        consumer = AnomalyKafkaConsumer(
            bootstrap_servers="localhost:9092",
            topic="anomaly-topic",
            group_id="anomaly-consumer-group",
        )
        threading.Thread(target=consumer.start, daemon=True).start()
        print("✅ Main Kafka Consumer started")

    except Exception as e:
        print(f"❌ Main Kafka Consumer error: {e}")

    # 🔥 DLQ Consumer
    try:
        dlq_consumer = DLQKafkaConsumer(
            bootstrap_servers="localhost:9092",
            topic="anomaly-dlq",
            group_id="dlq-consumer-group",
        )
        threading.Thread(target=dlq_consumer.start, daemon=True).start()
        print("✅ DLQ Kafka Consumer started")

    except Exception as e:
        print(f"❌ DLQ Kafka Consumer error: {e}")


@app.get("/")
def root():
    return {"message": "Error Recovery System is running"}