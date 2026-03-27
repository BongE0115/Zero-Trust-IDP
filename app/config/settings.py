import os
from dotenv import load_dotenv

# .env 로드
load_dotenv()


class Settings:
    # =========================
    # App
    # =========================
    APP_NAME = os.getenv("APP_NAME", "error-recovery-system")
    APP_ENV = os.getenv("APP_ENV", "dev")

<<<<<<< HEAD
    # =========================
    # Kafka
    # =========================
    KAFKA_BOOTSTRAP_SERVERS = os.getenv(
        "KAFKA_BOOTSTRAP_SERVERS",
        "localhost:9092"  # 👉 로컬 기본값 (k8s에서는 env로 덮어씀)
    )

    KAFKA_TOPIC_MAIN = os.getenv(
        "KAFKA_TOPIC_MAIN",
        "events-main"
    )

    KAFKA_TOPIC_DLQ = os.getenv(
        "KAFKA_TOPIC_DLQ",
        "events-dlq"
    )

    KAFKA_TOPIC_REPLAY = os.getenv(
        "KAFKA_TOPIC_REPLAY",
        "events-replay"
    )

    # =========================
    # MongoDB
    # =========================
    MONGO_URI = os.getenv(
        "MONGO_URI",
        "mongodb://localhost:27017"  # 👉 로컬 기본값
    )

    MONGO_DB = os.getenv("MONGO_DB", "sandbox_db")
    MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "errors")

    RESET_DB_ON_START = os.getenv(
        "RESET_DB_ON_START",
        "true"
    ).lower() == "true"

    # =========================
    # Slack
    # =========================
=======
    # Kafka
    KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    KAFKA_TOPIC_MAIN = os.getenv("KAFKA_TOPIC_MAIN", "anomaly-topic")
    KAFKA_TOPIC_DLQ = os.getenv("KAFKA_TOPIC_DLQ", "anomaly-dlq")

    # MongoDB
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    MONGO_DB = os.getenv("MONGO_DB", "sandbox_db")
    MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "errors")

    # Slack
>>>>>>> c56df95f91839c06e4d9c285fda960a4e249b796
    SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
    SLACK_CHANNEL = os.getenv("SLACK_CHANNEL", "")


# 싱글톤 객체
settings = Settings()