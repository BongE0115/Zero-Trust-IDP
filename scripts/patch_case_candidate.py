#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import uuid
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
            default_flow_style=False,
        )


def find_deployment(docs: List[Dict[str, Any]]) -> Dict[str, Any]:
    deployments = [d for d in docs if d.get("kind") == "Deployment"]
    if not deployments:
        raise ValueError("no Deployment found in manifest")
    if len(deployments) > 1:
        # 케이스 manifest는 일반적으로 sandbox deployment 1개를 기준으로 본다.
        # 여러 개면 name 기반 필터를 추가로 넣는 게 안전하지만,
        # 지금 단계에서는 단일 deployment를 전제한다.
        raise ValueError("multiple Deployments found; expected exactly one sandbox deployment")
    return deployments[0]


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


def get_containers(deployment: Dict[str, Any]) -> List[Dict[str, Any]]:
    containers = deployment.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
    if not containers:
        raise ValueError("deployment has no containers")
    return containers


def find_container_by_name(containers: List[Dict[str, Any]], name: str) -> Dict[str, Any]:
    for container in containers:
        if container.get("name") == name:
            return container
    raise ValueError(f"container '{name}' not found")


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


def get_env_value(container: Dict[str, Any], name: str) -> Optional[str]:
    for item in get_env_list(container):
        if item.get("name") == name:
            return item.get("value")
    return None


def maybe_update_case_record(
    *,
    records_dir: Path,
    case_id: str,
    candidate_image_ref: str,
    manifest_path: Path,
    generation: int,
    validation_run_id: str,
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
        "--revalidation-generation",
        str(generation),
        "--validation-run-id",
        validation_run_id,
        "--flags-json",
        json.dumps({"revalidation_passed": False}, ensure_ascii=False),
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
    validation_run_id: str,
    set_case_configmap: bool,
) -> Tuple[str, str]:
    docs = load_yaml_all(manifest_path)

    deployment = find_deployment(docs)
    consumer = find_container_by_name(get_containers(deployment), "consumer-app")

    previous_image_ref = consumer.get("image")
    if not previous_image_ref:
        raise ValueError("consumer-app.image is empty")

    consumer["image"] = candidate_image_ref
    upsert_env(consumer, "IMAGE_REF", candidate_image_ref)

    # 수정 후 재검증 모드 강제
    upsert_env(consumer, "VALIDATION_MODE", "fix-verify")
    upsert_env(consumer, "REVALIDATION_GENERATION", str(generation))
    upsert_env(consumer, "VALIDATION_RUN_ID", validation_run_id)
    upsert_env(consumer, "CASE_ID", case_id)

    # sandbox strict 쪽은 유지하되, 혹시 빠져 있으면 기본값 고정
    if not get_env_value(consumer, "ISOLATION_MODE"):
        upsert_env(consumer, "ISOLATION_MODE", "sandbox_strict")

    # ConfigMap도 같이 갱신할 수 있게 처리
    if set_case_configmap:
        configmap = find_configmap_for_case(docs, case_id)
        if configmap is not None:
            data = configmap.setdefault("data", {})
            data["case_id"] = case_id
            data["candidate_image_ref"] = candidate_image_ref
            data["validation_mode"] = "fix-verify"
            data["revalidation_generation"] = str(generation)
            data["validation_run_id"] = validation_run_id

    dump_yaml_all(manifest_path, docs)
    return previous_image_ref, candidate_image_ref


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Patch a case sandbox manifest to use a candidate consumer image digest."
    )
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--manifest-path", required=True)
    parser.add_argument("--candidate-image-ref", required=True)
    parser.add_argument("--generation", type=int, default=1)
    parser.add_argument("--validation-run-id")
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
        validation_run_id = args.validation_run_id or f"{args.case_id}-reval-{args.generation}-{uuid.uuid4().hex[:8]}"

        old_ref, new_ref = patch_manifest(
            manifest_path=manifest_path,
            case_id=args.case_id,
            candidate_image_ref=args.candidate_image_ref,
            generation=args.generation,
            validation_run_id=validation_run_id,
            set_case_configmap=args.set_case_configmap,
        )

        if args.update_record:
            maybe_update_case_record(
                records_dir=records_dir,
                case_id=args.case_id,
                candidate_image_ref=args.candidate_image_ref,
                manifest_path=manifest_path,
                generation=args.generation,
                validation_run_id=validation_run_id,
                note=args.note,
            )

        result = {
            "case_id": args.case_id,
            "manifest_path": str(manifest_path),
            "previous_image_ref": old_ref,
            "candidate_image_ref": new_ref,
            "revalidation_generation": args.generation,
            "validation_run_id": validation_run_id,
            "record_updated": bool(args.update_record),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())