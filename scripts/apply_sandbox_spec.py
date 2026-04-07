#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

import yaml


def load_yaml_all(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        docs = list(yaml.safe_load_all(f))
    return [doc for doc in docs if doc is not None]


def dump_yaml_all(path: Path, docs: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump_all(
            docs,
            f,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_env_list(container: Dict[str, Any]) -> List[Dict[str, str]]:
    env_list = container.get("env")
    if env_list is None:
        env_list = []
        container["env"] = env_list
    return env_list


def upsert_env(container: Dict[str, Any], name: str, value: str) -> None:
    env_list = get_env_list(container)
    value = "" if value is None else str(value)

    for item in env_list:
        if item.get("name") == name:
            item["value"] = value
            return

    env_list.append({"name": name, "value": value})


def ensure_volume(spec: Dict[str, Any], volume_name: str) -> None:
    volumes = spec.setdefault("volumes", [])
    for vol in volumes:
        if vol.get("name") == volume_name:
            return
    volumes.append({"name": volume_name, "emptyDir": {}})


def ensure_volume_mount(container: Dict[str, Any], volume_name: str, mount_path: str) -> None:
    mounts = container.setdefault("volumeMounts", [])
    for m in mounts:
        if m.get("name") == volume_name:
            m["mountPath"] = mount_path
            return
    mounts.append({"name": name_to_str(volume_name), "mountPath": mount_path})


def name_to_str(value: Any) -> str:
    return "" if value is None else str(value)


def find_deployment(docs: List[Dict[str, Any]], deployment_name: str) -> Dict[str, Any]:
    for doc in docs:
        if doc.get("kind") == "Deployment" and doc.get("metadata", {}).get("name") == deployment_name:
            return doc
    raise ValueError(f"Deployment '{deployment_name}' not found")


def find_service(docs: List[Dict[str, Any]], service_name: str) -> Dict[str, Any]:
    for doc in docs:
        if doc.get("kind") == "Service" and doc.get("metadata", {}).get("name") == service_name:
            return doc
    raise ValueError(f"Service '{service_name}' not found")


def find_container_by_name(containers: List[Dict[str, Any]], name: str) -> Dict[str, Any]:
    for c in containers:
        if c.get("name") == name:
            return c
    raise ValueError(f"Container '{name}' not found")


def find_init_container_by_name(init_containers: List[Dict[str, Any]], name: str) -> Dict[str, Any]:
    for c in init_containers:
        if c.get("name") == name:
            return c
    raise ValueError(f"Init container '{name}' not found")


def sanitize_name(value: str, max_len: int = 40) -> str:
    cleaned = "".join(c.lower() if c.isalnum() else "-" for c in value)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    cleaned = cleaned.strip("-")
    if not cleaned:
        cleaned = "case"
    return cleaned[:max_len].rstrip("-")


def make_case_suffix(case_id: str) -> str:
    cleaned = sanitize_name(case_id, max_len=15)
    digest = hashlib.sha1(case_id.encode("utf-8")).hexdigest()[:8]
    return f"{cleaned}-{digest}"


def make_case_label(case_id: str, max_len: int = 63) -> str:
    cleaned = "".join(c.lower() if c.isalnum() else "-" for c in case_id)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    cleaned = cleaned.strip("-")

    if not cleaned:
        cleaned = "case"

    digest = hashlib.sha1(case_id.encode("utf-8")).hexdigest()[:8]
    head_len = max_len - len(digest) - 1
    head = cleaned[:head_len].rstrip("-")

    if not head:
        head = "case"

    return f"{head}-{digest}"


def patch_topic_init_container(
    deployment: Dict[str, Any],
    kafka_bootstrap: str,
    replay_topic: str,
    result_topic: str,
    partitions: str,
    replication_factor: str,
) -> None:
    pod_spec = deployment["spec"]["template"]["spec"]
    init_containers = pod_spec.get("initContainers", [])
    if not init_containers:
        raise ValueError("initContainers not found in sandbox deployment")

    topic_init = find_init_container_by_name(init_containers, "topic-init")

    script = """set -eu

BOOTSTRAP="${KAFKA_BOOTSTRAP}"
PARTITIONS="${TOPIC_PARTITIONS:-1}"
REPLICATION_FACTOR="${TOPIC_REPLICATION_FACTOR:-1}"

create_topic() {
  topic="$1"
  if [ -z "$topic" ]; then
    return 0
  fi

  /opt/bitnami/kafka/bin/kafka-topics.sh \\
    --bootstrap-server "$BOOTSTRAP" \\
    --create \\
    --if-not-exists \\
    --topic "$topic" \\
    --partitions "$PARTITIONS" \\
    --replication-factor "$REPLICATION_FACTOR"
}

create_topic "${REPLAY_TOPIC}"
create_topic "${RESULT_TOPIC}"

echo "[OK] topic-init completed"
"""
    topic_init["command"] = ["/bin/sh", "-c", script]
    upsert_env(topic_init, "KAFKA_BOOTSTRAP", kafka_bootstrap)
    upsert_env(topic_init, "REPLAY_TOPIC", replay_topic)
    upsert_env(topic_init, "RESULT_TOPIC", result_topic)
    upsert_env(topic_init, "TOPIC_PARTITIONS", partitions)
    upsert_env(topic_init, "TOPIC_REPLICATION_FACTOR", replication_factor)


def patch_init_container_for_artifacts(
    deployment: Dict[str, Any],
    failure_artifact: Dict[str, Any],
    normal_artifact: Dict[str, Any],
) -> None:
    pod_spec = deployment["spec"]["template"]["spec"]
    ensure_volume(pod_spec, "artifacts")

    init_containers = pod_spec.get("initContainers", [])
    if not init_containers:
        raise ValueError("initContainers not found in sandbox deployment")

    init_container = find_init_container_by_name(init_containers, "artifact-init")
    ensure_volume_mount(init_container, "artifacts", "/artifacts")

    script = f"""mkdir -p /artifacts
cat > /artifacts/failure.json <<'EOF'
{json.dumps(failure_artifact, ensure_ascii=False, indent=2)}
EOF
cat > /artifacts/normal.json <<'EOF'
{json.dumps(normal_artifact, ensure_ascii=False, indent=2)}
EOF
"""
    init_container["command"] = ["/bin/sh", "-c", script]


def build_case_configmap(
    spec: Dict[str, Any],
    failure_artifact: Dict[str, Any],
    normal_artifact: Dict[str, Any],
    deployment_name: str,
    case_configmap_name: str,
    mongo_host: str,
    case_label: str,
) -> Dict[str, Any]:
    metadata = spec["metadata"]
    failure = spec["failure"]
    validation = spec.get("validation", {})
    sandbox = spec["sandbox"]
    replay = spec.get("replay", {})
    sandbox_isolation = spec.get("sandbox_isolation", {})

    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": case_configmap_name,
            "namespace": sandbox["namespace"],
            "labels": {
                "app": deployment_name,
                "forensic-case-id": case_label,
            },
            "annotations": {
                "argocd.argoproj.io/sync-wave": "2",
                "forensic.case-id/full": metadata["case_id"],
            },
        },
        "data": {
            "case_id": metadata["case_id"],
            "requested_by": "manual-or-workflow",
            "source_service": metadata["source_service"],
            "source_namespace": metadata["source_namespace"],
            "source_deployment": metadata["source_deployment"],
            "error_type": failure["error_type"],
            "error_message": failure["error_message"],
            "consumer_image_ref": sandbox["consumer_image_ref"],
            "deployment_name": deployment_name,
            "replay_topic": sandbox["replay_topic"],
            "result_topic": sandbox.get("result_topic", ""),
            "config_version": sandbox["consumer_env"].get("CONFIG_VERSION", ""),
            "dependency_profile": sandbox["consumer_env"].get("DEPENDENCY_PROFILE", ""),
            "requested_at": metadata["requested_at"],
            "failure_payload_hash": failure["payload_hash"],
            "normal_payload_hash": validation.get("normal_payload_hash", ""),
            "order_id": failure["order_id"],
            "failure_artifact_type": failure_artifact.get("artifact_type", ""),
            "failure_artifact_payload_hash": failure_artifact.get("payload_hash", ""),
            "normal_artifact_type": normal_artifact.get("artifact_type", ""),
            "normal_artifact_payload_hash": normal_artifact.get("payload_hash", ""),
            "normal_validation_enabled": str(normal_artifact.get("enabled", False)).lower(),
            "replay_publish_strategy": replay.get("publish_strategy", ""),
            "isolation_mode": sandbox_isolation.get("mode", ""),
            "allowed_replay_topic": sandbox_isolation.get("allowed_replay_topic", ""),
            "allowed_result_topic": sandbox_isolation.get("allowed_result_topic", ""),
            "mongo_host": mongo_host,
            "expected_failure_status": validation.get("expected_failure_status", ""),
            "expected_normal_status": validation.get("expected_normal_status", ""),
        },
    }


def build_case_manifest_docs(
    template_docs: List[Dict[str, Any]],
    spec: Dict[str, Any],
    failure_artifact: Dict[str, Any],
    normal_artifact: Dict[str, Any],
) -> List[Dict[str, Any]]:
    sandbox = spec["sandbox"]
    metadata = spec["metadata"]
    failure = spec["failure"]
    validation = spec.get("validation", {})
    topic_init = spec.get("topic_init", {})

    template_deployment = find_deployment(template_docs, sandbox["deployment_name"])
    deployment = copy.deepcopy(template_deployment)

    template_mongo_deployment = find_deployment(template_docs, "mongodb-temp")
    mongo_deployment = copy.deepcopy(template_mongo_deployment)

    template_mongo_service = find_service(template_docs, "mongodb-temp")
    mongo_service = copy.deepcopy(template_mongo_service)

    case_suffix = make_case_suffix(metadata["case_id"])
    case_label = make_case_label(metadata["case_id"])
    case_deployment_name = f"{sandbox['deployment_name']}-{case_suffix}"
    case_mongo_name = f"mongodb-temp-{case_suffix}"
    case_app_label = case_deployment_name
    case_configmap_name = f"forensic-sandbox-case-{case_suffix}"
    case_mongo_host = f"{case_mongo_name}.{sandbox['namespace']}.svc.cluster.local"

    deployment["metadata"]["namespace"] = sandbox["namespace"]
    deployment["metadata"]["name"] = case_deployment_name
    deployment["metadata"].setdefault("labels", {})
    deployment["metadata"]["labels"]["forensic-case-id"] = case_label
    deployment["metadata"].setdefault("annotations", {})
    deployment["metadata"]["annotations"]["forensic.case-id/full"] = metadata["case_id"]

    deployment["spec"]["replicas"] = int(sandbox["replicas"])
    deployment["spec"]["selector"]["matchLabels"]["app"] = case_app_label
    deployment["spec"]["template"]["metadata"]["labels"]["app"] = case_app_label
    deployment["spec"]["template"]["metadata"]["labels"]["forensic-case-id"] = case_label
    deployment["spec"]["template"]["metadata"].setdefault("annotations", {})
    deployment["spec"]["template"]["metadata"]["annotations"]["forensic.case-id/full"] = metadata["case_id"]
    deployment["spec"]["template"]["metadata"]["labels"]["sandbox-tier"] = "strict-isolation"
    deployment["spec"]["template"]["metadata"]["labels"]["istio.io/use-waypoint"] = "sandbox-waypoint"
    

    pod_spec = deployment["spec"]["template"]["spec"]
    ensure_volume(pod_spec, "artifacts")

    containers = pod_spec.get("containers", [])
    if not containers:
        raise ValueError("Deployment has no containers")

    consumer_container = find_container_by_name(containers, "consumer-app")
    ensure_volume_mount(consumer_container, "artifacts", "/artifacts")
    consumer_container["image"] = sandbox["consumer_image_ref"]

    if topic_init.get("image"):
        init_containers = pod_spec.get("initContainers", [])
        topic_init_container = find_init_container_by_name(init_containers, "topic-init")
        topic_init_container["image"] = topic_init["image"]

    patch_topic_init_container(
        deployment=deployment,
        kafka_bootstrap=topic_init.get("kafka_bootstrap", ""),
        replay_topic=topic_init.get("replay_topic", ""),
        result_topic=topic_init.get("result_topic", ""),
        partitions=topic_init.get("partitions", "1"),
        replication_factor=topic_init.get("replication_factor", "1"),
    )

    for k, v in sandbox["consumer_env"].items():
        upsert_env(consumer_container, k, v)

    upsert_env(consumer_container, "DB_HOST", case_mongo_host)
    upsert_env(consumer_container, "SERVICE_NAME", case_deployment_name)
    upsert_env(consumer_container, "DEPLOYMENT_NAME", case_deployment_name)
    upsert_env(consumer_container, "FAILURE_ERROR_TYPE", failure["error_type"])
    upsert_env(consumer_container, "FAILURE_ERROR_MESSAGE", failure["error_message"])
    upsert_env(consumer_container, "REPLAY_PAYLOAD_HASH", failure["payload_hash"])
    upsert_env(consumer_container, "REPLAY_ORDER_ID", failure["order_id"])
    upsert_env(consumer_container, "NORMAL_PAYLOAD_HASH", validation.get("normal_payload_hash", ""))
    upsert_env(consumer_container, "CASE_ID", metadata["case_id"])
    upsert_env(consumer_container, "VALIDATION_MODE", "reproduce")
    upsert_env(consumer_container, "EXPECTED_FAILURE_STATUS", validation.get("expected_failure_status", "failed"))
    upsert_env(consumer_container, "EXPECTED_NORMAL_STATUS", validation.get("expected_normal_status", "success"))

    patch_init_container_for_artifacts(deployment, failure_artifact, normal_artifact)

    mongo_deployment["metadata"]["namespace"] = sandbox["namespace"]
    mongo_deployment["metadata"]["name"] = case_mongo_name
    mongo_deployment["metadata"].setdefault("labels", {})
    mongo_deployment["metadata"]["labels"]["forensic-case-id"] = case_label
    mongo_deployment["metadata"].setdefault("annotations", {})
    mongo_deployment["metadata"]["annotations"]["forensic.case-id/full"] = metadata["case_id"]
    mongo_deployment["spec"]["selector"]["matchLabels"]["app"] = case_mongo_name
    mongo_deployment["spec"]["template"]["metadata"]["labels"]["app"] = case_mongo_name
    mongo_deployment["spec"]["template"]["metadata"]["labels"]["forensic-case-id"] = case_label
    mongo_deployment["spec"]["template"]["metadata"].setdefault("annotations", {})
    mongo_deployment["spec"]["template"]["metadata"]["annotations"]["forensic.case-id/full"] = metadata["case_id"]

    mongo_service["metadata"]["namespace"] = sandbox["namespace"]
    mongo_service["metadata"]["name"] = case_mongo_name
    mongo_service["metadata"].setdefault("labels", {})
    mongo_service["metadata"]["labels"]["forensic-case-id"] = case_label
    mongo_service["metadata"].setdefault("annotations", {})
    mongo_service["metadata"]["annotations"]["forensic.case-id/full"] = metadata["case_id"]
    mongo_service["spec"]["selector"]["app"] = case_mongo_name

    case_configmap = build_case_configmap(
        spec=spec,
        failure_artifact=failure_artifact,
        normal_artifact=normal_artifact,
        deployment_name=case_deployment_name,
        case_configmap_name=case_configmap_name,
        mongo_host=case_mongo_host,
        case_label=case_label,
    )

    return [mongo_service, mongo_deployment, deployment, case_configmap]


def main():
    parser = argparse.ArgumentParser(description="Generate case-specific forensic sandbox manifest")
    parser.add_argument("--spec", required=True, help="Path to sandbox spec JSON")
    parser.add_argument("--failure-artifact", required=True, help="Path to failure replay artifact JSON")
    parser.add_argument("--normal-artifact", required=True, help="Path to normal validation artifact JSON")
    parser.add_argument("--template-yaml", required=True, help="Path to sandbox template yaml")
    parser.add_argument("--output-yaml", required=True, help="Path to generated case yaml")
    args = parser.parse_args()

    spec_path = Path(args.spec)
    failure_artifact_path = Path(args.failure_artifact)
    normal_artifact_path = Path(args.normal_artifact)
    template_yaml_path = Path(args.template_yaml)
    output_yaml_path = Path(args.output_yaml)

    spec = load_json(spec_path)
    failure_artifact = load_json(failure_artifact_path)
    normal_artifact = load_json(normal_artifact_path)
    template_docs = load_yaml_all(template_yaml_path)

    case_docs = build_case_manifest_docs(
        template_docs=template_docs,
        spec=spec,
        failure_artifact=failure_artifact,
        normal_artifact=normal_artifact,
    )

    dump_yaml_all(output_yaml_path, case_docs)

    print("[OK] case manifest generated")
    print(f"[OK] case_id={spec['metadata']['case_id']}")
    print(f"[OK] output_yaml={output_yaml_path}")
    print(f"[OK] replay_topic={spec['sandbox']['replay_topic']}")
    print(f"[OK] result_topic={spec['sandbox']['result_topic']}")


if __name__ == "__main__":
    main()