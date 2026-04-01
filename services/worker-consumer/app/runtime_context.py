import os


def getenv(name: str, default: str = "") -> str:
    return os.getenv(name, default)


class Settings:
    KAFKA_BOOTSTRAP = getenv("KAFKA_BOOTSTRAP", "kafka.kafka-poc.svc.cluster.local:9092")
    SOURCE_TOPIC = getenv("SOURCE_TOPIC", "orders")
    DLQ_TOPIC = getenv("DLQ_TOPIC", "orders-dlq")
    GROUP_ID = getenv("GROUP_ID", "worker-consumer")
    SERVICE_NAME = getenv("SERVICE_NAME", "worker-consumer")
    NAMESPACE = getenv("NAMESPACE", "kafka-poc")
    DEPLOYMENT_NAME = getenv("DEPLOYMENT_NAME", "worker-consumer")
    IMAGE_REF = getenv("IMAGE_REF", "unset")
    CONFIG_VERSION = getenv("CONFIG_VERSION", "v1")
    DEPENDENCY_PROFILE = getenv("DEPENDENCY_PROFILE", "default")
    FORCE_FAIL_FIELD = getenv("FORCE_FAIL_FIELD", "should_fail")

    ENABLE_DLQ_PUBLISH = getenv("ENABLE_DLQ_PUBLISH", "true").lower() == "true"
    NORMAL_FIXTURE_PATH = getenv("NORMAL_FIXTURE_PATH", "")
    DB_MODE = getenv("DB_MODE", "mysql")
    DB_HOST = getenv("DB_HOST", "")
    CACHE_MODE = getenv("CACHE_MODE", "disabled")
    CACHE_HOST = getenv("CACHE_HOST", "")
    EXTERNAL_API_MODE = getenv("EXTERNAL_API_MODE", "disabled")
    EXTERNAL_API_BASE_URL = getenv("EXTERNAL_API_BASE_URL", "")

    RUN_MODE = getenv("RUN_MODE", "production")
    CASE_ID = getenv("CASE_ID", "")
    RESULT_TOPIC = getenv("RESULT_TOPIC", "")
    EMIT_RESULT_EVENT = getenv("EMIT_RESULT_EVENT", "false").lower() == "true"
    REPLAY_PAYLOAD_HASH = getenv("REPLAY_PAYLOAD_HASH", "")
    NORMAL_PAYLOAD_HASH = getenv("NORMAL_PAYLOAD_HASH", "")
    READY_FILE_PATH = getenv("READY_FILE_PATH", "")
    ISOLATION_MODE = getenv("ISOLATION_MODE", "disabled")
    ALLOWED_REPLAY_TOPIC = getenv("ALLOWED_REPLAY_TOPIC", "")
    ALLOWED_RESULT_TOPIC = getenv("ALLOWED_RESULT_TOPIC", "")

    VALIDATION_MODE = getenv("VALIDATION_MODE", "reproduce")
    VALIDATION_RUN_ID = getenv("VALIDATION_RUN_ID", "")
    REVALIDATION_GENERATION = int(getenv("REVALIDATION_GENERATION", "0"))
    EXPECTED_FAILURE_STATUS = getenv(
        "EXPECTED_FAILURE_STATUS",
        "failed" if VALIDATION_MODE == "reproduce" else "success",
    )
    EXPECTED_NORMAL_STATUS = getenv("EXPECTED_NORMAL_STATUS", "success")
    FAILURE_ERROR_TYPE = getenv("FAILURE_ERROR_TYPE", "")
    FAILURE_ERROR_MESSAGE = getenv("FAILURE_ERROR_MESSAGE", "")


settings = Settings()