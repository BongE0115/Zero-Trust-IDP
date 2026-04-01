#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RECORDS_DIR = REPO_ROOT / "gitops" / "apps" / "forensic-sandbox" / "cases" / "records"


def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"JSON file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"JSON root must be object: {path}")
    return data


def run_update_case_record(args_list: list[str]) -> None:
    script = REPO_ROOT / "scripts" / "update_case_record.py"
    if not script.exists():
        raise FileNotFoundError(f"update_case_record.py not found: {script}")

    cmd = [sys.executable, str(script)] + args_list
    subprocess.run(cmd, check=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect revalidation verdict and write final result into case record."
    )
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--verdict-path", required=True)
    parser.add_argument(
        "--records-dir",
        default=str(DEFAULT_RECORDS_DIR),
        help=f"Directory containing case records (default: {DEFAULT_RECORDS_DIR})",
    )
    parser.add_argument(
        "--note",
        default="revalidation verdict collected",
        help="Note to store in case record history",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        records_dir = Path(args.records_dir)
        record_path = records_dir / f"{args.case_id}.json"
        verdict_path = Path(args.verdict_path)

        record = load_json(record_path)
        verdict = load_json(verdict_path)

        candidate_image_ref = record.get("candidate_image_ref")
        if not candidate_image_ref:
            raise ValueError("case record has empty candidate_image_ref")

        verdict_case_id = verdict.get("case_id")
        if verdict_case_id != args.case_id:
            raise ValueError(
                f"verdict case_id mismatch: expected={args.case_id}, actual={verdict_case_id}"
            )

        overall_passed = verdict.get("overall_passed") is True
        validation_run_id = verdict.get("validation_run_id", "")
        revalidation_generation = int(verdict.get("revalidation_generation", 0))
        validation_mode = verdict.get("validation_mode", "")
        launcher_image_ref = verdict.get("launcher_image_ref", "")

        metadata_patch = {
            "last_revalidation_verdict_path": str(verdict_path),
            "last_revalidation_overall_passed": overall_passed,
            "last_revalidation_mode": validation_mode,
            "last_revalidation_launcher_image_ref": launcher_image_ref,
        }

        common_args = [
            "--records-dir",
            str(records_dir),
            "update",
            "--case-id",
            args.case_id,
            "--revalidation-generation",
            str(revalidation_generation),
            "--validation-run-id",
            validation_run_id,
            "--metadata-json",
            json.dumps(metadata_patch, ensure_ascii=False),
            "--note",
            args.note,
        ]

        if overall_passed:
            # revalidation 성공 -> verified image = candidate image
            run_update_case_record(
                common_args
                + [
                    "--status",
                    "revalidation_passed",
                    "--verified-image-ref",
                    candidate_image_ref,
                    "--flags-json",
                    json.dumps({"revalidation_passed": True}, ensure_ascii=False),
                ]
            )
            result = {
                "case_id": args.case_id,
                "status": "revalidation_passed",
                "verified_image_ref": candidate_image_ref,
                "validation_run_id": validation_run_id,
                "revalidation_generation": revalidation_generation,
                "verdict_path": str(verdict_path),
            }
        else:
            error_info = verdict.get("error", {})
            metadata_patch["last_revalidation_error"] = error_info
            run_update_case_record(
                [
                    "--records-dir",
                    str(records_dir),
                    "update",
                    "--case-id",
                    args.case_id,
                    "--status",
                    "failed",
                    "--revalidation-generation",
                    str(revalidation_generation),
                    "--validation-run-id",
                    validation_run_id,
                    "--flags-json",
                    json.dumps({"revalidation_passed": False}, ensure_ascii=False),
                    "--metadata-json",
                    json.dumps(metadata_patch, ensure_ascii=False),
                    "--note",
                    args.note,
                ]
            )
            result = {
                "case_id": args.case_id,
                "status": "failed",
                "verified_image_ref": None,
                "validation_run_id": validation_run_id,
                "revalidation_generation": revalidation_generation,
                "verdict_path": str(verdict_path),
                "error": error_info,
            }

        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())