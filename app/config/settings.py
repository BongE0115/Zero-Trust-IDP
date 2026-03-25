import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    APP_NAME = os.getenv("APP_NAME", "error-recovery-system")
    APP_ENV = os.getenv("APP_ENV", "dev")

    # Kafka
    KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    KAFKA_TOPIC_MAIN = os.getenv("KAFKA_TOPIC_MAIN", "anomaly-topic")
    KAFKA_TOPIC_DLQ = os.getenv("KAFKA_TOPIC_DLQ", "anomaly-dlq")

    # MongoDB
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    MONGO_DB = os.getenv("MONGO_DB", "sandbox_db")
    MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "errors")

    # Slack
    SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
    SLACK_CHANNEL = os.getenv("SLACK_CHANNEL", "")


settings = Settings()