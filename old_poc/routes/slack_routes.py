from fastapi import APIRouter, Request
import json
import threading
import requests

from app.services.redrive_service import RedriveService

router = APIRouter()


def run_redrive_async(response_url: str):
    print("🔥 [Async] Redrive 시작")

    try:
        service = RedriveService()
        result = service.redrive(limit=50)

        print(f"🔥 [Async] Redrive 완료: {result}")

        # 🔥 결과 Slack 전송
        requests.post(
            response_url,
            json={
                "response_type": "in_channel",
                "text": (
                    "✅ *Redrive 완료!*\n\n"
                    f"• 재처리: {result.get('reprocessed', 0)}\n"
                    f"• 성공: {result.get('success', 0)}\n"
                    f"• 실패: {result.get('failed', 0)}"
                )
            }
        )

    except Exception as e:
        print(f"[Redrive ERROR] {e}")

        requests.post(
            response_url,
            json={
                "response_type": "ephemeral",
                "text": f"❌ Redrive 실패: {str(e)}"
            }
        )


@router.post("/slack/actions")
async def slack_actions(request: Request):
    form = await request.form()
    payload_str = form.get("payload")

    if not payload_str:
        return {"status": "invalid payload"}

    payload = json.loads(payload_str)

    actions = payload.get("actions", [])
    if not actions:
        return {"status": "no actions"}

    action_id = actions[0].get("action_id")
    response_url = payload.get("response_url")

    print("🔥 Slack action_id:", action_id)

    if action_id == "redrive_button":
        print("🔥 Redrive 실행!")

        # 🔥 비동기 실행
        threading.Thread(
            target=run_redrive_async,
            args=(response_url,)
        ).start()

        # 🔥 Slack 즉시 ACK (3초 규칙)
        return {
            "response_type": "ephemeral",
            "text": "⏳ Redrive 실행 중..."
        }

    return {"status": "ok"}