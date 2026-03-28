import time
import logging
from app.services.aiops_service import run_aiops_loop
from app.config.settings import settings

# 로그 설정
logging.getLogger().setLevel(logging.INFO)

def start_aiops():
    print("🧠 AIOps Analysis Pod Starting...")
    print(f"🔍 Monitoring MongoDB: {settings.MONGO_URI}")
    
    # 분석 루프 실행 (30초 간격, 최근 10분 데이터 분석)
    # 기존 main.py에 있던 설정을 그대로 가져옵니다.
    try:
        run_aiops_loop(interval_seconds=30, minutes=10)
    except Exception as e:
        print(f"❌ AIOps Loop Error: {e}")

if __name__ == "__main__":
    start_aiops()