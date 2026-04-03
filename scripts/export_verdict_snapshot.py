#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VERDICTS_DIR = REPO_ROOT / "gitops" / "apps" / "forensic-sandbox" / "cases" / "verdicts"

SAFE_CASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


def require_safe_case_id(case_id: str) -> None:
    if not SAFE_CASE_ID_PATTERN.fullmatch(case_id):
        raise ValueError(
            "case_id contains unsupported characters. "
            "Use only letters, numbers, dot(.), underscore(_), hyphen(-)."
        )


def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"JSON file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"JSON root must be object: {path}")
    return data


def dump_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=False)
        f.write("\n")


def build_default_output_path(
    *,
    verdicts_dir: Path,
    case_id: str,
    generation: int | None,
    validation_mode: str,
) -> Path:
    mode = (validation_mode or "").strip().lower()

    if mode == "revalidate":
        if generation is None:
            raise ValueError("generation is required when validation_mode=revalidate")
        return verdicts_dir / f"revalidate-{case_id}-g{generation}.json"

    if mode == "reproduce":
        if generation is None:
            raise ValueError("generation is required when validation_mode=reproduce")
        return verdicts_dir / f"reproduce-{case_id}-g{generation}.json"

    return verdicts_dir / f"{case_id}.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export a launcher verdict JSON into a repo-managed verdict snapshot path."
    )
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--input-verdict", required=True, help="Path to source verdict JSON")
    parser.add_argument(
        "--verdicts-dir",
        default=str(DEFAULT_VERDICTS_DIR),
        help=f"Directory containing verdict snapshots (default: {DEFAULT_VERDICTS_DIR})",
    )
    parser.add_argument(
        "--generation",
        type=int,
        help="Optional generation number used when building a default output filename",
    )
    parser.add_argument(
        "--validation-mode",
        default="",
        help="Optional validation mode used when building a default output filename "
             "(e.g. revalidate, reproduce)",
    )
    parser.add_argument(
        "--output-path",
        help="Optional explicit output path. "
             "If omitted, defaults are mode-aware, e.g. "
             "revalidate-<case-id>-g<generation>.json",
    )
    parser.add_argument(
        "--annotate-source-path",
        action="store_true",
        help="Add _snapshot metadata including source verdict path",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        require_safe_case_id(args.case_id)

        input_path = Path(args.input_verdict)
        verdicts_dir = Path(args.verdicts_dir)

        output_path = (
            Path(args.output_path)
            if args.output_path
            else build_default_output_path(
                verdicts_dir=verdicts_dir,
                case_id=args.case_id,
                generation=args.generation,
                validation_mode=args.validation_mode,
            )
        )

        verdict = load_json(input_path)

        verdict_case_id = verdict.get("case_id")
        if verdict_case_id != args.case_id:
            raise ValueError(
                f"verdict case_id mismatch: expected={args.case_id}, actual={verdict_case_id}"
            )

        if args.annotate_source_path:
            verdict["_snapshot"] = {
                "source_verdict_path": str(input_path),
                "snapshot_path": str(output_path),
                "validation_mode": args.validation_mode,
                "generation": args.generation,
            }

        dump_json(output_path, verdict)

        print(
            json.dumps(
                {
                    "case_id": args.case_id,
                    "input_verdict": str(input_path),
                    "output_path": str(output_path),
                    "validation_mode": args.validation_mode,
                    "generation": args.generation,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())