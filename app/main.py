from fastapi import FastAPI
from app.routes import test_routes, redrive_routes, slack_routes

import logging
from pymongo import MongoClient

from app.config.settings import settings

# 🔥 Uvicorn access log 제거 (터미널을 깔끔하게 유지합니다)
logging.getLogger("uvicorn.access").disabled = True

app = FastAPI()

# ==============================
# ✅ 라우터 등록
# ==============================
# API 엔드포인트와 Slack 대화형 버튼 처리를 담당합니다.
app.include_router(test_routes.router)
app.include_router(redrive_routes.router)
app.include_router(slack_routes.router)


# ==============================
# 🧹 DB 초기화 (개발용)
# ==============================
def reset_db_if_needed():
    if settings.RESET_DB_ON_START:
        try:
            client = MongoClient(settings.MONGO_URI)
            db = client[settings.MONGO_DB]
            db[settings.MONGO_COLLECTION].delete_many({})
            print("🧹 MongoDB 초기화 완료 (Backend)")
        except Exception as e:
            print(f"❌ DB 초기화 실패: {e}")


# ==============================
# 🚀 Startup
# ==============================
@app.on_event("startup")
def start_services():
    print("🔥 Backend Service startup called")
    
    # DB 초기화는 API 서버가 시작될 때 수행하도록 유지합니다.
    reset_db_if_needed()
    
    # 💡 [변경사항] 
    # 기존에 여기서 실행되던 AIOps(run_aiops_loop) 쓰레드는 삭제되었습니다.
    # 이제 이 로직은 aiops_runner.py가 담당하여 독립된 파드로 실행됩니다.
    print("✅ Backend API Gateway is ready")


# ==============================
# Root
# ==============================
@app.get("/")
def root():
    return {"message": "Error Recovery System Backend is running"}