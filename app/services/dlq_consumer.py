import json
import logging
import time
import threading
from datetime import datetime

from kafka import KafkaConsumer
from sklearn.metrics import precision_score, recall_score, f1_score

from app.aiops.merlion_detector import MerlionAnomalyDetector
from app.services.slack_notifier import send_slack_alert

# 🔥 로그 최소화
logging.getLogger().setLevel(logging.ERROR)

logger = logging.getLogger(__name__)

times = 10


class DLQKafkaConsumer:
    def __init__(self, bootstrap_servers: str, topic: str, group_id: str):
        self.topic = topic
        self.dlq_count = 0

        self.total_count = 0
        self.last_printed = 0

        self.time_series = []
        self.eval_buffer = []
        self.label_threshold = 20

        self.detector = MerlionAnomalyDetector()

        self.consumer = KafkaConsumer(
            self.topic,
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
            auto_offset_reset="earliest",
            enable_auto_commit=True,
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        )

    def start(self):
        print("🔥 DLQ Consumer started")

        def metrics_loop():
            while True:
                time.sleep(times)
                self.update_metrics()

        threading.Thread(target=metrics_loop, daemon=True).start()

        for message in self.consumer:
            try:
                self.dlq_count += 1
                self.total_count += 1

                if self.total_count // 10 > self.last_printed:
                    self.last_printed = self.total_count // 10
                    print(f"📥 메시지 도착! {self.last_printed * 10}", flush=True)

            except Exception as e:
                logger.error(f"[DLQ Consumer] Error: {e}")

    def update_metrics(self):
        timestamp = datetime.utcnow()

        if self.dlq_count == 0:
            return

        print(f"\n📊 DLQ Count (last {times}s): {self.dlq_count}")

        label = 1 if self.dlq_count > self.label_threshold else 0

        self.time_series.append({
            "timestamp": timestamp,
            "count": self.dlq_count,
            "label": label
        })

        self.run_anomaly_detection()

        self.dlq_count = 0

    def run_anomaly_detection(self):
        if len(self.time_series) >= 2 and not self.detector.is_trained:
            print("🧠 Training Merlion model...")
            self.detector.train(self.time_series)

        if not self.detector.is_trained:
            print("[Merlion] Waiting for more data...")
            return

        score = self.detector.detect(self.time_series)

        if score is None:
            return

        print(f"🧠 Anomaly Score: {score}")

        current_count = self.time_series[-1]["count"]
        prev_count = self.time_series[-2]["count"] if len(self.time_series) >= 2 else current_count

        # 🔥 핵심 수정 부분 (이게 중요)
        prediction = 1 if (
            self.detector.is_anomaly(score)
            and current_count > 20
            and (current_count >= prev_count or current_count > 40)
        ) else 0

        label = self.time_series[-1]["label"]

        self.eval_buffer.append((label, prediction))

        if prediction == 1:
            print("🚨 ANOMALY DETECTED!")

            event = {
                "metric_name": "dlq_message_count",
                "metric_value": current_count,
                "threshold": "dynamic (Merlion)",
                "severity": "CRITICAL",
                "message": "DLQ spike detected"
            }

            send_slack_alert(event=event, score=score)

        if len(self.eval_buffer) >= 10:
            y_true = [x[0] for x in self.eval_buffer]
            y_pred = [x[1] for x in self.eval_buffer]

            precision = precision_score(y_true, y_pred, zero_division=0)
            recall = recall_score(y_true, y_pred, zero_division=0)
            f1 = f1_score(y_true, y_pred, zero_division=0)

            print("\n📊 [F1 Evaluation]")
            print(f"Precision: {precision:.4f}")
            print(f"Recall:    {recall:.4f}")
            print(f"F1 Score:  {f1:.4f}\n")

            self.eval_buffer = []