import os
import json
import requests
import zlib
import base64

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL")

def compress_payload(payload_dict: dict) -> str:
    """
    거대한 JSON 객체(sandbox_spec + artifacts)를 
    zlib으로 압축하고 Base64 문자열로 변환하여 슬랙 버튼 용량 제한(2000자)을 우회합니다.
    """
    json_str = json.dumps(payload_dict, ensure_ascii=False)
    compressed = zlib.compress(json_str.encode('utf-8'))
    return base64.b64encode(compressed).decode('utf-8')

def send_slack_alert(case_id: str, error_msg: str, raw_payload: dict, source_service: str):
    """
    DLQ 핸들러에서 생성된 포렌식 스펙을 슬랙 카드로 전송합니다.
    [Create Sandbox] 버튼에는 압축된 전체 스펙 데이터가 포함됩니다.
    """
    if not SLACK_BOT_TOKEN or not SLACK_CHANNEL:
        print("[WARN] SLACK_BOT_TOKEN 또는 SLACK_CHANNEL 설정이 누락되었습니다.")
        return

    # 1. 거대 페이로드(spec + artifacts) 압축 및 인코딩
    try:
        compressed_value = compress_payload(raw_payload)
    except Exception as e:
        print(f"[ERROR] 페이로드 압축 실패: {e}")
        return

    # 2. 슬랙 전용 Block Kit UI 구성
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "🚨 [JIT] 포렌식 샌드박스 배포 승인 요청",
                "emoji": True
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*탐지 서비스:* `{source_service}`\n"
                    f"*Case ID:* `{case_id}`\n"
                    f"*발생 에러:* `{error_msg}`\n\n"
                    "⚠️ 서비스에 에러가 탐지되었습니다. 포렌식 샌드박스를 배포하시겠습니까?"
                )
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
                        "text": "배포 승인 (Create Sandbox) 🚀",
                        "emoji": True
                    },
                    "style": "primary",
                    "value": compressed_value,
                    "action_id": "approve_sandbox_creation" 
                }
            ]
        }
    ]

    # 3. Slack API 호출
    url = "https://slack.com/api/chat.postMessage"
    headers = {
        "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
        "Content-Type": "application/json; charset=utf-8"
    }
    data = {
        "channel": SLACK_CHANNEL,
        "blocks": blocks,
        "text": f"🚨 [승인 요청] {case_id} 포렌식 샌드박스"
    }

    try:
        resp = requests.post(url, headers=headers, json=data, timeout=10)
        resp_json = resp.json()
        if not resp_json.get("ok"):
            print(f"[ERROR] Slack 메시지 전송 실패: {resp_json.get('error')}")
        else:
            print(f"[SLACK] HITL 승인 요청 전송 완료 (Case: {case_id})")
    except Exception as e:
        print(f"[ERROR] Slack 통신 중 예외 발생: {e}")