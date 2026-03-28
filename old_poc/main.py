import logging
from fastapi import FastAPI
from pymongo import MongoClient
from app.routes import test_routes, redrive_routes, slack_routes
from app.config.settings import settings

# 로그 설정: 터미널을 깨끗하게 유지하기 위해 uvicorn access 로그만 비활성화
logging.getLogger("uvicorn.access").disabled = True
logger = logging.getLogger(__name__)

app = FastAPI(title="Zero-Trust AIOps Backend Gateway")

# ==============================
# ✅ 라우터 등록
# ==============================
# 1. 테스트용, 2. 복구(Redrive)용, 3. 슬랙 상호작용(버튼 클릭 등) 수신용
app.include_router(test_routes.router)
app.include_router(redrive_routes.router, prefix="/api/v1")
app.include_router(slack_routes.router) # 👈 ngrok을 통해 슬랙 신호를 받는 핵심!


# ==============================
# 🧹 DB 초기화 (개발용)
# ==============================
def reset_db_if_needed():
    if settings.RESET_DB_ON_START:
        try:
            client = MongoClient(settings.MONGO_URI)
            db = client[settings.MONGO_DB]
            # 지정된 컬렉션 초기화
            db[settings.MONGO_COLLECTION].delete_many({})
            print("🧹 MongoDB 초기화 완료 (Backend Gateway)")
        except Exception as e:
            print(f"❌ DB 초기화 실패: {e}")


# ==============================
# 🚀 Startup Event
# ==============================
@app.on_event("startup")
def start_services():
    print("🔥 Backend Gateway Service starting...")
    
    # 서버 시작 시 DB 초기화 수행
    reset_db_if_needed()
    
    # 💡 [구조 알림]
    # Kafka Consumer와 AIOps(Merlion) 루프는 여기서 직접 실행하지 않습니다.
    # 각각 독립된 파드(aiops_runner.py, consumer_runner.py 등)에서 실행되어야
    # 진정한 6개 파드 마이크로서비스 구조가 완성됩니다.
    
    print("✅ Backend API Gateway is ready to receive Slack events!")


@app.get("/")
def root():
    return {
        "message": "Zero-Trust Error Recovery System API is running",
        "mode": "6-Pod Architecture Gateway"
    }