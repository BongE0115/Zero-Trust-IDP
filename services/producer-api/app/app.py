from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from kafka import KafkaProducer
import json
import os
import time
import base64
import zlib
import requests

app = FastAPI()

# ==========================================
# 기존 환경 변수
# ==========================================
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "kafka.kafka-poc.svc.cluster.local:9092")
TOPIC = os.getenv("KAFKA_TOPIC", "orders")

# ==========================================
# 🚨 신규 장착: GitHub Actions 격발용 환경변수 
# ==========================================
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_OWNER = os.getenv("GITHUB_OWNER", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
GITHUB_REF = os.getenv("GITHUB_REF", "jy")
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
        body {
          font-family: Arial, sans-serif;
          max-width: 760px;
          margin: 40px auto;
          padding: 20px;
          line-height: 1.6;
        }
        h1 { margin-bottom: 8px; }
        .card {
          border: 1px solid #ddd;
          border-radius: 10px;
          padding: 20px;
          margin-top: 20px;
        }
        label {
          display: block;
          margin-top: 12px;
          font-weight: bold;
        }
        input, textarea, button {
          width: 100%;
          padding: 10px;
          margin-top: 6px;
          box-sizing: border-box;
          font-size: 14px;
        }
        textarea {
          min-height: 120px;
          font-family: monospace;
        }
        .row {
          display: flex;
          gap: 12px;
          margin-top: 12px;
        }
        .row button {
          flex: 1;
        }
        .success {
          color: green;
          white-space: pre-wrap;
          margin-top: 16px;
        }
        .error {
          color: red;
          white-space: pre-wrap;
          margin-top: 16px;
        }
        .hint {
          color: #555;
          font-size: 13px;
        }
      </style>
    </head>
    <body>
      <h1>Kafka 장애 대응 POC</h1>
      <p class="hint">
        정상 요청 또는 실패 요청을 보내서
        <code>producer → kafka → consumer → dlq</code> 흐름을 확인할 수 있습니다.
      </p>

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
          result.className = "";
          result.textContent = "전송 중...";

          let payloadObj = {};
          try {
            payloadObj = JSON.parse(document.getElementById("payload").value);
          } catch (e) {
            result.className = "error";
            result.textContent = "Payload JSON 형식이 잘못되었습니다.";
            return;
          }

          const body = {
            order_id: document.getElementById("order_id").value,
            should_fail: shouldFail,
            payload: payloadObj
          };

          try {
            const res = await fetch("/submit", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(body)
            });

            const data = await res.json();
            result.className = "success";
            result.textContent = JSON.stringify(data, null, 2);
          } catch (e) {
            result.className = "error";
            result.textContent = "요청 실패: " + e;
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


# ==========================================
# 🚨 신규 장착: GitHub Actions 격발 함수
# ==========================================
def github_dispatch(workflow_file: str, inputs: dict):
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/workflows/{workflow_file}/dispatches"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {"ref": GITHUB_REF, "inputs": inputs}
    resp = requests.post(url, headers=headers, json=payload, timeout=20)

    if resp.status_code not in (204, 201):
        print(f"[ERROR] GitHub dispatch failed: {resp.status_code} - {resp.text}")
    else:
        print(f"[GITHUB_DISPATCH] workflow={workflow_file} successfully dispatched!")


# ==========================================
# 🚨 신규 장착: Slack Interactive 뒷문 (Ngrok 수신부)
# ==========================================
@app.post("/slack/interactive")
async def slack_interactive(request: Request):
    form_data = await request.form()
    payload_data = form_data.get("payload")
    
    # 데이터가 없거나 문자열이 아닌 경우 에러 처리
    if not payload_data or not isinstance(payload_data, str):
        return {"status": "error", "message": "Invalid or missing payload"}

    slack_payload = json.loads(payload_data)
    
    actions = slack_payload.get("actions", [])
    if not actions:
        return {"status": "ignored"}

    action = actions[0]
    action_id = action.get("action_id")
    compressed_value = action.get("value")

    print(f"[SLACK_RECV] Action ID: {action_id} clicked by user.")

    # "Create Sandbox" 버튼이 눌렸을 때만 반응
    if action_id == "approve_sandbox_creation" and compressed_value:
        try:
            # 1. Base64 디코딩 및 zlib 압축 해제
            decompressed_bytes = zlib.decompress(base64.b64decode(compressed_value))
            combined_payload = json.loads(decompressed_bytes.decode('utf-8'))
            
            sandbox_spec = combined_payload.get("spec", {})
            failure_artifact = combined_payload.get("failure_artifact", {})
            normal_artifact = combined_payload.get("normal_artifact", {})
            
            case_id = sandbox_spec.get("metadata", {}).get("case_id", "unknown")
            print(f"[SLACK_RECV] Successfully decompressed payload for Case ID: {case_id}")

            # 2. GitHub Actions 격발 (1연사: 샌드박스 배포)
            print(f"[ACTION] Triggering {ACTIVATE_SANDBOX_WORKFLOW_FILE}...")
            github_dispatch(
                ACTIVATE_SANDBOX_WORKFLOW_FILE,
                {
                    "spec_json": json.dumps(sandbox_spec, ensure_ascii=False),
                    "failure_artifact_json": json.dumps(failure_artifact, ensure_ascii=False),
                    "normal_artifact_json": json.dumps(normal_artifact, ensure_ascii=False),
                }
            )

            # 3. GitHub Actions 격발 (2연사: 케이스 브랜치 생성)
            print(f"[ACTION] Triggering {CREATE_CASE_BRANCH_WORKFLOW_FILE}...")
            github_dispatch(
                CREATE_CASE_BRANCH_WORKFLOW_FILE,
                {
                    "case_id": case_id,
                    "service": sandbox_spec.get("metadata", {}).get("source_service", "unknown"),
                    "base_ref": GITHUB_REF,
                    "source_image_ref": sandbox_spec.get("sandbox", {}).get("consumer_image_ref", ""),
                    "sandbox_manifest_path": sandbox_spec.get("metadata", {}).get("sandbox_manifest_path", ""),
                    "note": "Case branch created via Slack HITL approval",
                }
            )

        except Exception as e:
            print(f"[ERROR] Failed to process sandbox approval: {e}")
            return {"status": "error", "message": str(e)}

    return {"status": "ok"}