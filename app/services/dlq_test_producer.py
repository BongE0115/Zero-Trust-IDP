from kafka import KafkaProducer
import json
import time

producer = KafkaProducer(
    bootstrap_servers="localhost:9092",
    value_serializer=lambda v: json.dumps(v).encode("utf-8")
)

topic = "anomaly-dlq"

# 🔥 여러 개 보내기 (중요)
for i in range(72):
    data = {
        "metric_name": "cpu_usage",
        "metric_value": 100 + i
    }

    producer.send(topic, data)
    print(f"Sent: {data}")
    time.sleep(0.1)

producer.flush()
print("✅ done")