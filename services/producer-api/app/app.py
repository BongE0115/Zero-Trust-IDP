# trigger
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from kafka import KafkaProducer
import json
import os
import time
import requests  # GitHub API 호출용

app = FastAPI()

# --- [Kafka 설정] ---
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "kafka.kafka-poc.svc.cluster.local:9092")
TOPIC = os.getenv("KAFKA_TOPIC", "orders")

# --- [GitHub Actions 설정 (GitOps 전환용)] ---
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "") # 슬랙 봇 토큰처럼 K8s Secret으로 주입받아야 합니다.
GITHUB_REPO = os.getenv("GITHUB_REPO", "your-org/Zero-Trust-IDP") # ⭐️ 본인의 레포지토리 이름으로 변경하세요!

producer = None

def get_producer():
    global producer
    if producer is None:
        for _ in range(30):
            try:
                producer = KafkaProducer(
                    bootstrap_servers=KAFKA_BOOTSTRAP,
                    value_serializer=lambda v: json.dumps(v).encode("utf-8")
                )
                break
            except Exception as e:
                print(f"[WARN] Kafka producer init failed: {e}")
                time.sleep(2)
    if producer is None:
        raise RuntimeError("Kafka producer init failed")
    return producer


def trigger_github_action(username: str):
    """
    슬랙 버튼 클릭 시, K8s API를 직접 찌르는 대신 
    GitHub Actions (Repository Dispatch)를 호출하여 GitOps 워크플로우를 가동합니다.
    """
    if not GITHUB_TOKEN:
        print("❌ [GitOps ERROR] GITHUB_TOKEN이 설정되지 않았습니다.")
        raise ValueError("GitHub Token is missing")

    url = f"https://api.github.com/repos/{GITHUB_REPO}/dispatches"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"token {GITHUB_TOKEN}"
    }
    # GitHub Actions Workflow로 전달할 명세서 (Payload)
    data = {
        "event_type": "deploy-sandbox", # 이 이벤트 이름이 GitHub Actions YAML 파일과 일치해야 합니다.
        "client_payload": {
            "triggered_by": username,
            "action": "create_sandbox",
            "message": "Slack ChatOps Triggered"
        }
    }
    
    response = requests.post(url, headers=headers, json=data)
    if response.status_code == 204:
        print(f"✅ [GitOps SUCCESS] GitHub Actions (deploy-sandbox) 워크플로우 호출 성공!")
    else:
        print(f"❌ [GitOps FAILED] 상태 코드: {response.status_code}, 응답: {response.text}")
        raise RuntimeError(f"GitHub API Error: {response.text}")


class SubmitRequest(BaseModel):
    order_id: str
    should_fail: bool = False
    payload: dict = {}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/", response_class=HTMLResponse)
def index():
    return """
    <!DOCTYPE html>
    <html lang="ko">
    <head>
      <meta charset="UTF-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1.0" />
      <title>Kafka POC Producer UI</title>
      <style>
        body { font-family: Arial, sans-serif; max-width: 760px; margin: 40px auto; padding: 20px; line-height: 1.6; }
        h1 { margin-bottom: 8px; }
        .card { border: 1px solid #ddd; border-radius: 10px; padding: 20px; margin-top: 20px; }
        label { display: block; margin-top: 12px; font-weight: bold; }
        input, textarea, button { width: 100%; padding: 10px; margin-top: 6px; box-sizing: border-box; font-size: 14px; }
        textarea { min-height: 120px; font-family: monospace; }
        .row { display: flex; gap: 12px; margin-top: 12px; }
        .row button { flex: 1; }
        .success { color: green; white-space: pre-wrap; margin-top: 16px; }
        .error { color: red; white-space: pre-wrap; margin-top: 16px; }
        .hint { color: #555; font-size: 13px; }
      </style>
    </head>
    <body>
      <h1>Kafka 장애 대응 POC</h1>
      <p class="hint">정상 요청 또는 실패 요청을 보내서 <code>producer → kafka → consumer → dlq</code> 흐름을 확인할 수 있습니다.</p>
      <div class="card">
        <label for="order_id">Order ID</label>
        <input id="order_id" value="order-1001" />
        <label for="payload">Payload (JSON)</label>
        <textarea id="payload">{"item":"book","qty":1}</textarea>
        <div class="row">
          <button onclick="sendRequest(false)">정상 요청 보내기</button>
          <button onclick="sendRequest(true)">실패(DataTruncation) 요청 흉내내기</button>
        </div>
        <div id="result"></div>
      </div>
      <script>
        async function sendRequest(shouldFail) {
          const result = document.getElementById("result");
          result.className = ""; result.textContent = "전송 중...";
          let payloadObj = {};
          try { payloadObj = JSON.parse(document.getElementById("payload").value); } 
          catch (e) { result.className = "error"; result.textContent = "Payload JSON 형식이 잘못되었습니다."; return; }
          
          if (shouldFail) { payloadObj["should_fail"] = true; }

          const body = { order_id: document.getElementById("order_id").value, should_fail: shouldFail, payload: payloadObj };
          try {
            const res = await fetch("/submit", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
            const data = await res.json();
            result.className = "success"; result.textContent = JSON.stringify(data, null, 2);
          } catch (e) {
            result.className = "error"; result.textContent = "요청 실패: " + e;
          }
        }
      </script>
    </body>
    </html>
    """

@app.post("/submit")
def submit(req: SubmitRequest):
    msg = {
        "order_id": req.order_id,
        "should_fail": req.should_fail,
        "payload": req.payload
    }
    p = get_producer()
    p.send(TOPIC, msg)
    p.flush()
    return {
        "status": "sent",
        "topic": TOPIC,
        "message": msg,
        "next": "worker-consumer will process this message"
    }

# --- [새로 추가된 핵심 기능: 슬랙 액션 콜백 엔드포인트] ---
@app.post("/slack/interactive")
async def slack_interactive(request: Request):
    """
    슬랙에서 버튼을 클릭했을 때 날아오는 POST 요청을 처리합니다.
    """
    form_data = await request.form()
    payload_str = form_data.get("payload")
    
    if not payload_str:
        return JSONResponse(content={"error": "Payload not found"}, status_code=400)
        
    try:
        slack_payload = json.loads(payload_str)
        actions = slack_payload.get("actions", [])
        
        if actions and actions[0].get("value") == "sandbox_open":
            username = slack_payload.get('user', {}).get('username', 'Unknown')
            print(f"🚨 [SLACK COMMAND] 샌드박스 기동 명령 수신! 요청자: {username}")
            
            # [수정됨] K8s 직접 제어(반칙)를 버리고, GitHub Actions(정석) 호출
            trigger_github_action(username)
            
            return {
                "replace_original": True,
                "text": f"✅ *GitOps 파이프라인 가동 시작!*\n요청자 `{username}`님의 명령에 따라 GitHub Actions가 샌드박스 프로비저닝을 진행 중입니다."
            }
            
    except Exception as e:
        print(f"❌ [SLACK ACTION ERROR] {e}")
        return {"text": f"❌ GitOps 호출 중 에러가 발생했습니다: {str(e)}"}
        
    return {"status": "ignored"}