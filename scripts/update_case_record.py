
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RECORDS_DIR = REPO_ROOT / "gitops" / "apps" / "forensic-sandbox" / "cases" / "records"

ALLOWED_STATUSES = {
    "sandbox_created",
    "branch_created",
    "candidate_built",
    "revalidation_requested",
    "revalidation_passed",
    "promoted",
    "redriven",
    "resolved",
    "cleanup_completed",
    "failed",
}

SAFE_CASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_json_maybe(value: Optional[str], field_name: str) -> Optional[Any]:
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field_name} must be valid JSON: {exc}") from exc


def require_safe_case_id(case_id: str) -> None:
    if not SAFE_CASE_ID_PATTERN.fullmatch(case_id):
        raise ValueError(
            "case_id contains unsupported characters. "
            "Use only letters, numbers, dot(.), underscore(_), hyphen(-)."
        )


def deep_merge(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    result = deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


@dataclass
class RecordStore:
    records_dir: Path

    def ensure_dir(self) -> None:
        self.records_dir.mkdir(parents=True, exist_ok=True)

    def record_path(self, case_id: str) -> Path:
        return self.records_dir / f"{case_id}.json"

    def exists(self, case_id: str) -> bool:
        return self.record_path(case_id).exists()

    def load(self, case_id: str) -> Dict[str, Any]:
        path = self.record_path(case_id)
        if not path.exists():
            raise FileNotFoundError(f"case record not found: {path}")
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def save(self, case_id: str, data: Dict[str, Any]) -> Path:
        self.ensure_dir()
        path = self.record_path(case_id)
        with path.open("w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=False)
            f.write("\n")
        return path


def default_record(case_id: str, now: str) -> Dict[str, Any]:
    return {
        "case_id": case_id,
        "service": None,
        "branch_name": None,
        "status": None,
        "created_at": now,
        "updated_at": now,
        "source_image_ref": None,
        "candidate_image_ref": None,
        "verified_image_ref": None,
        "promoted_image_ref": None,
        "previous_production_image_ref": None,
        "sandbox_manifest_path": None,
        "revalidation_generation": 0,
        "validation_run_id": None,
        "redrive_count": 0,
        "flags": {
            "revalidation_passed": False,
            "promoted": False,
            "redriven": False,
            "resolved": False,
            "cleanup_completed": False,
        },
        "metadata": {},
        "history": [],
    }


def append_history(
    record: Dict[str, Any],
    *,
    action: str,
    status: Optional[str],
    note: Optional[str],
    now: str,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    entry: Dict[str, Any] = {
        "at": now,
        "action": action,
        "status": status,
    }
    if note:
        entry["note"] = note
    if extra:
        entry["extra"] = extra
    record.setdefault("history", []).append(entry)


def set_flag_defaults(record: Dict[str, Any]) -> None:
    flags = record.setdefault("flags", {})
    flags.setdefault("revalidation_passed", False)
    flags.setdefault("promoted", False)
    flags.setdefault("redriven", False)
    flags.setdefault("resolved", False)
    flags.setdefault("cleanup_completed", False)
    record.setdefault("metadata", {})
    record.setdefault("history", [])
    record.setdefault("redrive_count", 0)
    record.setdefault("revalidation_generation", 0)


def validate_status(status: Optional[str]) -> None:
    if status is None:
        return
    if status not in ALLOWED_STATUSES:
        raise ValueError(
            f"unsupported status '{status}'. Allowed: {', '.join(sorted(ALLOWED_STATUSES))}"
        )


def derive_flag_updates(status: Optional[str]) -> Dict[str, bool]:
    if status is None:
        return {}
    mapping: Dict[str, Dict[str, bool]] = {
        "revalidation_passed": {"revalidation_passed": True},
        "promoted": {"promoted": True},
        "redriven": {"redriven": True},
        "resolved": {"resolved": True},
        "cleanup_completed": {"cleanup_completed": True},
    }
    return mapping.get(status, {})


def create_record(args: argparse.Namespace, store: RecordStore) -> int:
    require_safe_case_id(args.case_id)
    validate_status(args.status)

    if store.exists(args.case_id) and not args.force:
        raise FileExistsError(
            f"case record already exists: {store.record_path(args.case_id)} "
            "(use --force to overwrite)"
        )

    now = utc_now_iso()
    record = default_record(args.case_id, now)

    if args.service:
        record["service"] = args.service
    if args.branch_name:
        record["branch_name"] = args.branch_name
    if args.status:
        record["status"] = args.status
    if args.source_image_ref:
        record["source_image_ref"] = args.source_image_ref
    if args.candidate_image_ref:
        record["candidate_image_ref"] = args.candidate_image_ref
    if args.verified_image_ref:
        record["verified_image_ref"] = args.verified_image_ref
    if args.promoted_image_ref:
        record["promoted_image_ref"] = args.promoted_image_ref
    if args.previous_production_image_ref:
        record["previous_production_image_ref"] = args.previous_production_image_ref
    if args.sandbox_manifest_path:
        record["sandbox_manifest_path"] = args.sandbox_manifest_path
    if args.revalidation_generation is not None:
        record["revalidation_generation"] = args.revalidation_generation
    if args.validation_run_id:
        record["validation_run_id"] = args.validation_run_id
    if args.redrive_count is not None:
        record["redrive_count"] = args.redrive_count

    if args.metadata_json:
        record["metadata"] = parse_json_maybe(args.metadata_json, "metadata_json") or {}

    if args.flags_json:
        flags_patch = parse_json_maybe(args.flags_json, "flags_json") or {}
        if not isinstance(flags_patch, dict):
            raise ValueError("flags_json must be a JSON object")
        record["flags"] = deep_merge(record["flags"], flags_patch)

    record["flags"] = deep_merge(record["flags"], derive_flag_updates(args.status))
    record["updated_at"] = now

    append_history(
        record,
        action="create",
        status=record["status"],
        note=args.note,
        now=now,
    )

    path = store.save(args.case_id, record)
    print(str(path))
    return 0


def update_record(args: argparse.Namespace, store: RecordStore) -> int:
    require_safe_case_id(args.case_id)
    validate_status(args.status)

    record = store.load(args.case_id)
    set_flag_defaults(record)
    now = utc_now_iso()

    before_status = record.get("status")

    if args.service is not None:
        record["service"] = args.service
    if args.branch_name is not None:
        record["branch_name"] = args.branch_name
    if args.status is not None:
        record["status"] = args.status
    if args.source_image_ref is not None:
        record["source_image_ref"] = args.source_image_ref
    if args.candidate_image_ref is not None:
        record["candidate_image_ref"] = args.candidate_image_ref
    if args.verified_image_ref is not None:
        record["verified_image_ref"] = args.verified_image_ref
    if args.promoted_image_ref is not None:
        record["promoted_image_ref"] = args.promoted_image_ref
    if args.previous_production_image_ref is not None:
        record["previous_production_image_ref"] = args.previous_production_image_ref
    if args.sandbox_manifest_path is not None:
        record["sandbox_manifest_path"] = args.sandbox_manifest_path
    if args.revalidation_generation is not None:
        record["revalidation_generation"] = args.revalidation_generation
    if args.validation_run_id is not None:
        record["validation_run_id"] = args.validation_run_id
    if args.redrive_count is not None:
        record["redrive_count"] = args.redrive_count
    if args.increment_redrive:
        record["redrive_count"] = int(record.get("redrive_count", 0)) + 1

    if args.metadata_json:
        metadata_patch = parse_json_maybe(args.metadata_json, "metadata_json") or {}
        if not isinstance(metadata_patch, dict):
            raise ValueError("metadata_json must be a JSON object")
        record["metadata"] = deep_merge(record.get("metadata", {}), metadata_patch)

    if args.flags_json:
        flags_patch = parse_json_maybe(args.flags_json, "flags_json") or {}
        if not isinstance(flags_patch, dict):
            raise ValueError("flags_json must be a JSON object")
        record["flags"] = deep_merge(record["flags"], flags_patch)

    record["flags"] = deep_merge(record["flags"], derive_flag_updates(args.status))
    record["updated_at"] = now

    extra: Dict[str, Any] = {}
    if before_status != record.get("status"):
        extra["from_status"] = before_status
        extra["to_status"] = record.get("status")

    append_history(
        record,
        action="update",
        status=record.get("status"),
        note=args.note,
        now=now,
        extra=extra or None,
    )

    path = store.save(args.case_id, record)
    print(str(path))
    return 0


def show_record(args: argparse.Namespace, store: RecordStore) -> int:
    require_safe_case_id(args.case_id)
    record = store.load(args.case_id)
    print(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create and update case lifecycle records for forensic sandbox workflows."
    )
    parser.add_argument(
        "--records-dir",
        default=str(DEFAULT_RECORDS_DIR),
        help=f"Directory containing case record JSON files (default: {DEFAULT_RECORDS_DIR})",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    common_fields = argparse.ArgumentParser(add_help=False)
    common_fields.add_argument("--case-id", required=True)
    common_fields.add_argument("--service")
    common_fields.add_argument("--branch-name")
    common_fields.add_argument("--status")
    common_fields.add_argument("--source-image-ref")
    common_fields.add_argument("--candidate-image-ref")
    common_fields.add_argument("--verified-image-ref")
    common_fields.add_argument("--promoted-image-ref")
    common_fields.add_argument("--previous-production-image-ref")
    common_fields.add_argument("--sandbox-manifest-path")
    common_fields.add_argument("--revalidation-generation", type=int)
    common_fields.add_argument("--validation-run-id")
    common_fields.add_argument("--redrive-count", type=int)
    common_fields.add_argument("--metadata-json")
    common_fields.add_argument("--flags-json")
    common_fields.add_argument("--note")

    create_parser = subparsers.add_parser("create", parents=[common_fields])
    create_parser.add_argument("--force", action="store_true")

    update_parser = subparsers.add_parser("update", parents=[common_fields])
    update_parser.add_argument("--increment-redrive", action="store_true")

    subparsers.add_parser("show", parents=[argparse.ArgumentParser(add_help=False)])
    show_parser = subparsers.choices["show"]
    show_parser.add_argument("--case-id", required=True)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        store = RecordStore(Path(args.records_dir))
        if args.command == "create":
            return create_record(args, store)
        if args.command == "update":
            return update_record(args, store)
        if args.command == "show":
            return show_record(args, store)
        parser.error(f"unsupported command: {args.command}")
        return 2
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())