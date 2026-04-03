#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TEMPLATE_PATH = (
    REPO_ROOT / "gitops" / "apps" / "forensic-sandbox" / "cases" / "templates" / "revalidation-job.yaml"
)
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT / "gitops" / "apps" / "forensic-sandbox" / "cases" / "revalidation"
)
DEFAULT_RECORDS_DIR = (
    REPO_ROOT / "gitops" / "apps" / "forensic-sandbox" / "cases" / "records"
)

SAFE_CASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
DIGEST_IMAGE_PATTERN = re.compile(r"^[^:@]+(?:/[^:@]+)*@sha256:[0-9a-f]{64}$")


def require_safe_case_id(case_id: str) -> None:
    if not SAFE_CASE_ID_PATTERN.fullmatch(case_id):
        raise ValueError(
            "case_id contains unsupported characters. "
            "Use only letters, numbers, dot(.), underscore(_), hyphen(-)."
        )


def require_digest_image_ref(image_ref: str) -> None:
    if not DIGEST_IMAGE_PATTERN.fullmatch(image_ref):
        raise ValueError(
            "launcher image must be a digest-pinned reference like "
            "'ghcr.io/org/image@sha256:<64hex>'"
        )


def deterministic_validation_run_id(case_id: str, generation: int) -> str:
    return f"{case_id}-reval-g{generation}"


def sanitize_name(value: str, max_len: int = 50) -> str:
    cleaned = "".join(c.lower() if c.isalnum() else "-" for c in value)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    cleaned = cleaned.strip("-")
    if not cleaned:
        cleaned = "case"
    return cleaned[:max_len].rstrip("-")


def load_text(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"template not found: {path}")
    return path.read_text(encoding="utf-8")


def dump_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def render_template(template: str, mapping: Dict[str, str]) -> str:
    rendered = template
    for key, value in mapping.items():
        rendered = rendered.replace(f"__{key}__", value)
    return rendered


def ensure_no_placeholders_left(rendered: str) -> None:
    unresolved = sorted(set(re.findall(r"__([A-Z0-9_]+)__", rendered)))
    if unresolved:
        raise ValueError(
            "unresolved placeholders remain in rendered template: "
            + ", ".join(unresolved)
        )


def load_yaml_all(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"manifest not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        docs = list(yaml.safe_load_all(f))
    return [doc for doc in docs if doc is not None]


def dump_yaml_all(path: Path, docs: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump_all(docs, f, allow_unicode=True, sort_keys=False)


def get_deployments(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [doc for doc in docs if doc.get("kind") == "Deployment"]


def get_containers(deployment: Dict[str, Any]) -> List[Dict[str, Any]]:
    spec = deployment.get("spec", {}).get("template", {}).get("spec", {})
    containers = spec.get("containers", [])
    if not isinstance(containers, list):
        raise ValueError("deployment.spec.template.spec.containers must be a list")
    return containers


def get_init_containers(deployment: Dict[str, Any]) -> List[Dict[str, Any]]:
    spec = deployment.get("spec", {}).get("template", {}).get("spec", {})
    init_containers = spec.get("initContainers", [])
    if not isinstance(init_containers, list):
        raise ValueError("deployment.spec.template.spec.initContainers must be a list")
    return init_containers


def find_container_by_name(containers: List[Dict[str, Any]], name: str) -> Dict[str, Any]:
    matches = [c for c in containers if c.get("name") == name]
    if not matches:
        raise ValueError(f"container not found: {name}")
    if len(matches) > 1:
        raise ValueError(f"multiple containers found with name={name}")
    return matches[0]


def find_sandbox_deployment(docs: List[Dict[str, Any]]) -> Dict[str, Any]:
    deployments = get_deployments(docs)
    if not deployments:
        raise ValueError("no Deployment found in manifest")

    consumer_candidates: List[Dict[str, Any]] = []
    for dep in deployments:
        try:
            consumer = find_container_by_name(get_containers(dep), "consumer-app")
            if consumer:
                consumer_candidates.append(dep)
        except Exception:
            continue

    if len(consumer_candidates) == 1:
        return consumer_candidates[0]

    preferred = [
        d for d in consumer_candidates
        if "forensic-sandbox-app" in (d.get("metadata", {}).get("name") or "")
    ]
    if len(preferred) == 1:
        return preferred[0]

    names = [d.get("metadata", {}).get("name", "<unknown>") for d in consumer_candidates]
    raise ValueError(
        "sandbox deployment not found uniquely. candidates=" + ", ".join(names)
    )


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


def extract_embedded_artifact(script_text: str, target_path: str) -> Dict[str, Any]:
    marker = f"cat > {target_path} <<'EOF'"
    if marker not in script_text:
        raise ValueError(f"artifact marker not found for {target_path}")

    start = script_text.index(marker) + len(marker)
    remainder = script_text[start:]
    end_marker = "\nEOF"
    end = remainder.find(end_marker)
    if end == -1:
        raise ValueError(f"EOF terminator not found for {target_path}")

    raw_json = remainder[:end].strip()
    data = json.loads(raw_json)
    if not isinstance(data, dict):
        raise ValueError(f"artifact for {target_path} must be a JSON object")
    return data


def load_case_record(records_dir: Path, case_id: str) -> Dict[str, Any]:
    path = records_dir / f"{case_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"case record not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def extract_artifacts_from_sandbox_manifest(manifest_path: Path) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    docs = load_yaml_all(manifest_path)
    deployment = find_sandbox_deployment(docs)
    init_containers = get_init_containers(deployment)
    artifact_init = find_container_by_name(init_containers, "artifact-init")

    command = artifact_init.get("command") or []
    if len(command) < 3:
        raise ValueError("artifact-init command is missing embedded artifact script")

    script_text = command[-1]
    if not isinstance(script_text, str):
        raise ValueError("artifact-init script is not a string")

    failure_artifact = extract_embedded_artifact(script_text, "/artifacts/failure.json")
    normal_artifact = extract_embedded_artifact(script_text, "/artifacts/normal.json")
    return failure_artifact, normal_artifact


def patch_sandbox_manifest_for_revalidation(
    *,
    manifest_path: Path,
    case_id: str,
    generation: int,
    validation_run_id: str,
    expected_failure_status: str,
    expected_normal_status: str,
) -> None:
    docs = load_yaml_all(manifest_path)
    deployment = find_sandbox_deployment(docs)
    consumer = find_container_by_name(get_containers(deployment), "consumer-app")

    upsert_env(consumer, "CASE_ID", case_id)
    upsert_env(consumer, "VALIDATION_MODE", "fix-verify")
    upsert_env(consumer, "VALIDATION_RUN_ID", validation_run_id)
    upsert_env(consumer, "REVALIDATION_GENERATION", str(generation))
    upsert_env(consumer, "EXPECTED_FAILURE_STATUS", expected_failure_status)
    upsert_env(consumer, "EXPECTED_NORMAL_STATUS", expected_normal_status)
    upsert_env(consumer, "ISOLATION_MODE", "sandbox_strict")

    dump_yaml_all(manifest_path, docs)


def maybe_update_case_record(
    *,
    case_id: str,
    records_dir: Path,
    generation: int,
    validation_run_id: str,
    output_path: Path,
    note: str,
    expected_failure_status: str,
    expected_normal_status: str,
) -> None:
    script = REPO_ROOT / "scripts" / "update_case_record.py"
    if not script.exists():
        raise FileNotFoundError(f"update_case_record.py not found: {script}")

    cmd = [
        sys.executable,
        str(script),
        "--records-dir",
        str(records_dir),
        "update",
        "--case-id",
        case_id,
        "--status",
        "revalidation_requested",
        "--revalidation-generation",
        str(generation),
        "--validation-run-id",
        validation_run_id,
        "--metadata-json",
        json.dumps(
            {
                "revalidation_job_manifest_path": str(output_path),
                "revalidation_expected_failure_status": expected_failure_status,
                "revalidation_expected_normal_status": expected_normal_status,
            },
            ensure_ascii=False,
        ),
        "--note",
        note,
    ]
    subprocess.run(cmd, check=True)


def indent_for_block_scalar(text: str, spaces: int) -> str:
    prefix = " " * spaces
    return textwrap.indent(text, prefix)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render a case-specific revalidation launcher Job manifest from a template."
    )
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--generation", type=int, required=True)
    parser.add_argument("--namespace", default="forensic-sandbox")
    parser.add_argument("--validation-mode", default="fix-verify")
    parser.add_argument("--validation-run-id")
    parser.add_argument("--kafka-bootstrap", default="kafka.kafka-poc.svc.cluster.local:9092")
    parser.add_argument("--replay-topic", required=True)
    parser.add_argument("--result-topic", required=True)
    parser.add_argument("--failure-artifact-path", default="/artifacts/failure.json")
    parser.add_argument("--normal-artifact-path", default="/artifacts/normal.json")
    parser.add_argument("--enable-normal-validation", choices=["true", "false"], default="true")
    parser.add_argument("--expected-failure-status", default="success")
    parser.add_argument("--expected-normal-status", default="success")
    parser.add_argument("--launcher-image-ref", required=True)
    parser.add_argument("--template-path", default=str(DEFAULT_TEMPLATE_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--output-path")
    parser.add_argument(
        "--records-dir",
        default=str(DEFAULT_RECORDS_DIR),
        help=f"Directory containing case records (default: {DEFAULT_RECORDS_DIR})",
    )
    parser.add_argument(
        "--update-record",
        action="store_true",
        help="Also update the case record to status=revalidation_requested",
    )
    parser.add_argument("--note", default="revalidation job manifest rendered")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        require_safe_case_id(args.case_id)
        require_digest_image_ref(args.launcher_image_ref)

        if args.validation_mode != "fix-verify":
            raise ValueError("revalidation renderer only supports fix-verify mode")

        records_dir = Path(args.records_dir)
        record = load_case_record(records_dir, args.case_id)
        sandbox_manifest_path_raw = record.get("sandbox_manifest_path") or ""
        if not sandbox_manifest_path_raw:
            raise ValueError("sandbox_manifest_path is empty in case record")

        sandbox_manifest_path = Path(sandbox_manifest_path_raw)
        failure_artifact, normal_artifact = extract_artifacts_from_sandbox_manifest(sandbox_manifest_path)

        template_path = Path(args.template_path)
        output_dir = Path(args.output_dir)
        validation_run_id = args.validation_run_id or deterministic_validation_run_id(args.case_id, args.generation)

        safe_suffix = sanitize_name(args.case_id, max_len=40)
        job_name = f"forensic-revalidate-{safe_suffix}-g{args.generation}"
        output_path = (
            Path(args.output_path)
            if args.output_path
            else output_dir / f"revalidate-case-{args.case_id}.yaml"
        )

        ready_stub = {
            "case_id": args.case_id,
            "source_topic": args.replay_topic,
            "group_id": f"forensic-revalidate-ready-{args.case_id}",
            "service": "worker-consumer",
            "namespace": args.namespace,
            "deployment": "sandbox-consumer-rollout",
            "image_ref": record.get("candidate_image_ref") or record.get("source_image_ref") or "",
            "ready_at": "1970-01-01T00:00:00Z",
            "validation_mode": args.validation_mode,
            "validation_run_id": validation_run_id,
            "revalidation_generation": args.generation,
            "synthetic": True,
        }

        failure_json = json.dumps(failure_artifact, ensure_ascii=False, indent=2)
        normal_json = json.dumps(normal_artifact, ensure_ascii=False, indent=2)
        ready_json = json.dumps(ready_stub, ensure_ascii=False, indent=2)

        mapping = {
            "JOB_NAME": job_name,
            "NAMESPACE": args.namespace,
            "CASE_ID": args.case_id,
            "VALIDATION_MODE": args.validation_mode,
            "VALIDATION_RUN_ID": validation_run_id,
            "REVALIDATION_GENERATION": str(args.generation),
            "KAFKA_BOOTSTRAP": args.kafka_bootstrap,
            "REPLAY_TOPIC": args.replay_topic,
            "RESULT_TOPIC": args.result_topic,
            "FAILURE_ARTIFACT_PATH": args.failure_artifact_path,
            "NORMAL_ARTIFACT_PATH": args.normal_artifact_path,
            "ENABLE_NORMAL_VALIDATION": args.enable_normal_validation,
            "EXPECTED_FAILURE_STATUS": args.expected_failure_status,
            "EXPECTED_NORMAL_STATUS": args.expected_normal_status,
            "LAUNCHER_IMAGE_REF": args.launcher_image_ref,
            "FAILURE_ARTIFACT_JSON": indent_for_block_scalar(failure_json, 14),
            "NORMAL_ARTIFACT_JSON": indent_for_block_scalar(normal_json, 14),
            "READY_FILE_JSON": indent_for_block_scalar(ready_json, 14),
        }

        template = load_text(template_path)
        rendered = render_template(template, mapping)
        ensure_no_placeholders_left(rendered)
        dump_text(output_path, rendered)

        patch_sandbox_manifest_for_revalidation(
            manifest_path=sandbox_manifest_path,
            case_id=args.case_id,
            generation=args.generation,
            validation_run_id=validation_run_id,
            expected_failure_status=args.expected_failure_status,
            expected_normal_status=args.expected_normal_status,
        )

        if args.update_record:
            maybe_update_case_record(
                case_id=args.case_id,
                records_dir=records_dir,
                generation=args.generation,
                validation_run_id=validation_run_id,
                output_path=output_path,
                note=args.note,
                expected_failure_status=args.expected_failure_status,
                expected_normal_status=args.expected_normal_status,
            )

        result = {
            "case_id": args.case_id,
            "template_path": str(template_path),
            "output_path": str(output_path),
            "job_name": job_name,
            "validation_mode": args.validation_mode,
            "validation_run_id": validation_run_id,
            "revalidation_generation": args.generation,
            "sandbox_manifest_path": str(sandbox_manifest_path),
            "record_updated": bool(args.update_record),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())