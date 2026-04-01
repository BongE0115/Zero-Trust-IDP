from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from kafka import KafkaProducer
import json
import os
import time
import requests
import base64
import zlib  # 🌟 슬랙에서 온 압축 해제용

app = FastAPI()

# --- [Kafka 설정] ---
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "kafka.kafka-poc.svc.cluster.local:9092")
TOPIC = os.getenv("KAFKA_TOPIC", "orders")

# --- [GitHub Actions 설정 (환경 변수)] ---
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_OWNER = os.getenv("GITHUB_OWNER", "BongE0115")
GITHUB_REPO = os.getenv("GITHUB_REPO", "Zero-Trust-IDP")
GITHUB_REF = os.getenv("GITHUB_REF", "test/chatops") # 얘를 나중에 진짜 branch 명에 맞게 바꿔야 함.
ACTIVATE_SANDBOX_WORKFLOW_FILE = os.getenv("ACTIVATE_SANDBOX_WORKFLOW_FILE", "activate-sandbox.yaml")
CREATE_CASE_BRANCH_WORKFLOW_FILE = os.getenv("CREATE_CASE_BRANCH_WORKFLOW_FILE", "create-case-branch.yaml")

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

# --- [🌟 핵심: GitHub Dispatch 공통 함수] ---
def github_dispatch(workflow_file: str, inputs: dict):
    if not GITHUB_TOKEN:
        print(f"❌ [GitOps ERROR] GITHUB_TOKEN이 없어 {workflow_file} 호출 불가")
        return False

    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/workflows/{workflow_file}/dispatches"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {"ref": GITHUB_REF, "inputs": inputs}
    
    resp = requests.post(url, headers=headers, json=payload, timeout=20)
    if resp.status_code in (204, 201):
        print(f"✅ [GITHUB_DISPATCH] workflow={workflow_file} dispatched successfully")
        return True
    else:
        print(f"❌ [GITHUB_DISPATCH FAILED] workflow={workflow_file} status={resp.status_code}, body={resp.text}")
        return False

# --- [🌟 핵심: 두 개의 파이프라인 동시 격발] ---
def trigger_github_actions(username: str, github_payload_data: dict):
    # 1. Activate Sandbox Workflow 호출
    activate_inputs = {
        "spec_json": github_payload_data.get("spec_json", "{}"),
        "failure_artifact_json": github_payload_data.get("failure_artifact_json", "{}"),
        "normal_artifact_json": github_payload_data.get("normal_artifact_json", "{}")
    }
    github_dispatch(ACTIVATE_SANDBOX_WORKFLOW_FILE, activate_inputs)

    # 2. Create Case Branch Workflow 호출 (팀원분 jy 브랜치 로직 반영)
    try:
        spec = json.loads(github_payload_data.get("spec_json", "{}"))
        case_id = spec["metadata"]["case_id"]
        
        branch_inputs = {
            "case_id": case_id,
            "service": spec["metadata"]["source_service"],
            "base_ref": GITHUB_REF,
            "source_image_ref": spec["sandbox"]["consumer_image_ref"],
            "sandbox_manifest_path": spec["metadata"].get("sandbox_manifest_path", ""),
            "note": f"case branch created from ChatOps (approved by {username})",
        }
        github_dispatch(CREATE_CASE_BRANCH_WORKFLOW_FILE, branch_inputs)
    except Exception as e:
        print(f"⚠️ [WARN] Create Case Branch 호출 실패 (spec_json 파싱 에러): {e}")

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
          <button onclick="sendRequest(true)">실패 요청 보내기</button>
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

# --- [🚀 신규: 슬랙 액션 콜백 엔드포인트] ---
@app.post("/slack/interactive")
async def slack_interactive(request: Request):
    form_data = await request.form()
    payload_str = form_data.get("payload")
    
    if not payload_str:
        return JSONResponse(content={"error": "Invalid payload"}, status_code=400)
        
    try:
        slack_payload = json.loads(payload_str)
        actions = slack_payload.get("actions", [])
        
        if actions and actions[0].get("action_id") == "sandbox_button":
            username = slack_payload.get('user', {}).get('username', 'Unknown')
            button_value = actions[0].get("value")
            
            print(f"🚨 [SLACK COMMAND] 샌드박스 기동 명령 수신! 요청자: {username}")
            
            # 🌟 마법의 해독: 슬랙이 돌려준 Base64 데이터를 디코딩 & 압축 해제합니다!
            try:
                decoded_bytes = base64.b64decode(button_value)
                decompressed = zlib.decompress(decoded_bytes)
                github_payload_data = json.loads(decompressed.decode('utf-8'))
            except Exception as decode_err:
                print(f"⚠️ [DECODE ERROR] 압축 해제 실패: {decode_err}")
                github_payload_data = {}

            # GitHub Actions 호출!
            trigger_github_actions(username, github_payload_data)
            
            return {
                "replace_original": True,
                "text": f"✅ *GitOps 파이프라인 가동 시작!*\n요청자 `{username}`님의 승인에 따라 샌드박스 프로비저닝 및 케이스 브랜치 생성을 시작했습니다. 🚀"
            }
            
    except Exception as e:
        print(f"❌ [SLACK ACTION ERROR] {e}")
        return {"text": f"❌ GitOps 호출 중 에러가 발생했습니다: {str(e)}"}
        
    return {"status": "ignored"}