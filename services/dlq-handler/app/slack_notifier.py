import requests
import json
import os

# --- [Slack 설정 (환경 변수에서 가져오기)] ---
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "xoxb-your-token-here")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL", "#your-channel")

# 💡 [수정됨] 팀원분의 score와 우리의 category, action을 모두 받을 수 있도록 파라미터를 확장했습니다!
def send_slack_alert(event: dict, score: float = 0.0, category: str = "UNKNOWN", action: str = "NONE"):
    """
    DLQ 에러(로직/데이터 결함) 발생 시 Slack으로 버튼이 포함된 카드를 발송합니다.
    """
    # 1. 데이터 추출 
    error_type = event.get("error_type", "Unknown Error")
    error_message = event.get("error_message", "No error message")
    source_service = event.get("source_service", "unknown-service")
    
    # 이벤트 딕셔너리 안에 category가 이미 들어있다면 그걸 우선적으로 씁니다.
    event_category = event.get("category", category)
    
    # 원본 데이터 요약 (너무 길면 슬랙이 안 좋아하므로 50자로 자릅니다)
    payload_data = event.get("original_payload", {})
    message_summary = str(payload_data)[:50]

    url = "https://slack.com/api/chat.postMessage"
    headers = {
        "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
        "Content-Type": "application/json"
    }

    # 2. Slack Block Kit 구성 (카테고리와 추천 행동 필드 추가!)
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
                    # 💡 지능형 에러 분석 결과 추가
                    {"type": "mrkdwn", "text": f"*Category:*\n`{event_category}`"},
                    {"type": "mrkdwn", "text": f"*Recommended Action:*\n`{action}`"},
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