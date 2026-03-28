import os
from dotenv import load_dotenv

# .env 파일이 있으면 로드합니다.
load_dotenv()

class Settings:
    # =========================
    # App
    # =========================
    APP_NAME: str = os.getenv("APP_NAME", "error-recovery-system")
    APP_ENV: str = os.getenv("APP_ENV", "dev")

    # =========================
    # Kafka
    # =========================
    # 로컬 테스트 시: kubectl port-forward를 통해 localhost:9092 사용
    # 서버 배포 시: 환경 변수로 kafka-service.kafka.svc.cluster.local:9092 주입
    KAFKA_BOOTSTRAP_SERVERS: str = os.getenv(
        "KAFKA_BOOTSTRAP_SERVERS", 
        "localhost:9092"
    )

    KAFKA_TOPIC_MAIN: str = os.getenv("KAFKA_TOPIC_MAIN", "events-main")
    KAFKA_TOPIC_DLQ: str = os.getenv("KAFKA_TOPIC_DLQ", "events-dlq")
    KAFKA_TOPIC_REPLAY: str = os.getenv("KAFKA_TOPIC_REPLAY", "events-replay")

    # =========================
    # MongoDB
    # =========================
    # 로컬 테스트 시: localhost:27017 사용 (포트 포워딩 필요)
    # 서버 배포 시: 환경 변수로 mongodb 주소 주입
    MONGO_URI: str = os.getenv(
        "MONGO_URI", 
        "mongodb://localhost:27017"
    )
    MONGO_DB: str = os.getenv("MONGO_DB", "sandbox_db")
    MONGO_COLLECTION: str = os.getenv("MONGO_COLLECTION", "errors")

    RESET_DB_ON_START: bool = os.getenv(
        "RESET_DB_ON_START", 
        "true"
    ).lower() == "true"

    # =========================
    # Slack
    # =========================
    SLACK_BOT_TOKEN: str = os.getenv("SLACK_BOT_TOKEN", "")
    SLACK_CHANNEL: str = os.getenv("SLACK_CHANNEL", "")


# 싱글톤 객체로 노출
settings = Settings()