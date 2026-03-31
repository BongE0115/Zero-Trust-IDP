import argparse
import copy
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
    with path.open("w", encoding="utf-8") as f:
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


def find_deployment(docs: List[Dict[str, Any]], deployment_name: str) -> Dict[str, Any]:
    for doc in docs:
        if doc.get("kind") == "Deployment" and doc.get("metadata", {}).get("name") == deployment_name:
            return doc
    raise ValueError(f"Deployment '{deployment_name}' not found")


def find_job(docs: List[Dict[str, Any]], job_name: str) -> Dict[str, Any]:
    for doc in docs:
        if doc.get("kind") == "Job" and doc.get("metadata", {}).get("name") == job_name:
            return doc
    raise ValueError(f"Job '{job_name}' not found")


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
    return sanitize_name(case_id, max_len=24)


def patch_init_container_for_artifacts(
    deployment: Dict[str, Any],
    failure_artifact: Dict[str, Any],
    normal_artifact: Dict[str, Any],
) -> None:
    init_containers = deployment["spec"]["template"]["spec"].get("initContainers", [])
    if not init_containers:
        raise ValueError("initContainers not found in sandbox deployment")

    init_container = find_init_container_by_name(init_containers, "artifact-init")
    script = f"""mkdir -p /artifacts
cat > /artifacts/failure.json <<'EOF'
{json.dumps(failure_artifact, ensure_ascii=False, indent=2)}
EOF
cat > /artifacts/normal.json <<'EOF'
{json.dumps(normal_artifact, ensure_ascii=False, indent=2)}
EOF
"""
    init_container["command"] = ["/bin/sh", "-c", script]


def patch_job_artifact_init_for_artifacts(
    job: Dict[str, Any],
    failure_artifact: Dict[str, Any],
    normal_artifact: Dict[str, Any],
) -> None:
    init_containers = job["spec"]["template"]["spec"].get("initContainers", [])
    if not init_containers:
        raise ValueError("initContainers not found in launcher job")

    init_container = find_init_container_by_name(init_containers, "artifact-init")
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
) -> Dict[str, Any]:
    metadata = spec["metadata"]
    failure = spec["failure"]
    validation = spec.get("validation", {})
    sandbox = spec["sandbox"]
    replay = spec.get("replay", {})
    sandbox_isolation = spec.get("sandbox_isolation", {})
    launcher_env = sandbox.get("launcher_env", {})

    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": case_configmap_name,
            "namespace": sandbox["namespace"],
            "labels": {
                "app": deployment_name,
                "forensic-case-id": metadata["case_id"],
            },
            "annotations": {
                "argocd.argoproj.io/sync-wave": "2"
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
            "verdict_file_path": launcher_env.get("VERDICT_FILE_PATH", "/artifacts/verdict.json"),
        },
    }


def build_case_manifest_docs(
    template_docs: List[Dict[str, Any]],
    spec: Dict[str, Any],
    failure_artifact: Dict[str, Any],
    normal_artifact: Dict[str, Any],
    launcher_image_ref: str,
) -> List[Dict[str, Any]]:
    sandbox = spec["sandbox"]
    metadata = spec["metadata"]
    failure = spec["failure"]
    validation = spec.get("validation", {})
    topic_init = spec.get("topic_init", {})

    template_deployment = find_deployment(template_docs, sandbox["deployment_name"])
    deployment = copy.deepcopy(template_deployment)

    template_job = find_job(template_docs, "forensic-launcher-job")
    job = copy.deepcopy(template_job)

    case_suffix = make_case_suffix(metadata["case_id"])
    case_deployment_name = f"{sandbox['deployment_name']}-{case_suffix}"
    case_job_name = f"forensic-launcher-job-{case_suffix}"
    case_app_label = case_deployment_name
    case_configmap_name = f"forensic-sandbox-case-{case_suffix}"

    deployment["metadata"]["namespace"] = sandbox["namespace"]
    deployment["metadata"]["name"] = case_deployment_name
    deployment["metadata"].setdefault("labels", {})
    deployment["metadata"]["labels"]["forensic-case-id"] = metadata["case_id"]

    deployment["spec"]["replicas"] = int(sandbox["replicas"])
    deployment["spec"]["selector"]["matchLabels"]["app"] = case_app_label
    deployment["spec"]["template"]["metadata"]["labels"]["app"] = case_app_label
    deployment["spec"]["template"]["metadata"]["labels"]["forensic-case-id"] = metadata["case_id"]

    pod_spec = deployment["spec"]["template"]["spec"]
    containers = pod_spec.get("containers", [])
    if not containers:
        raise ValueError("Deployment has no containers")

    init_containers = pod_spec.get("initContainers", [])
    if not init_containers:
        raise ValueError("Deployment has no initContainers")

    topic_init_container = find_init_container_by_name(init_containers, "topic-init")
    consumer_container = find_container_by_name(containers, "consumer-app")

    job["metadata"]["namespace"] = sandbox["namespace"]
    job["metadata"]["name"] = case_job_name
    job["metadata"].setdefault("labels", {})
    job["metadata"]["labels"]["forensic-case-id"] = metadata["case_id"]

    job_template_meta = job["spec"]["template"].setdefault("metadata", {})
    job_template_meta.setdefault("labels", {})
    job_template_meta["labels"]["app"] = case_job_name
    job_template_meta["labels"]["forensic-case-id"] = metadata["case_id"]

    job_pod_spec = job["spec"]["template"]["spec"]
    job_containers = job_pod_spec.get("containers", [])
    if not job_containers:
        raise ValueError("Launcher Job has no containers")

    job_init_containers = job_pod_spec.get("initContainers", [])
    if not job_init_containers:
        raise ValueError("Launcher Job has no initContainers")

    launcher_container = find_container_by_name(job_containers, "forensic-launcher")

    consumer_container["image"] = sandbox["consumer_image_ref"]
    launcher_container["image"] = launcher_image_ref

    if topic_init.get("image"):
        topic_init_container["image"] = topic_init["image"]

    upsert_env(topic_init_container, "KAFKA_BOOTSTRAP", topic_init.get("kafka_bootstrap", ""))
    upsert_env(topic_init_container, "REPLAY_TOPIC", topic_init.get("replay_topic", ""))
    upsert_env(topic_init_container, "RESULT_TOPIC", topic_init.get("result_topic", ""))
    upsert_env(topic_init_container, "TOPIC_PARTITIONS", topic_init.get("partitions", "1"))
    upsert_env(topic_init_container, "TOPIC_REPLICATION_FACTOR", topic_init.get("replication_factor", "1"))

    for k, v in sandbox["consumer_env"].items():
        upsert_env(consumer_container, k, v)

    upsert_env(consumer_container, "SERVICE_NAME", case_deployment_name)
    upsert_env(consumer_container, "DEPLOYMENT_NAME", case_deployment_name)
    upsert_env(consumer_container, "FAILURE_ERROR_TYPE", failure["error_type"])
    upsert_env(consumer_container, "FAILURE_ERROR_MESSAGE", failure["error_message"])
    upsert_env(consumer_container, "REPLAY_PAYLOAD_HASH", failure["payload_hash"])
    upsert_env(consumer_container, "REPLAY_ORDER_ID", failure["order_id"])
    upsert_env(consumer_container, "NORMAL_PAYLOAD_HASH", validation.get("normal_payload_hash", ""))

    for k, v in sandbox["launcher_env"].items():
        upsert_env(launcher_container, k, v)

    upsert_env(launcher_container, "CASE_ID", metadata["case_id"])
    upsert_env(launcher_container, "REPLAY_TOPIC", sandbox["replay_topic"])
    upsert_env(
        launcher_container,
        "ENABLE_NORMAL_VALIDATION",
        "true" if validation.get("normal_fixture_available", False) else "false"
    )

    patch_init_container_for_artifacts(deployment, failure_artifact, normal_artifact)
    patch_job_artifact_init_for_artifacts(job, failure_artifact, normal_artifact)

    case_configmap = build_case_configmap(
        spec=spec,
        failure_artifact=failure_artifact,
        normal_artifact=normal_artifact,
        deployment_name=case_deployment_name,
        case_configmap_name=case_configmap_name,
    )

    return [deployment, job, case_configmap]


def main():
    parser = argparse.ArgumentParser(description="Generate case-specific forensic sandbox manifest")
    parser.add_argument("--spec", required=True, help="Path to sandbox spec JSON")
    parser.add_argument("--failure-artifact", required=True, help="Path to failure replay artifact JSON")
    parser.add_argument("--normal-artifact", required=True, help="Path to normal validation artifact JSON")
    parser.add_argument("--launcher-image-ref", required=True, help="Launcher image ref")
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
        launcher_image_ref=args.launcher_image_ref,
    )

    dump_yaml_all(output_yaml_path, case_docs)

    print("[OK] case manifest generated")
    print(f"[OK] case_id={spec['metadata']['case_id']}")
    print(f"[OK] output_yaml={output_yaml_path}")
    print(f"[OK] replay_topic={spec['sandbox']['replay_topic']}")
    print(f"[OK] result_topic={spec['sandbox']['result_topic']}")


if __name__ == "__main__":
    main()