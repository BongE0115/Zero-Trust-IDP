import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    APP_NAME = os.getenv("APP_NAME", "error-recovery-system")
    APP_ENV = os.getenv("APP_ENV", "dev")

    # ✅ 기본값 추가 (핵심)
    KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    KAFKA_TOPIC_MAIN = os.getenv("KAFKA_TOPIC_MAIN", "anomaly-topic")
    KAFKA_TOPIC_DLQ = os.getenv("KAFKA_TOPIC_DLQ", "anomaly-dlq")

    SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
    SLACK_CHANNEL = os.getenv("SLACK_CHANNEL", "")


settings = Settings()