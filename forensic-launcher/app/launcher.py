from kafka import KafkaProducer, KafkaConsumer
import json
import os
import time
from typing import Any, Dict


def getenv(name: str, default: str = "") -> str:
    return os.getenv(name, default)


KAFKA_BOOTSTRAP = getenv("KAFKA_BOOTSTRAP", "kafka.kafka-poc.svc.cluster.local:9092")
CASE_ID = getenv("CASE_ID", "")
REPLAY_TOPIC = getenv("REPLAY_TOPIC", "")
RESULT_TOPIC = getenv("RESULT_TOPIC", "")
RESULT_GROUP_ID = getenv("RESULT_GROUP_ID", f"forensic-launcher-{CASE_ID}")
FAILURE_ARTIFACT_PATH = getenv("FAILURE_ARTIFACT_PATH", "/artifacts/failure.json")
NORMAL_ARTIFACT_PATH = getenv("NORMAL_ARTIFACT_PATH", "/artifacts/normal.json")
VERDICT_FILE_PATH = getenv("VERDICT_FILE_PATH", "/artifacts/verdict.json")
ENABLE_NORMAL_VALIDATION = getenv("ENABLE_NORMAL_VALIDATION", "false").lower() == "true"

READY_FILE_PATH = getenv("READY_FILE_PATH", "/artifacts/consumer-ready.json")
READY_WAIT_SECONDS = int(getenv("READY_WAIT_SECONDS", "90"))
BETWEEN_FAILURE_AND_NORMAL_SECONDS = int(getenv("BETWEEN_FAILURE_AND_NORMAL_SECONDS", "10"))
PRODUCER_RETRY_COUNT = int(getenv("PRODUCER_RETRY_COUNT", "30"))
PRODUCER_RETRY_INTERVAL_SECONDS = int(getenv("PRODUCER_RETRY_INTERVAL_SECONDS", "2"))
RESULT_WAIT_SECONDS = int(getenv("RESULT_WAIT_SECONDS", "60"))
EXPECTED_FAILURE_ERROR_TYPE = getenv("EXPECTED_FAILURE_ERROR_TYPE", "")
ISOLATION_MODE = getenv("ISOLATION_MODE", "disabled")
ALLOWED_REPLAY_TOPIC = getenv("ALLOWED_REPLAY_TOPIC", "")
ALLOWED_RESULT_TOPIC = getenv("ALLOWED_RESULT_TOPIC", "")

def load_json_file(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"artifact file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError(f"artifact file must contain a JSON object: {path}")

    return data


def get_producer() -> KafkaProducer:
    last_error = None
    for attempt in range(1, PRODUCER_RETRY_COUNT + 1):
        try:
            producer = KafkaProducer(
                bootstrap_servers=KAFKA_BOOTSTRAP,
                value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8")
            )
            print(f"[LAUNCHER] Kafka producer ready on attempt={attempt}")
            return producer
        except Exception as e:
            last_error = e
            print(f"[LAUNCHER][WARN] Kafka producer init failed attempt={attempt}: {e}")
            time.sleep(PRODUCER_RETRY_INTERVAL_SECONDS)

    raise RuntimeError(f"Kafka producer init failed after retries: {last_error}")


def get_result_consumer() -> KafkaConsumer:
    last_error = None
    for attempt in range(1, PRODUCER_RETRY_COUNT + 1):
        try:
            consumer = KafkaConsumer(
                RESULT_TOPIC,
                bootstrap_servers=KAFKA_BOOTSTRAP,
                group_id=RESULT_GROUP_ID,
                auto_offset_reset="latest",
                enable_auto_commit=True,
                consumer_timeout_ms=1000,
                value_deserializer=lambda m: json.loads(m.decode("utf-8"))
            )
            print(f"[LAUNCHER] Result consumer ready on attempt={attempt}")
            return consumer
        except Exception as e:
            last_error = e
            print(f"[LAUNCHER][WARN] Result consumer init failed attempt={attempt}: {e}")
            time.sleep(PRODUCER_RETRY_INTERVAL_SECONDS)

    raise RuntimeError(f"Result consumer init failed after retries: {last_error}")


def validate_artifact_common(artifact: Dict[str, Any], expected_type: str):
    if artifact.get("artifact_type") != expected_type:
        raise ValueError(
            f"artifact_type mismatch expected={expected_type} actual={artifact.get('artifact_type')}"
        )

    if CASE_ID and artifact.get("case_id") != CASE_ID:
        raise ValueError(
            f"case_id mismatch expected={CASE_ID} actual={artifact.get('case_id')}"
        )

    if REPLAY_TOPIC and artifact.get("target_topic") != REPLAY_TOPIC:
        raise ValueError(
            f"target_topic mismatch expected={REPLAY_TOPIC} actual={artifact.get('target_topic')}"
        )


def publish_payload(producer: KafkaProducer, topic: str, payload: Dict[str, Any], label: str):
    if ISOLATION_MODE == "sandbox_strict":
        if topic != ALLOWED_REPLAY_TOPIC:
            raise ValueError(
                f"launcher isolation blocked publish expected={ALLOWED_REPLAY_TOPIC} actual={topic}"
            )

    print(f"[LAUNCHER] publishing label={label} topic={topic} payload={json.dumps(payload, ensure_ascii=False)}")
    producer.send(topic, payload)
    producer.flush()
    print(f"[LAUNCHER] published label={label} topic={topic}")


def wait_for_phase_result(result_consumer: KafkaConsumer, phase: str) -> Dict[str, Any]:
    deadline = time.time() + RESULT_WAIT_SECONDS

    while time.time() < deadline:
        for message in result_consumer:
            event = message.value
            print(f"[LAUNCHER] observed result event={json.dumps(event, ensure_ascii=False)}")

            if event.get("case_id") != CASE_ID:
                continue
            if event.get("phase") != phase:
                continue
            return event

        time.sleep(1)

    raise TimeoutError(f"result timeout phase={phase} wait_seconds={RESULT_WAIT_SECONDS}")

def validate_launcher_isolation():
    if ISOLATION_MODE != "sandbox_strict":
        print(f"[WARN] launcher isolation mode is not strict: {ISOLATION_MODE}")
        return

    if not CASE_ID:
        raise ValueError("launcher isolation requires CASE_ID")

    if not ALLOWED_REPLAY_TOPIC:
        raise ValueError("launcher isolation requires ALLOWED_REPLAY_TOPIC")

    if not ALLOWED_RESULT_TOPIC:
        raise ValueError("launcher isolation requires ALLOWED_RESULT_TOPIC")

    if REPLAY_TOPIC != ALLOWED_REPLAY_TOPIC:
        raise ValueError(
            f"launcher REPLAY_TOPIC mismatch expected={ALLOWED_REPLAY_TOPIC} actual={REPLAY_TOPIC}"
        )

    if RESULT_TOPIC != ALLOWED_RESULT_TOPIC:
        raise ValueError(
            f"launcher RESULT_TOPIC mismatch expected={ALLOWED_RESULT_TOPIC} actual={RESULT_TOPIC}"
        )

    print(
        f"[ISOLATION] launcher strict sandbox isolation validated "
        f"case_id={CASE_ID} replay_topic={ALLOWED_REPLAY_TOPIC} result_topic={ALLOWED_RESULT_TOPIC}"
    )


def write_verdict(verdict: Dict[str, Any]):
    os.makedirs(os.path.dirname(VERDICT_FILE_PATH), exist_ok=True)
    with open(VERDICT_FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(verdict, f, ensure_ascii=False, indent=2)
    print(f"[LAUNCHER] verdict written path={VERDICT_FILE_PATH}")


def wait_for_consumer_ready():
    deadline = time.time() + READY_WAIT_SECONDS

    while time.time() < deadline:
        if os.path.exists(READY_FILE_PATH):
            try:
                with open(READY_FILE_PATH, "r", encoding="utf-8") as f:
                    ready_data = json.load(f)

                print(f"[LAUNCHER] observed ready file={json.dumps(ready_data, ensure_ascii=False)}")

                if CASE_ID and ready_data.get("case_id") != CASE_ID:
                    print(
                        f"[LAUNCHER][WARN] ready file case_id mismatch "
                        f"expected={CASE_ID} actual={ready_data.get('case_id')}"
                    )
                    time.sleep(1)
                    continue

                if REPLAY_TOPIC and ready_data.get("source_topic") != REPLAY_TOPIC:
                    print(
                        f"[LAUNCHER][WARN] ready file source_topic mismatch "
                        f"expected={REPLAY_TOPIC} actual={ready_data.get('source_topic')}"
                    )
                    time.sleep(1)
                    continue

                print(f"[LAUNCHER] consumer readiness confirmed path={READY_FILE_PATH}")
                return ready_data

            except Exception as e:
                print(f"[LAUNCHER][WARN] failed to read ready file: {e}")

        time.sleep(1)

    raise TimeoutError(
        f"consumer readiness timeout path={READY_FILE_PATH} wait_seconds={READY_WAIT_SECONDS}"
    )


def validate_failure_result(event: Dict[str, Any]):
    if event.get("status") != "failed":
        raise ValueError(f"failure replay expected failed but got {event.get('status')}")

    if EXPECTED_FAILURE_ERROR_TYPE:
        actual = event.get("observed_error_type", "")
        if actual != EXPECTED_FAILURE_ERROR_TYPE:
            raise ValueError(
                f"failure replay error type mismatch expected={EXPECTED_FAILURE_ERROR_TYPE} actual={actual}"
            )


def validate_normal_result(event: Dict[str, Any]):
    if event.get("status") != "success":
        raise ValueError(f"normal validation expected success but got {event.get('status')}")


def main():
    print(
        f"[LAUNCHER] started case_id={CASE_ID}, replay_topic={REPLAY_TOPIC}, "
        f"result_topic={RESULT_TOPIC}, failure_artifact={FAILURE_ARTIFACT_PATH}, "
        f"normal_artifact={NORMAL_ARTIFACT_PATH}, enable_normal_validation={ENABLE_NORMAL_VALIDATION}, "
        f"ready_file_path={READY_FILE_PATH}, ready_wait_seconds={READY_WAIT_SECONDS}, "
        f"isolation_mode={ISOLATION_MODE}, allowed_replay_topic={ALLOWED_REPLAY_TOPIC}, "
        f"allowed_result_topic={ALLOWED_RESULT_TOPIC}"
    )
    validate_launcher_isolation()
    
    print(
        f"[LAUNCHER] waiting for consumer readiness "
        f"path={READY_FILE_PATH} wait_seconds={READY_WAIT_SECONDS}"
    )
    wait_for_consumer_ready()

    if not RESULT_TOPIC:
        raise ValueError("RESULT_TOPIC is required")

    failure_artifact = load_json_file(FAILURE_ARTIFACT_PATH)
    validate_artifact_common(failure_artifact, "failure_replay")

    producer = get_producer()
    result_consumer = get_result_consumer()

    verdict = {
        "case_id": CASE_ID,
        "failure_replay": {"passed": False, "result": None},
        "normal_validation": {"passed": False, "result": None},
        "final_status": "running",
    }

    failure_topic = failure_artifact["target_topic"]
    failure_payload = failure_artifact.get("payload", {}) or {}
    if not failure_payload:
        raise ValueError("failure replay payload is empty")

    publish_payload(producer, failure_topic, failure_payload, "failure_replay")
    failure_result = wait_for_phase_result(result_consumer, "failure_replay")
    validate_failure_result(failure_result)
    verdict["failure_replay"] = {"passed": True, "result": failure_result}

    if not ENABLE_NORMAL_VALIDATION:
        verdict["final_status"] = "passed"
        write_verdict(verdict)
        producer.close()
        result_consumer.close()
        print("[LAUNCHER] normal validation disabled, exiting after verified failure replay")
        return

    normal_artifact = load_json_file(NORMAL_ARTIFACT_PATH)
    validate_artifact_common(normal_artifact, "normal_validation")

    if not normal_artifact.get("enabled", False):
        verdict["final_status"] = "passed"
        write_verdict(verdict)
        producer.close()
        result_consumer.close()
        print("[LAUNCHER] normal validation artifact present but disabled, exiting")
        return

    normal_topic = normal_artifact["target_topic"]
    normal_payload = normal_artifact.get("payload", {}) or {}
    if not normal_payload:
        verdict["final_status"] = "passed"
        write_verdict(verdict)
        producer.close()
        result_consumer.close()
        print("[LAUNCHER] normal validation enabled but payload empty, skipping")
        return

    print(f"[LAUNCHER] waiting {BETWEEN_FAILURE_AND_NORMAL_SECONDS}s before normal validation publish")
    time.sleep(BETWEEN_FAILURE_AND_NORMAL_SECONDS)

    publish_payload(producer, normal_topic, normal_payload, "normal_validation")
    normal_result = wait_for_phase_result(result_consumer, "normal_validation")
    validate_normal_result(normal_result)
    verdict["normal_validation"] = {"passed": True, "result": normal_result}

    verdict["final_status"] = "passed"
    write_verdict(verdict)

    producer.close()
    result_consumer.close()
    print("[LAUNCHER] completed replay orchestration with verdict=passed")


if __name__ == "__main__":
    main()