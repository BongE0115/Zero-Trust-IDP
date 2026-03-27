import logging

from app.services.kafka_consumer import AnomalyKafkaConsumer
from app.config.settings import settings

# 로그 최소화
logging.getLogger().setLevel(logging.ERROR)


def run_replay_consumer():
    print("🚀 Replay Consumer starting...")

    consumer = AnomalyKafkaConsumer(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        topic=settings.KAFKA_TOPIC_REPLAY,  # 🔥 핵심: replay topic
        group_id="replay-consumer-group",
    )

    consumer.start()


if __name__ == "__main__":
    run_replay_consumer()