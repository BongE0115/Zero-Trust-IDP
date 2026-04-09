#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import subprocess
import sys
import time
from typing import Any, Dict


def run_aws_cmd(args: list[str]) -> str:
    result = subprocess.run(
        ["aws"] + args,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def read_query() -> Dict[str, Any]:
    raw = sys.stdin.read()
    if not raw:
        raise ValueError("No input query received from Terraform external data source")
    query = json.loads(raw)
    if not isinstance(query, dict):
        raise ValueError("Query must be a JSON object")
    return query


def send_ssm_command(instance_id: str, region: str) -> str:
    commands = [
        "if [ ! -f /etc/rancher/k3s/k3s.yaml ]; then echo '__KUBECONFIG_NOT_READY__'; exit 11; fi",
        "sudo cat /etc/rancher/k3s/k3s.yaml"
    ]

    stdout = run_aws_cmd([
        "ssm", "send-command",
        "--region", region,
        "--instance-ids", instance_id,
        "--document-name", "AWS-RunShellScript",
        "--parameters", json.dumps({"commands": commands}),
        "--query", "Command.CommandId",
        "--output", "text"
    ])
    return stdout


def wait_for_command(command_id: str, instance_id: str, region: str, timeout_seconds: int = 180) -> Dict[str, Any]:
    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        try:
            raw = run_aws_cmd([
                "ssm", "get-command-invocation",
                "--region", region,
                "--command-id", command_id,
                "--instance-id", instance_id,
                "--output", "json"
            ])
            data = json.loads(raw)
            status = data.get("Status", "")

            if status in ("Pending", "InProgress", "Delayed"):
                time.sleep(5)
                continue

            return data

        except subprocess.CalledProcessError:
            time.sleep(5)

    raise TimeoutError("Timed out waiting for SSM command result")


def fetch_kubeconfig_with_retry(instance_id: str, region: str, retries: int = 30, wait_seconds: int = 20) -> str:
    last_error = None

    for _ in range(retries):
        try:
            command_id = send_ssm_command(instance_id, region)
            result = wait_for_command(command_id, instance_id, region)

            status = result.get("Status")
            stdout = result.get("StandardOutputContent", "")
            stderr = result.get("StandardErrorContent", "")

            if "__KUBECONFIG_NOT_READY__" in stdout:
                raise RuntimeError("k3s kubeconfig file is not ready yet")

            if status != "Success":
                raise RuntimeError(f"SSM command failed: status={status}, stderr={stderr}")

            content = stdout.strip()
            if not content:
                raise RuntimeError("Received empty kubeconfig content")

            return content

        except Exception as exc:
            last_error = exc
            print(f"DEBUG: Attempt failed with error: {exc}", file=sys.stderr)
            time.sleep(wait_seconds)

    raise RuntimeError(f"Failed to fetch kubeconfig after retries: {last_error}")


def main() -> None:
    query = read_query()

    instance_id = query.get("instance_id", "").strip()
    region = query.get("region", "").strip()
    api_server_host = query.get("api_server_host", "").strip()

    if not instance_id:
        raise ValueError("instance_id is required")
    if not region:
        raise ValueError("region is required")
    if not api_server_host:
        raise ValueError("api_server_host is required")

    kubeconfig = fetch_kubeconfig_with_retry(instance_id, region)

    kubeconfig = kubeconfig.replace("127.0.0.1", api_server_host)

    kubeconfig_b64 = base64.b64encode(kubeconfig.encode("utf-8")).decode("utf-8")

    result = {
        "kubeconfig_b64": kubeconfig_b64
    }

    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)