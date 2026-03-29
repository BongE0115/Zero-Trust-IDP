# trigger
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from kafka import KafkaProducer
import json
import os
import time

app = FastAPI()

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "kafka.kafka-poc.svc.cluster.local:9092") # 메시지 전송 확인 방법 1 (ssm에서 확인)로 확인하기 위해 local -> kafka로 변경함.
TOPIC = os.getenv("KAFKA_TOPIC", "orders")

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