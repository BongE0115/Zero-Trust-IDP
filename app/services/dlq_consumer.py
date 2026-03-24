import json
import logging
import time
import threading
from datetime import datetime

from kafka import KafkaConsumer
from sklearn.metrics import precision_score, recall_score, f1_score

from app.aiops.merlion_detector import MerlionAnomalyDetector
from app.services.slack_notifier import send_slack_alert

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

        # 🔥 persistence
        self.anomaly_streak = 0
        self.persistence = 3

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
        # 🔹 모델 학습
        if len(self.time_series) >= 5 and not self.detector.is_trained:
            print("🧠 Training Merlion model...")
            self.detector.train(self.time_series)

        score = None
        if self.detector.is_trained:
            score = self.detector.detect(self.time_series)
            print(f"🧠 Anomaly Score: {score:.4f}")

        current_count = self.time_series[-1]["count"]

        # 🔥 baseline (최근 5개 중 정상값 평균)
        window = self.time_series[-5:]
        normal_values = [x["count"] for x in window if x["count"] < 30]

        if len(normal_values) == 0:
            baseline = current_count
        else:
            baseline = sum(normal_values) / len(normal_values)

        ratio = current_count / baseline if baseline > 0 else 0

        print(f"📈 Baseline: {baseline:.2f}, Ratio: {ratio:.2f}")

        # 🔥 핵심 로직 (완성형)
        is_spike = ratio > 2.5
        is_model_anomaly = score >= 0.5 if score is not None else False

        if is_spike:
            if self.anomaly_streak == 0:
                # 🔥 첫 진입 → Merlion 필요
                if is_model_anomaly:
                    self.anomaly_streak = 1
            else:
                # 🔥 이후 → baseline만으로 유지
                self.anomaly_streak += 1
        else:
            # 🔥 정상 복귀
            self.anomaly_streak = 0

        print(f"🔥 Anomaly Streak: {self.anomaly_streak}")

        prediction = 1 if self.anomaly_streak >= self.persistence else 0
        label = self.time_series[-1]["label"]

        self.eval_buffer.append((label, prediction))

        if prediction == 1:
            print("🚨 ANOMALY DETECTED!")

            event = {
                "metric_name": "dlq_message_count",
                "metric_value": current_count,
                "threshold": "merlion(trigger) + baseline + persistence",
                "severity": "CRITICAL",
                "message": f"DLQ spike detected (ratio={ratio:.2f})"
            }

            send_slack_alert(event=event, score=score)

            # 🔥 중복 알림 방지
            self.anomaly_streak = 0

        # 🔹 평가
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