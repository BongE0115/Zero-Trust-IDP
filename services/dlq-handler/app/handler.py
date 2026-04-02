from kafka import KafkaConsumer
import json
import os
import time
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict
import requests


def getenv(name: str, default: str = "") -> str:
    return os.getenv(name, default)


KAFKA_BOOTSTRAP = getenv("KAFKA_BOOTSTRAP", "kafka.kafka-poc.svc.cluster.local:9092")
DLQ_TOPIC = getenv("DLQ_TOPIC", "orders-dlq")
GROUP_ID = getenv("GROUP_ID", "orders-dlq-handler")

SANDBOX_NAMESPACE = getenv("SANDBOX_NAMESPACE", "forensic-sandbox")
SANDBOX_SERVICE_NAME = getenv("SANDBOX_SERVICE_NAME", "forensic-sandbox-app")
SANDBOX_DEPLOYMENT_NAME = getenv("SANDBOX_DEPLOYMENT_NAME", "forensic-sandbox-app")
SANDBOX_LAUNCHER_NAME = getenv("SANDBOX_LAUNCHER_NAME", "forensic-launcher")
SANDBOX_GROUP_ID_PREFIX = getenv("SANDBOX_GROUP_ID_PREFIX", "orders-consumer-sandbox")
SANDBOX_DEPENDENCY_PROFILE = getenv("SANDBOX_DEPENDENCY_PROFILE", "sandbox")

SANDBOX_DB_MODE = getenv("SANDBOX_DB_MODE", "mock")
SANDBOX_DB_HOST = getenv("SANDBOX_DB_HOST", "mongodb-temp.forensic-sandbox.svc.cluster.local")
SANDBOX_CACHE_MODE = getenv("SANDBOX_CACHE_MODE", "mock")
SANDBOX_CACHE_HOST = getenv("SANDBOX_CACHE_HOST", "")
SANDBOX_EXTERNAL_API_MODE = getenv("SANDBOX_EXTERNAL_API_MODE", "mock")
SANDBOX_EXTERNAL_API_BASE_URL = getenv("SANDBOX_EXTERNAL_API_BASE_URL", "")

SANDBOX_REPLICAS = int(getenv("SANDBOX_REPLICAS", "1"))

TOPIC_INIT_IMAGE = getenv("TOPIC_INIT_IMAGE", "bitnami/kafka:3.7")
TOPIC_INIT_PARTITIONS = int(getenv("TOPIC_INIT_PARTITIONS", "1"))
TOPIC_INIT_REPLICATION_FACTOR = int(getenv("TOPIC_INIT_REPLICATION_FACTOR", "1"))

SPEC_OUTPUT_MODE = getenv("SPEC_OUTPUT_MODE", "stdout")  # stdout | file
SPEC_OUTPUT_DIR = getenv("SPEC_OUTPUT_DIR", "/tmp/sandbox-specs")

REPLAY_ARTIFACT_OUTPUT_DIR = getenv("REPLAY_ARTIFACT_OUTPUT_DIR", "/tmp/replay-artifacts")
VALIDATION_ARTIFACT_OUTPUT_DIR = getenv("VALIDATION_ARTIFACT_OUTPUT_DIR", "/tmp/validation-artifacts")

GITHUB_TOKEN = getenv("GITHUB_TOKEN", "")
GITHUB_OWNER = getenv("GITHUB_OWNER", "")
GITHUB_REPO = getenv("GITHUB_REPO", "")
GITHUB_REF = getenv("GITHUB_REF", "jy")

ACTIVATE_SANDBOX_WORKFLOW_FILE = getenv("ACTIVATE_SANDBOX_WORKFLOW_FILE", "activate-sandbox.yaml")
CREATE_CASE_BRANCH_WORKFLOW_FILE = getenv("CREATE_CASE_BRANCH_WORKFLOW_FILE", "create-case-branch.yaml")

ENABLE_GITHUB_DISPATCH = getenv("ENABLE_GITHUB_DISPATCH", "false").lower() == "true"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_of_json(data: Any) -> str:
    return hashlib.sha256(stable_json_dumps(data).encode("utf-8")).hexdigest()


def sanitize_case_id(case_id: str) -> str:
    return "".join(c if c.isalnum() or c == "-" else "-" for c in case_id).lower()


def get_consumer():
    for _ in range(60):
        try:
            return KafkaConsumer(
                DLQ_TOPIC,
                bootstrap_servers=KAFKA_BOOTSTRAP,
                group_id=GROUP_ID,
                auto_offset_reset="earliest",
                enable_auto_commit=True,
                value_deserializer=lambda m: json.loads(m.decode("utf-8"))
            )
        except Exception as e:
            print(f"[WARN] Kafka consumer init failed: {e}")
            time.sleep(2)
    raise RuntimeError("Kafka consumer init failed")


def get_nested(event: Dict[str, Any], *keys, default=None):
    current = event
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    return current


def build_case_id_from_payload(source_service: str, payload: Dict[str, Any]) -> str:
    order_id = str(payload.get("order_id", "unknown-order"))
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    digest = sha256_of_json(payload)[:8]
    return f"{source_service}-{order_id}-{ts}-{digest}"


def normalize_legacy_event(event: Dict[str, Any]) -> Dict[str, Any]:
    if "runtime" in event and "source" in event and "error" in event and "repro_config" in event:
        normalized = dict(event)
        original_payload = normalized.get("original_payload", {}) or {}

        if "case_id" not in normalized:
            normalized["case_id"] = build_case_id_from_payload(
                normalized.get("source", {}).get("service", "unknown-service"),
                original_payload
            )

        if "replay" not in normalized:
            case_id = normalized["case_id"]
            normalized["replay"] = {
                "target_topic": f"orders-replay-{sanitize_case_id(case_id)}",
                "failure_payload_hash": sha256_of_json(original_payload)
            }

        if "validation" not in normalized:
            normal_payload = normalized.get("normal_validation_payload", {}) or {}
            normalized["validation"] = {
                "normal_fixture_available": bool(normal_payload),
                "normal_fixture_path": "",
                "normal_payload_hash": sha256_of_json(normal_payload) if normal_payload else ""
            }

        return normalized

    original_payload = event.get("original_payload", {}) or {}
    source_service = event.get("source_service", "unknown-service")
    case_id = build_case_id_from_payload(source_service, original_payload)
    normal_payload = event.get("normal_validation_payload", {}) or {}

    return {
        "event_type": "consumer_failure",
        "case_id": case_id,
        "detected_at": event.get("timestamp", utc_now_iso()),
        "source": {
            "service": event.get("source_service", "unknown"),
            "namespace": event.get("source_namespace", "unknown"),
            "deployment": event.get("source_deployment", "unknown"),
            "topic": event.get("source_topic", "unknown"),
            "consumer_group": event.get("consumer_group", "unknown")
        },
        "runtime": {
            "image_ref": event.get("image_ref", "unknown"),
            "config_version": event.get("config_version", "unknown"),
            "dependency_profile": event.get("dependency_profile", "unknown")
        },
        "repro_config": {
            "force_fail_field": event.get("force_fail_field", "should_fail"),
            "db_mode": event.get("db_mode", "unknown"),
            "db_host": event.get("db_host", ""),
            "cache_mode": event.get("cache_mode", "unknown"),
            "cache_host": event.get("cache_host", ""),
            "external_api_mode": event.get("external_api_mode", "unknown"),
            "external_api_base_url": event.get("external_api_base_url", "")
        },
        "replay": {
            "target_topic": f"orders-replay-{sanitize_case_id(case_id)}",
            "failure_payload_hash": sha256_of_json(original_payload)
        },
        "validation": {
            "normal_fixture_available": bool(normal_payload),
            "normal_fixture_path": "",
            "normal_payload_hash": sha256_of_json(normal_payload) if normal_payload else ""
        },
        "error": {
            "type": event.get("error_type", "unknown"),
            "message": event.get("error_message", "unknown")
        },
        "original_payload": original_payload,
        "normal_validation_payload": normal_payload,
    }


def print_alert(event: Dict[str, Any]):
    original_payload = event.get("original_payload", {}) or {}

    print("=" * 100)
    print("[ALERT] DLQ failure event detected")
    print(f"[ALERT] detected_at={utc_now_iso()}")
    print(f"[ALERT] case_id={event.get('case_id', 'unknown')}")
    print(f"[ALERT] source_service={get_nested(event, 'source', 'service', default='unknown')}")
    print(f"[ALERT] source_namespace={get_nested(event, 'source', 'namespace', default='unknown')}")
    print(f"[ALERT] source_deployment={get_nested(event, 'source', 'deployment', default='unknown')}")
    print(f"[ALERT] source_topic={get_nested(event, 'source', 'topic', default='unknown')}")
    print(f"[ALERT] consumer_group={get_nested(event, 'source', 'consumer_group', default='unknown')}")
    print(f"[ALERT] image_ref={get_nested(event, 'runtime', 'image_ref', default='unknown')}")
    print(f"[ALERT] config_version={get_nested(event, 'runtime', 'config_version', default='unknown')}")
    print(f"[ALERT] dependency_profile={get_nested(event, 'runtime', 'dependency_profile', default='unknown')}")
    print(f"[ALERT] error_type={get_nested(event, 'error', 'type', default='unknown')}")
    print(f"[ALERT] error_message={get_nested(event, 'error', 'message', default='unknown')}")
    print(f"[ALERT] replay_target_topic={get_nested(event, 'replay', 'target_topic', default='unknown')}")
    print(f"[ALERT] failure_payload_hash={get_nested(event, 'replay', 'failure_payload_hash', default='unknown')}")
    print(f"[ALERT] normal_fixture_available={get_nested(event, 'validation', 'normal_fixture_available', default=False)}")
    print(f"[ALERT] original_payload={json.dumps(original_payload, ensure_ascii=False)}")
    print("=" * 100)


def build_failure_replay_artifact(event: Dict[str, Any]) -> Dict[str, Any]:
    original_payload = event.get("original_payload", {}) or {}
    case_id = event["case_id"]
    failure_payload_hash = get_nested(event, "replay", "failure_payload_hash", default="") or sha256_of_json(original_payload)

    return {
        "artifact_type": "failure_replay",
        "case_id": case_id,
        "target_topic": get_nested(event, "replay", "target_topic", default=""),
        "payload_hash": failure_payload_hash,
        "created_at": utc_now_iso(),
        "source_service": get_nested(event, "source", "service", default="unknown"),
        "payload": original_payload,
    }


def build_normal_validation_artifact(event: Dict[str, Any]) -> Dict[str, Any]:
    case_id = event["case_id"]
    normal_payload = event.get("normal_validation_payload", {}) or {}
    normal_payload_hash = get_nested(event, "validation", "normal_payload_hash", default="")
    return {
        "artifact_type": "normal_validation",
        "case_id": case_id,
        "target_topic": get_nested(event, "replay", "target_topic", default=""),
        "payload_hash": normal_payload_hash if normal_payload else "",
        "created_at": utc_now_iso(),
        "enabled": bool(normal_payload),
        "source_service": get_nested(event, "source", "service", default="unknown"),
        "payload": normal_payload,
    }


def build_sandbox_spec(
    event: Dict[str, Any],
    failure_artifact_path: str,
    normal_artifact_path: str,
) -> Dict[str, Any]:
    case_id = event["case_id"]
    image_ref = get_nested(event, "runtime", "image_ref", default="unknown")
    replay_topic = get_nested(event, "replay", "target_topic", default="")
    result_topic = f"orders-result-{sanitize_case_id(case_id)}"
    config_version = get_nested(event, "runtime", "config_version", default="unknown")
    repro = event.get("repro_config", {}) or {}
    normal_available = get_nested(event, "validation", "normal_fixture_available", default=False)

    return {
        "metadata": {
            "case_id": case_id,
            "requested_at": utc_now_iso(),
            "source_service": get_nested(event, "source", "service", default="unknown"),
            "source_namespace": get_nested(event, "source", "namespace", default="unknown"),
            "source_deployment": get_nested(event, "source", "deployment", default="unknown"),
        },
        "failure": {
            "error_type": get_nested(event, "error", "type", default="unknown"),
            "error_message": get_nested(event, "error", "message", default="unknown"),
            "payload_hash": get_nested(event, "replay", "failure_payload_hash", default=""),
            "order_id": (event.get("original_payload", {}) or {}).get("order_id", "")
        },
        "validation": {
            "normal_fixture_available": normal_available,
            "normal_payload_hash": get_nested(event, "validation", "normal_payload_hash", default=""),
            "validation_mode": "reproduce",
            "validation_run_id": f"{case_id}-repro-0",
            "revalidation_generation": 0,
            "expected_failure_status": "failed",
            "expected_normal_status": "success",
        },
        "replay": {
            "publish_strategy": "launcher_after_sandbox_ready",
            "target_topic": replay_topic
        },
        "topic_init": {
            "image": TOPIC_INIT_IMAGE,
            "kafka_bootstrap": KAFKA_BOOTSTRAP,
            "replay_topic": replay_topic,
            "result_topic": result_topic,
            "partitions": TOPIC_INIT_PARTITIONS,
            "replication_factor": TOPIC_INIT_REPLICATION_FACTOR
        },
        "sandbox_isolation": {
            "mode": "sandbox_strict",
            "allowed_replay_topic": replay_topic,
            "allowed_result_topic": result_topic,
            "dlq_publish_allowed": False
        },
        "sandbox": {
            "namespace": SANDBOX_NAMESPACE,
            "deployment_name": SANDBOX_DEPLOYMENT_NAME,
            "service_name": SANDBOX_SERVICE_NAME,
            "launcher_name": SANDBOX_LAUNCHER_NAME,
            "replicas": SANDBOX_REPLICAS,
            "consumer_image_ref": image_ref,
            "replay_topic": replay_topic,
            "result_topic": result_topic,
            "consumer_env": {
                "KAFKA_BOOTSTRAP": KAFKA_BOOTSTRAP,
                "SOURCE_TOPIC": replay_topic,
                "DLQ_TOPIC": DLQ_TOPIC,
                "GROUP_ID": f"{SANDBOX_GROUP_ID_PREFIX}-{sanitize_case_id(case_id)}",
                "SERVICE_NAME": SANDBOX_SERVICE_NAME,
                "NAMESPACE": SANDBOX_NAMESPACE,
                "DEPLOYMENT_NAME": SANDBOX_DEPLOYMENT_NAME,
                "IMAGE_REF": image_ref,
                "CONFIG_VERSION": config_version,
                "DEPENDENCY_PROFILE": SANDBOX_DEPENDENCY_PROFILE,
                "DB_MODE": SANDBOX_DB_MODE,
                "DB_HOST": SANDBOX_DB_HOST,
                "CACHE_MODE": SANDBOX_CACHE_MODE,
                "CACHE_HOST": SANDBOX_CACHE_HOST,
                "EXTERNAL_API_MODE": SANDBOX_EXTERNAL_API_MODE,
                "EXTERNAL_API_BASE_URL": SANDBOX_EXTERNAL_API_BASE_URL,
                "FORCE_FAIL_FIELD": repro.get("force_fail_field", "should_fail"),
                "ENABLE_DLQ_PUBLISH": "false",
                "RUN_MODE": "sandbox",
                "CASE_ID": case_id,
                "RESULT_TOPIC": result_topic,
                "EMIT_RESULT_EVENT": "true",
                "READY_FILE_PATH": "/artifacts/consumer-ready.json",
                "ISOLATION_MODE": "sandbox_strict",
                "ALLOWED_REPLAY_TOPIC": replay_topic,
                "ALLOWED_RESULT_TOPIC": result_topic,
                "VALIDATION_MODE": "reproduce",
                "VALIDATION_RUN_ID": f"{case_id}-repro-0",
                "REVALIDATION_GENERATION": "0",
                "EXPECTED_FAILURE_STATUS": "failed",
                "EXPECTED_NORMAL_STATUS": "success",
            },
            "launcher_env": {
                "KAFKA_BOOTSTRAP": KAFKA_BOOTSTRAP,
                "CASE_ID": case_id,
                "REPLAY_TOPIC": replay_topic,
                "RESULT_TOPIC": result_topic,
                "RESULT_GROUP_ID": f"forensic-launcher-{sanitize_case_id(case_id)}",
                "VERDICT_FILE_PATH": "/artifacts/verdict.json",
                "RESULT_WAIT_SECONDS": "60",
                "EXPECTED_FAILURE_ERROR_TYPE": get_nested(event, "error", "type", default=""),
                "FAILURE_ARTIFACT_PATH": "/artifacts/failure.json",
                "NORMAL_ARTIFACT_PATH": "/artifacts/normal.json",
                "ENABLE_NORMAL_VALIDATION": "true" if normal_available else "false",
                "READY_FILE_PATH": "/artifacts/consumer-ready.json",
                "READY_WAIT_SECONDS": "90",
                "ISOLATION_MODE": "sandbox_strict",
                "ALLOWED_REPLAY_TOPIC": replay_topic,
                "ALLOWED_RESULT_TOPIC": result_topic,
                "VALIDATION_MODE": "reproduce",
                "VALIDATION_RUN_ID": f"{case_id}-repro-0",
                "REVALIDATION_GENERATION": "0",
                "EXPECTED_FAILURE_STATUS": "failed",
                "EXPECTED_NORMAL_STATUS": "success",
            }
        },
        "artifacts": {
            "failure_artifact_path": failure_artifact_path,
            "normal_artifact_path": normal_artifact_path,
        },
    }


def emit_json_file(output_dir: str, filename: str, payload: Dict[str, Any]) -> str:
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def emit_spec(spec: Dict[str, Any]) -> str:
    case_id = spec["metadata"]["case_id"]

    if SPEC_OUTPUT_MODE == "file":
        path = emit_json_file(SPEC_OUTPUT_DIR, f"{case_id}.json", spec)
        print(f"[SANDBOX_SPEC] written path={path}")
        return path

    print("[SANDBOX_SPEC_BEGIN]")
    print(json.dumps(spec, ensure_ascii=False, indent=2))
    print("[SANDBOX_SPEC_END]")
    return ""


def validate_github_dispatch_config():
    if not ENABLE_GITHUB_DISPATCH:
        return
    missing = [
        name for name, value in [
            ("GITHUB_TOKEN", GITHUB_TOKEN),
            ("GITHUB_OWNER", GITHUB_OWNER),
            ("GITHUB_REPO", GITHUB_REPO),
            ("GITHUB_REF", GITHUB_REF),
            ("ACTIVATE_SANDBOX_WORKFLOW_FILE", ACTIVATE_SANDBOX_WORKFLOW_FILE),
            ("CREATE_CASE_BRANCH_WORKFLOW_FILE", CREATE_CASE_BRANCH_WORKFLOW_FILE),
        ]
        if not value
    ]
    if missing:
        raise ValueError(f"Missing GitHub dispatch configuration: {', '.join(missing)}")


def github_dispatch(workflow_file: str, inputs: Dict[str, str]):
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/workflows/{workflow_file}/dispatches"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {"ref": GITHUB_REF, "inputs": inputs}
    resp = requests.post(url, headers=headers, json=payload, timeout=20)

    if resp.status_code not in (204, 201):
        raise RuntimeError(
            f"GitHub dispatch failed workflow={workflow_file} "
            f"status={resp.status_code}, body={resp.text}"
        )

    print(f"[GITHUB_DISPATCH] workflow={workflow_file} dispatched")


def dispatch_activate_sandbox(spec: Dict[str, Any], failure_artifact: Dict[str, Any], normal_artifact: Dict[str, Any]):
    github_dispatch(
        ACTIVATE_SANDBOX_WORKFLOW_FILE,
        {
            "spec_json": json.dumps(spec, ensure_ascii=False),
            "failure_artifact_json": json.dumps(failure_artifact, ensure_ascii=False),
            "normal_artifact_json": json.dumps(normal_artifact, ensure_ascii=False),
        },
    )
    print(f"[GITHUB_DISPATCH] activate-sandbox case_id={spec['metadata']['case_id']}")


def dispatch_create_case_branch(spec: Dict[str, Any]):
    case_id = spec["metadata"]["case_id"]
    github_dispatch(
        CREATE_CASE_BRANCH_WORKFLOW_FILE,
        {
            "case_id": case_id,
            "service": spec["metadata"]["source_service"],
            "base_ref": GITHUB_REF,
            "source_image_ref": spec["sandbox"]["consumer_image_ref"],
            "sandbox_manifest_path": spec["metadata"].get(
                "sandbox_manifest_path",
                f"gitops/apps/forensic-sandbox/cases/sandbox-case-{sanitize_case_id(case_id)[:48]}.yaml"
            ),
            "note": "case branch created from dlq handler",
        },
    )
    print(f"[GITHUB_DISPATCH] create-case-branch case_id={case_id}")


def main():
    validate_github_dispatch_config()
    consumer = get_consumer()

    print(
        f"[INFO] DLQ handler started. dlq={DLQ_TOPIC}, "
        f"group={GROUP_ID}, spec_output_mode={SPEC_OUTPUT_MODE}, "
        f"github_dispatch={ENABLE_GITHUB_DISPATCH}"
    )

    for message in consumer:
        raw_event = message.value

        try:
            event = normalize_legacy_event(raw_event)
            print_alert(event)

            case_id = event["case_id"]

            failure_artifact = build_failure_replay_artifact(event)
            failure_artifact_path = emit_json_file(
                REPLAY_ARTIFACT_OUTPUT_DIR,
                f"{case_id}-failure.json",
                failure_artifact
            )
            print(f"[REPLAY_ARTIFACT] written path={failure_artifact_path}")

            normal_artifact = build_normal_validation_artifact(event)
            normal_artifact_path = emit_json_file(
                VALIDATION_ARTIFACT_OUTPUT_DIR,
                f"{case_id}-normal.json",
                normal_artifact
            )
            print(f"[VALIDATION_ARTIFACT] written path={normal_artifact_path}")

            sandbox_spec = build_sandbox_spec(event, failure_artifact_path, normal_artifact_path)

            safe_case = sanitize_case_id(case_id)
            sandbox_spec["metadata"]["sandbox_manifest_path"] = (
                f"gitops/apps/forensic-sandbox/cases/sandbox-case-{safe_case[:48]}.yaml"
            )

            spec_path = emit_spec(sandbox_spec)

            if ENABLE_GITHUB_DISPATCH:
                # 순서 고정: 1) sandbox manifest 생성 2) case branch 생성
                dispatch_activate_sandbox(
                    spec=sandbox_spec,
                    failure_artifact=failure_artifact,
                    normal_artifact=normal_artifact,
                )
                dispatch_create_case_branch(sandbox_spec)

            print(
                "[NEXT_ACTION] sandbox activation dispatched, then case branch creation dispatched. "
                "developer will work on case/<case-id>; sandbox will remain isolated."
            )

            if spec_path:
                print(f"[NEXT_ACTION] sandbox_spec_path={spec_path}")

        except Exception as e:
            print(f"[ERROR] Failed to process DLQ event: {e}")
            print(f"[ERROR] raw_event={json.dumps(raw_event, ensure_ascii=False)}")


if __name__ == "__main__":
    main()