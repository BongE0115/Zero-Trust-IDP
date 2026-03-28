import requests
import json
from app.config.settings import settings

def send_slack_alert(event: dict, score: float = 0.0):
    """
    DLQ 에러 및 이상 탐지 발생 시 Slack으로 버튼이 포함된 카드를 발송합니다.
    """
    # 1. 재처리 데이터(Redriven)는 중복 알림 방지를 위해 스킵
    if event.get("is_reprocessed"):
        print("[Slack] skip reprocessed event")
        return

    # 2. 데이터 추출 (DLQ 메타데이터 또는 일반 페이로드)
    # dlq_producer에서 보낸 구조를 우선적으로 참조합니다.
    error_type = event.get("error_type", "Unknown Error")
    source_service = event.get("source_service", "unknown-service")
    timestamp = event.get("timestamp", "N/A")
    
    # 시나리오 A를 위한 DB 컨텍스트 추출
    dep_context = event.get("dependency_context", {})
    target_db = dep_context.get("db_name", "N/A")
    target_coll = dep_context.get("collection", "N/A")

    # 원본 데이터 요약
    payload_data = event.get("original_payload") or event.get("payload") or {}
    message_summary = str(payload_data.get("message", "No message content"))[:50]

    url = "https://slack.com/api/chat.postMessage"
    headers = {
        "Authorization": f"Bearer {settings.SLACK_BOT_TOKEN}",
        "Content-Type": "application/json"
    }

    # 3. Slack Block Kit 구성 (샌드박스 버튼 추가)
    payload = {
        "channel": settings.SLACK_CHANNEL,
        "text": f"🚨 장애 발생 알림: {error_type}",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "🚨 Incident Detected (DLQ)"
                }
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Error Type:*\n{error_type}"},
                    {"type": "mrkdwn", "text": f"*Service:*\n{source_service}"},
                    {"type": "mrkdwn", "text": f"*Target DB:*\n{target_db}.{target_coll}"},
                    {"type": "mrkdwn", "text": f"*Score:*\n{score:.4f}"}
                ]
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Original Message Preview:*\n`{message_summary}...`"
                }
            },
            {
                "type": "divider"
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "🛠️ Create Sandbox",
                            "emoji": True
                        },
                        "style": "primary",
                        "value": json.dumps({"action": "create_sandbox", "case_id": event.get("case_id", "temp")}),
                        "action_id": "sandbox_button"
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "🔄 Direct Redrive",
                            "emoji": True
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
            print(f"[Slack] Alert sent for error: {error_type}")

    except Exception as e:
        print(f"[Slack EXCEPTION] {e}")