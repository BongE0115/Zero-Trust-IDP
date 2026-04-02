#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Dict, Optional

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


def maybe_update_case_record(
    *,
    case_id: str,
    records_dir: Path,
    generation: int,
    validation_run_id: str,
    output_path: Path,
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
        "revalidation_requested",
        "--revalidation-generation",
        str(generation),
        "--validation-run-id",
        validation_run_id,
        "--metadata-json",
        json.dumps({"revalidation_job_manifest_path": str(output_path)}, ensure_ascii=False),
        "--note",
        note,
    ]
    subprocess.run(cmd, check=True)


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
            raise ValueError(
                "revalidation renderer is only for fix-verify mode at this stage"
            )

        template_path = Path(args.template_path)
        output_dir = Path(args.output_dir)
        validation_run_id = args.validation_run_id or f"{args.case_id}-reval-{args.generation}-{uuid.uuid4().hex[:8]}"

        safe_suffix = sanitize_name(args.case_id, max_len=40)
        job_name = f"forensic-revalidate-{safe_suffix}-g{args.generation}"
        output_path = (
            Path(args.output_path)
            if args.output_path
            else output_dir / f"revalidate-case-{args.case_id}.yaml"
        )

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
        }

        template = load_text(template_path)
        rendered = render_template(template, mapping)
        ensure_no_placeholders_left(rendered)
        dump_text(output_path, rendered)

        if args.update_record:
            maybe_update_case_record(
                case_id=args.case_id,
                records_dir=Path(args.records_dir),
                generation=args.generation,
                validation_run_id=validation_run_id,
                output_path=output_path,
                note=args.note,
            )

        result = {
            "case_id": args.case_id,
            "template_path": str(template_path),
            "output_path": str(output_path),
            "job_name": job_name,
            "validation_mode": args.validation_mode,
            "validation_run_id": validation_run_id,
            "revalidation_generation": args.generation,
            "record_updated": bool(args.update_record),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())