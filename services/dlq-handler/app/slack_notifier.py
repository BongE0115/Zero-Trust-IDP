import requests
import json
import os

# --- [Slack 설정 (환경 변수에서 가져오기)] ---
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "xoxb-your-token-here")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL", "#your-channel")

def send_slack_alert(event: dict, score: float = 0.0, category: str = "UNKNOWN", action: str = "NONE", payload_for_github: str = "sandbox_open"):
    """
    DLQ 에러 발생 시 Slack으로 버튼이 포함된 카드를 발송합니다.
    payload_for_github 에는 zlib+base64 로 압축된 샌드박스 재료(Spec 등)가 들어옵니다.
    """
    error_type = event.get("error_type", "Unknown Error")
    error_message = event.get("error_message", "No error message")
    source_service = event.get("source_service", "unknown-service")
    event_category = event.get("category", category)
    
    payload_data = event.get("original_payload", {})
    message_summary = str(payload_data)[:50]

    url = "https://slack.com/api/chat.postMessage"
    headers = {
        "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "channel": SLACK_CHANNEL,
        "text": f"🚨 장애 발생 알림: {error_type}",
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "🚨 Incident Detected (DLQ)"}
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Error Type:*\n{error_type}"},
                    {"type": "mrkdwn", "text": f"*Service:*\n{source_service}"},
                    {"type": "mrkdwn", "text": f"*Category:*\n`{event_category}`"},
                    {"type": "mrkdwn", "text": f"*Recommended Action:*\n`{action}`"},
                    {"type": "mrkdwn", "text": f"*Error Message:*\n{error_message}"},
                    {"type": "mrkdwn", "text": f"*Action Score:*\n{score:.2f} (Logic Error)"}
                ]
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Original Message Preview:*\n`{message_summary}...`"}
            },
            {"type": "divider"},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "🛠️ Create Sandbox", "emoji": True},
                        "style": "primary",
                        "value": payload_for_github, # 🌟 깃허브로 쏠 거대한 압축 파일을 value에 탑재합니다!
                        "action_id": "sandbox_button"
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "🔄 Direct Redrive", "emoji": True},
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
            print(f"❌ [Slack ERROR] 슬랙 전송 실패: {result.get('error')}")
        else:
            print(f"💬 [Slack SUCCESS] {error_type} 에러에 대한 알림이 전송되었습니다.")
    except Exception as e:
        print(f"❌ [Slack EXCEPTION] 슬랙 통신 중 에러 발생: {e}")