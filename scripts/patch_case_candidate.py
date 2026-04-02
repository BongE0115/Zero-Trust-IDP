#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CASES_DIR = REPO_ROOT / "gitops" / "apps" / "forensic-sandbox" / "cases"
DEFAULT_RECORDS_DIR = DEFAULT_CASES_DIR / "records"

DIGEST_IMAGE_PATTERN = re.compile(r"^[^:@]+(?:/[^:@]+)*@sha256:[0-9a-f]{64}$")
SAFE_CASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


def require_safe_case_id(case_id: str) -> None:
    if not SAFE_CASE_ID_PATTERN.fullmatch(case_id):
        raise ValueError(
            "case_id contains unsupported characters. "
            "Use only letters, numbers, dot(.), underscore(_), hyphen(-)."
        )


def require_digest_image_ref(image_ref: str) -> None:
    if not DIGEST_IMAGE_PATTERN.fullmatch(image_ref):
        raise ValueError(
            "candidate image must be a digest-pinned reference like "
            "'ghcr.io/org/image@sha256:<64hex>'"
        )


def deterministic_validation_run_id(case_id: str, generation: int) -> str:
    return f"{case_id}-reval-g{generation}"


def load_yaml_all(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"manifest not found: {path}")
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
        )


def get_deployments(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [doc for doc in docs if doc.get("kind") == "Deployment"]


def get_containers(deployment: Dict[str, Any]) -> List[Dict[str, Any]]:
    spec = deployment.get("spec", {}).get("template", {}).get("spec", {})
    containers = spec.get("containers", [])
    if not isinstance(containers, list):
        raise ValueError("deployment.spec.template.spec.containers must be a list")
    return containers


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

    if len(consumer_candidates) > 1:
        preferred = [
            d for d in consumer_candidates
            if "forensic-sandbox-app" in (d.get("metadata", {}).get("name") or "")
        ]
        if len(preferred) == 1:
            return preferred[0]

        names = [d.get("metadata", {}).get("name", "<unknown>") for d in consumer_candidates]
        raise ValueError(
            "multiple consumer-app deployments found; cannot determine sandbox deployment: "
            + ", ".join(names)
        )

    name_candidates = [
        d for d in deployments
        if "forensic-sandbox-app" in (d.get("metadata", {}).get("name") or "")
    ]
    if len(name_candidates) == 1:
        return name_candidates[0]

    names = [d.get("metadata", {}).get("name", "<unknown>") for d in deployments]
    raise ValueError(
        "sandbox deployment not found. Expected a deployment with container 'consumer-app' "
        "or name containing 'forensic-sandbox-app'. Found deployments: "
        + ", ".join(names)
    )


def find_configmap_for_case(docs: List[Dict[str, Any]], case_id: str) -> Optional[Dict[str, Any]]:
    for doc in docs:
        if doc.get("kind") != "ConfigMap":
            continue
        data = doc.get("data") or {}
        if data.get("case_id") == case_id:
            return doc
        labels = doc.get("metadata", {}).get("labels", {})
        if labels.get("forensic-case-id") == case_id:
            return doc
    return None


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


def maybe_update_case_record(
    *,
    records_dir: Path,
    case_id: str,
    candidate_image_ref: str,
    manifest_path: Path,
    note: str,
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
        "candidate_built",
        "--candidate-image-ref",
        candidate_image_ref,
        "--sandbox-manifest-path",
        str(manifest_path),
        "--validation-run-id",
        "",
        "--verified-image-ref",
        "",
        "--promoted-image-ref",
        "",
        "--flags-json",
        json.dumps(
            {
                "revalidation_passed": False,
                "promoted": False,
                "resolved": False,
                "cleanup_completed": False,
            },
            ensure_ascii=False,
        ),
        "--note",
        note,
    ]
    subprocess.run(cmd, check=True)


def patch_manifest(
    *,
    manifest_path: Path,
    case_id: str,
    candidate_image_ref: str,
    generation: int,
    set_case_configmap: bool,
) -> Tuple[str, str, str, str]:
    docs = load_yaml_all(manifest_path)

    deployment = find_sandbox_deployment(docs)
    deployment_name = deployment.get("metadata", {}).get("name", "<unknown>")
    consumer = find_container_by_name(get_containers(deployment), "consumer-app")

    previous_image_ref = consumer.get("image")
    if not previous_image_ref:
        raise ValueError("consumer-app.image is empty")

    validation_run_id = deterministic_validation_run_id(case_id, generation)

    consumer["image"] = candidate_image_ref
    upsert_env(consumer, "IMAGE_REF", candidate_image_ref)

    # 수정 후 검증 준비 상태
    upsert_env(consumer, "VALIDATION_MODE", "fix-verify")
    upsert_env(consumer, "REVALIDATION_GENERATION", str(generation))
    upsert_env(consumer, "VALIDATION_RUN_ID", validation_run_id)
    upsert_env(consumer, "CASE_ID", case_id)

    # sandbox strict 보장
    upsert_env(consumer, "ISOLATION_MODE", "sandbox_strict")

    # 수정 후 기대 상태
    upsert_env(consumer, "EXPECTED_FAILURE_STATUS", "success")
    upsert_env(consumer, "EXPECTED_NORMAL_STATUS", "success")

    if set_case_configmap:
        configmap = find_configmap_for_case(docs, case_id)
        if configmap is not None:
            data = configmap.setdefault("data", {})
            data["case_id"] = case_id
            data["candidate_image_ref"] = candidate_image_ref
            data["consumer_image_ref"] = candidate_image_ref
            data["validation_mode"] = "fix-verify"
            data["revalidation_generation"] = str(generation)
            data["validation_run_id"] = validation_run_id
            data["deployment_name"] = deployment_name

    dump_yaml_all(manifest_path, docs)
    return previous_image_ref, candidate_image_ref, deployment_name, validation_run_id


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Patch a case sandbox manifest to use a candidate consumer image digest."
    )
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--manifest-path", required=True)
    parser.add_argument("--candidate-image-ref", required=True)
    parser.add_argument("--generation", type=int, default=1)
    parser.add_argument(
        "--records-dir",
        default=str(DEFAULT_RECORDS_DIR),
        help=f"Directory containing case records (default: {DEFAULT_RECORDS_DIR})",
    )
    parser.add_argument(
        "--update-record",
        action="store_true",
        help="Also update the case record to status=candidate_built",
    )
    parser.add_argument(
        "--set-case-configmap",
        action="store_true",
        help="Also update the case-specific ConfigMap if one exists in the same manifest",
    )
    parser.add_argument("--note", default="candidate image patched into sandbox manifest")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        require_safe_case_id(args.case_id)
        require_digest_image_ref(args.candidate_image_ref)

        manifest_path = Path(args.manifest_path)
        records_dir = Path(args.records_dir)

        old_ref, new_ref, deployment_name, validation_run_id = patch_manifest(
            manifest_path=manifest_path,
            case_id=args.case_id,
            candidate_image_ref=args.candidate_image_ref,
            generation=args.generation,
            set_case_configmap=args.set_case_configmap,
        )

        if args.update_record:
            maybe_update_case_record(
                records_dir=records_dir,
                case_id=args.case_id,
                candidate_image_ref=args.candidate_image_ref,
                manifest_path=manifest_path,
                note=args.note,
            )

        result = {
            "case_id": args.case_id,
            "manifest_path": str(manifest_path),
            "sandbox_deployment_name": deployment_name,
            "previous_image_ref": old_ref,
            "candidate_image_ref": new_ref,
            "revalidation_generation_prepared": args.generation,
            "validation_run_id_prepared": validation_run_id,
            "record_updated": bool(args.update_record),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())