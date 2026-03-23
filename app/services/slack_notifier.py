import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")


def send_slack_alert(event: dict, score: float):
    message = {
        "text": f"""
🚨 *Anomaly Detected*

• Metric: {event.get("metric_name")}
• Value: {event.get("metric_value")}
• Score: {score:.4f}
• Threshold: {event.get("threshold")}
• Severity: {event.get("severity")}
• Message: {event.get("message")}
"""
    }

    response = requests.post(
        SLACK_WEBHOOK_URL,
        data=json.dumps(message),
        headers={"Content-Type": "application/json"},
    )

    print(f"[Slack] status={response.status_code}")
    print(f"[Slack] response={response.text}")