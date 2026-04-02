#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from kafka import KafkaConsumer, KafkaProducer

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


def update_case_record(
    *,
    records_dir: Path,
    case_id: str,
    status: str,
    note: str,
    increment_redrive: bool = False,
    metadata_patch: Optional[Dict[str, Any]] = None,
    flags_patch: Optional[Dict[str, Any]] = None,
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
        status,
        "--note",
        note,
    ]

    if increment_redrive:
        cmd.append("--increment-redrive")

    if metadata_patch:
        cmd.extend(["--metadata-json", json.dumps(metadata_patch, ensure_ascii=False)])

    if flags_patch:
        cmd.extend(["--flags-json", json.dumps(flags_patch, ensure_ascii=False)])

    subprocess.run(cmd, check=True)


def get_consumer(*, kafka_bootstrap: str, dlq_topic: str, group_id: str) -> KafkaConsumer:
    return KafkaConsumer(
        dlq_topic,
        bootstrap_servers=kafka_bootstrap,
        group_id=group_id,
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        consumer_timeout_ms=3000,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
    )


def get_producer(*, kafka_bootstrap: str) -> KafkaProducer:
    return KafkaProducer(
        bootstrap_servers=kafka_bootstrap,
        value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
    )


def find_case_failure_event(
    *,
    consumer: KafkaConsumer,
    case_id: str,
    max_scan_messages: int,
) -> Dict[str, Any]:
    scanned = 0

    for message in consumer:
        scanned += 1
        event = message.value

        if not isinstance(event, dict):
            continue

        if event.get("case_id") == case_id:
            consumer.commit()
            return event

        if scanned >= max_scan_messages:
            break

    raise RuntimeError(f"Could not find case_id={case_id} in DLQ within {max_scan_messages} scanned messages")


def validate_failure_event(event: Dict[str, Any], case_id: str) -> Dict[str, Any]:
    if event.get("case_id") != case_id:
        raise ValueError(f"case_id mismatch expected={case_id}, actual={event.get('case_id')}")

    original_payload = event.get("original_payload")
    if not isinstance(original_payload, dict) or not original_payload:
        raise ValueError("failure event does not contain valid original_payload")

    return original_payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Redrive original payload for a specific case from DLQ back into the production topic."
    )
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--kafka-bootstrap", required=True)
    parser.add_argument("--dlq-topic", default="orders-dlq")
    parser.add_argument("--target-topic", default="orders")
    parser.add_argument("--scan-group-id", default="case-redrive-scanner")
    parser.add_argument("--max-scan-messages", type=int, default=10000)
    parser.add_argument(
        "--records-dir",
        default=str(DEFAULT_RECORDS_DIR),
        help=f"Directory containing case records (default: {DEFAULT_RECORDS_DIR})",
    )
    parser.add_argument("--note", default="case messages redriven into production topic")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        records_dir = Path(args.records_dir)
        record_path = records_dir / f"{args.case_id}.json"
        record = load_json(record_path)

        flags = record.get("flags", {})
        if flags.get("promoted") is not True:
            raise RuntimeError("Redrive denied: case is not promoted yet")
        if flags.get("redriven") is True:
            raise RuntimeError("Redrive denied: case already marked as redriven")

        consumer = get_consumer(
            kafka_bootstrap=args.kafka_bootstrap,
            dlq_topic=args.dlq_topic,
            group_id=f"{args.scan_group_id}-{args.case_id}",
        )
        producer = get_producer(kafka_bootstrap=args.kafka_bootstrap)

        try:
            failure_event = find_case_failure_event(
                consumer=consumer,
                case_id=args.case_id,
                max_scan_messages=args.max_scan_messages,
            )
        finally:
            consumer.close()

        original_payload = validate_failure_event(failure_event, args.case_id)

        producer.send(args.target_topic, original_payload)
        producer.flush()
        producer.close()

        metadata_patch = {
            "last_redrive_target_topic": args.target_topic,
            "last_redrive_dlq_topic": args.dlq_topic,
            "last_redrive_original_order_id": original_payload.get("order_id", ""),
            "last_redrive_source_case_id": args.case_id,
        }

        flags_patch = {
            "redriven": True,
        }

        update_case_record(
            records_dir=records_dir,
            case_id=args.case_id,
            status="redriven",
            note=args.note,
            increment_redrive=True,
            metadata_patch=metadata_patch,
            flags_patch=flags_patch,
        )

        result = {
            "case_id": args.case_id,
            "status": "redriven",
            "target_topic": args.target_topic,
            "dlq_topic": args.dlq_topic,
            "order_id": original_payload.get("order_id", ""),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())