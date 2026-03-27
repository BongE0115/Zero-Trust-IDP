# app/consumer_runner.py

import threading

from app.services.kafka_consumer import AnomalyKafkaConsumer
from app.services.dlq_consumer import DLQKafkaConsumer
from app.config.settings import settings


def start_main_consumer():
    consumer = AnomalyKafkaConsumer(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        topic=settings.KAFKA_TOPIC_MAIN,
        group_id="anomaly-consumer-group",
    )
    consumer.start()


def start_dlq_consumer():
    dlq_consumer = DLQKafkaConsumer(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        topic=settings.KAFKA_TOPIC_DLQ,
        group_id="dlq-consumer-group",
    )
    dlq_consumer.start()


if __name__ == "__main__":
    print("🚀 Consumer Pod Starting...")

    # 🔥 Main Consumer
    threading.Thread(target=start_main_consumer, daemon=True).start()
    print("✅ Main Consumer Thread Started")

    # 🔥 DLQ Consumer
    threading.Thread(target=start_dlq_consumer, daemon=True).start()
    print("✅ DLQ Consumer Thread Started")

    # 🔥 계속 살아있게 유지
    while True:
        pass