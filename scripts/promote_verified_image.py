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
DEFAULT_PRODUCTION_MANIFEST = (
    REPO_ROOT / "gitops" / "apps" / "kafka-poc" / "manifests" / "21-consumer.yaml"
)
DEFAULT_RECORDS_DIR = REPO_ROOT / "gitops" / "apps" / "forensic-sandbox" / "cases" / "records"

DIGEST_IMAGE_PATTERN = re.compile(r"^[^:@]+(?:/[^:@]+)*@sha256:[0-9a-f]{64}$")
SAFE_CASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


def require_digest_image_ref(image_ref: str) -> None:
    if not DIGEST_IMAGE_PATTERN.fullmatch(image_ref):
        raise ValueError(
            "verified image must be a digest-pinned reference like "
            "'ghcr.io/org/image@sha256:<64hex>'"
        )


def require_safe_case_id(case_id: str) -> None:
    if not SAFE_CASE_ID_PATTERN.fullmatch(case_id):
        raise ValueError(
            "case_id contains unsupported characters. "
            "Use only letters, numbers, dot(.), underscore(_), hyphen(-)."
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


def find_target_deployment(docs: List[Dict[str, Any]], deployment_name: str, namespace: Optional[str]) -> Dict[str, Any]:
    for doc in docs:
        if doc.get("kind") != "Deployment":
            continue
        metadata = doc.get("metadata", {})
        if metadata.get("name") != deployment_name:
            continue
        if namespace is not None and metadata.get("namespace") != namespace:
            continue
        return doc
    ns_desc = namespace if namespace is not None else "*"
    raise ValueError(f"Deployment '{deployment_name}' in namespace '{ns_desc}' not found")


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


def maybe_update_case_record(
    *,
    case_id: str,
    records_dir: Path,
    verified_image_ref: str,
    previous_image_ref: str,
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
        "promoted",
        "--verified-image-ref",
        verified_image_ref,
        "--promoted-image-ref",
        verified_image_ref,
        "--previous-production-image-ref",
        previous_image_ref,
        "--flags-json",
        json.dumps({"promoted": True}, ensure_ascii=False),
        "--note",
        note,
    ]
    subprocess.run(cmd, check=True)


def promote_manifest(
    *,
    manifest_path: Path,
    deployment_name: str,
    container_name: str,
    namespace: Optional[str],
    verified_image_ref: str,
) -> Tuple[str, str]:
    docs = load_yaml_all(manifest_path)
    deployment = find_target_deployment(docs, deployment_name, namespace)

    containers = deployment.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
    if not containers:
        raise ValueError("target deployment has no containers")

    container = find_container_by_name(containers, container_name)

    previous_image_ref = container.get("image")
    if not previous_image_ref:
        raise ValueError("target container image is empty")

    container["image"] = verified_image_ref
    upsert_env(container, "IMAGE_REF", verified_image_ref)

    dump_yaml_all(manifest_path, docs)
    return previous_image_ref, verified_image_ref


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Promote a verified digest-pinned consumer image into the production manifest."
    )
    parser.add_argument("--verified-image-ref", required=True)
    parser.add_argument("--manifest-path", default=str(DEFAULT_PRODUCTION_MANIFEST))
    parser.add_argument("--deployment-name", default="worker-consumer")
    parser.add_argument("--container-name", default="worker-consumer")
    parser.add_argument("--namespace", default="kafka-poc")
    parser.add_argument("--case-id")
    parser.add_argument(
        "--records-dir",
        default=str(DEFAULT_RECORDS_DIR),
        help=f"Directory containing case records (default: {DEFAULT_RECORDS_DIR})",
    )
    parser.add_argument(
        "--update-record",
        action="store_true",
        help="Also update the case record to status=promoted",
    )
    parser.add_argument("--note", default="verified image promoted into production manifest")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        require_digest_image_ref(args.verified_image_ref)
        if args.update_record:
            if not args.case_id:
                raise ValueError("--case-id is required when --update-record is used")
            require_safe_case_id(args.case_id)

        manifest_path = Path(args.manifest_path)
        records_dir = Path(args.records_dir)

        previous_ref, new_ref = promote_manifest(
            manifest_path=manifest_path,
            deployment_name=args.deployment_name,
            container_name=args.container_name,
            namespace=args.namespace,
            verified_image_ref=args.verified_image_ref,
        )

        if args.update_record:
            maybe_update_case_record(
                case_id=args.case_id,
                records_dir=records_dir,
                verified_image_ref=args.verified_image_ref,
                previous_image_ref=previous_ref,
                note=args.note,
            )

        result = {
            "manifest_path": str(manifest_path),
            "deployment_name": args.deployment_name,
            "container_name": args.container_name,
            "previous_image_ref": previous_ref,
            "promoted_image_ref": new_ref,
            "record_updated": bool(args.update_record),
            "case_id": args.case_id,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())