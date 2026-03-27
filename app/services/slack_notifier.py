import requests
from app.config.settings import settings


def send_slack_alert(event: dict, score: float):

    # 🔥 재처리 데이터는 Slack skip
    if event.get("is_reprocessed"):
        print("[Slack] skip reprocessed event")
        return

    # 🔥 payload 안전 추출
    payload_data = event.get("payload") or event.get("original_payload") or {}

    metric_name = payload_data.get("metric_name", "unknown")
    metric_value = payload_data.get("metric_value", "unknown")
    severity = event.get("severity", "unknown")

    url = "https://slack.com/api/chat.postMessage"

    headers = {
        "Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "channel": settings.SLACK_CHANNEL,
        "text": "🚨 Anomaly Detected",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "🚨 *Anomaly Detected*\n\n"
                        f"• Metric: {metric_name}\n"
                        f"• Value: {metric_value}\n"
                        f"• Score: {score:.4f}\n"
                        f"• Severity: {severity}"
                    ),
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "🔄 Redrive"
                        },
                        "value": "run_redrive",
                        "action_id": "redrive_button"
                    }
                ]
            }
        ]
    }

    try:
        res = requests.post(url, headers=headers, json=payload)
        result = res.json()

        if not result.get("ok"):
            print(f"[Slack ERROR] {result}")
        else:
            print("[Slack] alert sent")

    except Exception as e:
        print(f"[Slack EXCEPTION] {e}")