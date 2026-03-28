import requests
import json
import os

# --- [Slack 설정 (환경 변수에서 가져오기)] ---
# ngrok을 켤 때나 시스템 환경 변수에 이 두 값을 꼭 넣어주세요!
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "xoxb-your-token-here")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL", "#your-channel")

def send_slack_alert(event: dict, score: float = 0.0):
    """
    DLQ 에러(로직/데이터 결함) 발생 시 Slack으로 버튼이 포함된 카드를 발송합니다.
    """
    # 1. 데이터 추출 (새로운 consumer.py의 메타데이터 구조 반영)
    error_type = event.get("error_type", "Unknown Error")
    error_message = event.get("error_message", "No error message")
    source_service = event.get("source_service", "unknown-service")
    
    # 원본 데이터 요약 (너무 길면 슬랙이 안 좋아하므로 50자로 자릅니다)
    payload_data = event.get("original_payload", {})
    message_summary = str(payload_data)[:50]

    url = "https://slack.com/api/chat.postMessage"
    headers = {
        "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
        "Content-Type": "application/json"
    }

    # 2. Slack Block Kit 구성
    payload = {
        "channel": SLACK_CHANNEL,
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
                    {"type": "mrkdwn", "text": f"*Error Message:*\n{error_message}"},
                    {"type": "mrkdwn", "text": f"*Action Score:*\n{score:.2f} (Logic Error)"}
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
                        # 매우 중요: app.py의 API가 이 값을 보고 샌드박스를 켭니다!
                        "value": "sandbox_open", 
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

    # 3. 슬랙 API 호출
    try:
        res = requests.post(url, headers=headers, json=payload)
        result = res.json()

        if not result.get("ok"):
            print(f"❌ [Slack ERROR] 슬랙 전송 실패: {result.get('error')}")
        else:
            print(f"💬 [Slack SUCCESS] {error_type} 에러에 대한 알림이 전송되었습니다.")

    except Exception as e:
        print(f"❌ [Slack EXCEPTION] 슬랙 통신 중 에러 발생: {e}")