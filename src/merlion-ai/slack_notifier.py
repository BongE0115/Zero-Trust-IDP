# src/merlion-ai/slack_notifier.py
import requests
import json

# 슬랙 채널에 연동한 Incoming Webhook URL을 여기에 넣으면 돼
SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"

def send_anomaly_alert(app_name, anomalous_port, severity, reason):
    """
    AI가 이상을 감지했을 때 슬랙으로 경고 메시지와 JIT 권한 부여 버튼을 전송합니다.
    """
    
    # Slack Block Kit을 이용한 UI 구성
    payload = {
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "🚨 [Merlion AI] 비정상 네트워크 패턴 감지!"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{app_name}* 파드에서 트래픽 이상이 감지되었습니다.\n\n* 🎯 문제 포트:* `{anomalous_port}`\n* ⚠️ 심각도:* {severity}\n* 📝 원인:* {reason}"
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": f"🛠️ {anomalous_port}번 포트 패킷 캡처 승인 (60분)"
                        },
                        "style": "danger",
                        # ★ 핵심: 버튼에 숨겨놓는 데이터. 승인 시 이 값이 Github Actions나 봇으로 넘어감
                        "value": f'{{"app": "{app_name}", "port": {anomalous_port}}}',
                        "action_id": "grant_jit_tcpdump"
                    }
                ]
            }
        ]
    }

    # 슬랙으로 전송!
    response = requests.post(
        SLACK_WEBHOOK_URL, 
        data=json.dumps(payload), 
        headers={'Content-Type': 'application/json'}
    )
    
    if response.status_code == 200:
        print(f"✅ 슬랙 알림 발송 성공! (대상: {app_name}, 포트: {anomalous_port})")
    else:
        print(f"❌ 슬랙 발송 실패: {response.status_code}, {response.text}")