# src/merlion-ai/mock_trigger.py
from slack_notifier import send_anomaly_alert
import time

print("🤖 Merlion AI (Mock) 가짜 모니터링 시작...")
time.sleep(2) # 2초 뒤 에러 발생 상황 연출

print("⚡ 앗! 8080 포트에서 502 에러 스파이크 감지!")

# slack_notifier.py의 함수를 호출해서 슬랙으로 쏜다!
send_anomaly_alert(
    app_name="api-server-xyz",
    anomalous_port=8080,           # 네가 원했던 '해당 포트 번호' 데이터!
    severity="HIGH",
    reason="502 Bad Gateway 에러율 평소 대비 400% 증가"
)

print("✅ 테스트 알림 트리거 완료. 슬랙을 확인해보세요.")