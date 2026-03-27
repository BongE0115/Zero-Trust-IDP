from kafka import KafkaProducer
import json
import time
from datetime import datetime
<<<<<<< HEAD
from app.config.settings import settings

bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS
=======
>>>>>>> c56df95f91839c06e4d9c285fda960a4e249b796

producer = KafkaProducer(
    bootstrap_servers="localhost:9092",
    value_serializer=lambda v: json.dumps(v).encode("utf-8")
)

topic = "anomaly-dlq"

# 1️⃣ 정상
for i in range(10):
<<<<<<< HEAD
    data = {
        "service": "payment",
        "error_type": "normal",
        "payload": {
            "metric_name": "cpu_usage",
            "metric_value": 25 + i
        },
        "created_at": datetime.utcnow().isoformat()
    }
    producer.send(topic, data)
    time.sleep(0.2)

# 2️⃣ 약한 이상
for i in range(5):
    data = {
        "service": "payment",
        "error_type": "warning",
        "payload": {
            "metric_name": "cpu_usage",
            "metric_value": 300 + i
=======
    data = {
        "service": "payment",
        "error_type": "normal",
        "payload": {
            "metric_name": "cpu_usage",
            "metric_value": 25 + i
>>>>>>> c56df95f91839c06e4d9c285fda960a4e249b796
        },
        "created_at": datetime.utcnow().isoformat()
    }
    producer.send(topic, data)
    time.sleep(0.2)

<<<<<<< HEAD
=======
# 2️⃣ 약한 이상
for i in range(5):
    data = {
        "service": "payment",
        "error_type": "warning",
        "payload": {
            "metric_name": "cpu_usage",
            "metric_value": 300 + i
        },
        "created_at": datetime.utcnow().isoformat()
    }
    producer.send(topic, data)
    time.sleep(0.2)

>>>>>>> c56df95f91839c06e4d9c285fda960a4e249b796
# 3️⃣ 강한 이상
for i in range(5):
    data = {
        "service": "payment",
        "error_type": "critical",
        "payload": {
            "metric_name": "cpu_usage",
            "metric_value": 120 + i
        },
        "created_at": datetime.utcnow().isoformat()
    }
    producer.send(topic, data)
    time.sleep(0.2)

producer.flush()
print("✅ done")