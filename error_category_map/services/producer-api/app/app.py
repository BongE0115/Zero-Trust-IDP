# trigger
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from kafka import KafkaProducer
from kubernetes import client, config
import json
import os
import time

app = FastAPI()

# --- [Kafka 설정] ---
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "kafka.kafka-poc.svc.cluster.kafka:9092")
TOPIC = os.getenv("KAFKA_TOPIC", "orders")

# --- [Kubernetes Sandbox 설정] ---
SANDBOX_NAMESPACE = os.getenv("SANDBOX_NAMESPACE", "forensic-sandbox")
SANDBOX_DEPLOYMENT = os.getenv("SANDBOX_DEPLOYMENT", "forensic-sandbox-app")
MONGO_DEPLOYMENT = os.getenv("MONGO_DEPLOYMENT", "mongodb-temp")

producer = None
apps_api = None


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


def get_apps_api():
    """쿠버네티스 API 클라이언트 초기화"""
    global apps_api
    if apps_api is None:
        try:
            # 클러스터 내부에서 실행될 때
            config.load_incluster_config()
            apps_api = client.AppsV1Api()
        except Exception:
            try:
                # 로컬 환경(터미널)에서 실행될 때
                config.load_kube_config()
                apps_api = client.AppsV1Api()
            except Exception as e:
                print(f"[WARN] Kubernetes API init failed: {e}")
    return apps_api


def scale_sandbox_resources(replicas: int):
    """샌드박스 관련 디플로이먼트 스케일링"""
    api = get_apps_api()
    if not api:
        raise RuntimeError("K8s API is not initialized.")
    
    body = {"spec": {"replicas": replicas}}
    
    # MongoDB 임시 저장소 스케일링
    api.patch_namespaced_deployment_scale(
        name=MONGO_DEPLOYMENT,
        namespace=SANDBOX_NAMESPACE,
        body=body
    )
    print(f"🚀 [SCALE] {SANDBOX_NAMESPACE}/{MONGO_DEPLOYMENT} -> replicas={replicas}")
    
    # 샌드박스 앱 스케일링
    api.patch_namespaced_deployment_scale(
        name=SANDBOX_DEPLOYMENT,
        namespace=SANDBOX_NAMESPACE,
        body=body
    )
    print(f"🚀 [SCALE] {SANDBOX_NAMESPACE}/{SANDBOX_DEPLOYMENT} -> replicas={replicas}")


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
    # 슬랙은 데이터를 Form-Data 형태로 보냅니다 ('payload' 키 안에 JSON 문자열 탑재)
    form_data = await request.form()
    payload_str = form_data.get("payload")
    
    if not payload_str:
        return JSONResponse(content={"error": "Payload not found"}, status_code=400)
        
    try:
        slack_payload = json.loads(payload_str)
        actions = slack_payload.get("actions", [])
        
        # 'sandbox_open'이라는 value를 가진 버튼이 클릭되었는지 확인
        if actions and actions[0].get("value") == "sandbox_open":
            print(f"🚨 [SLACK COMMAND] 샌드박스 기동 명령 수신! 사용자: {slack_payload.get('user', {}).get('username')}")
            
            # 쿠버네티스 샌드박스 리소스 스케일 업 (0 -> 1)
            scale_sandbox_resources(replicas=1)
            
            # 슬랙 버튼을 누른 메시지를 업데이트하여 응답
            return {
                "replace_original": True,
                "text": "✅ *포렌식 샌드박스(Forensic Sandbox)가 성공적으로 기동되었습니다.*\n임시 MongoDB와 분석 앱이 준비되었습니다. 로그를 확인하세요!"
            }
            
    except Exception as e:
        print(f"❌ [SLACK ACTION ERROR] {e}")
        return {"text": f"❌ 샌드박스 기동 중 에러가 발생했습니다: {str(e)}"}
        
    return {"status": "ignored"}