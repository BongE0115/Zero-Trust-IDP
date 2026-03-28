import json
import time
from datetime import datetime
from kafka import KafkaProducer
from app.config.settings import settings

# 이제 settings에서 서버 주소를 가져옵니다.
producer = KafkaProducer(
    bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
    value_serializer=lambda v: json.dumps(v).encode("utf-8")
)

# 우리가 정한 DLQ 토픽 명칭 사용
topic = settings.KAFKA_TOPIC_DLQ

def send_burst(error_type, count, base_value):
    print(f"🔥 Sending {count} {error_type} events to {topic}...")
    for i in range(count):
        data = {
            "source_service": "payment-service",
            "error_type": error_type,
            "timestamp": datetime.utcnow().isoformat(),
            "original_payload": {
                "metric_name": "cpu_usage",
                "metric_value": base_value + i
            },
            "dependency_context": {"type": "mongodb", "db_name": "sandbox_db"}
        }
        producer.send(topic, data)
        time.sleep(0.1)

if __name__ == "__main__":
    # AIOps가 감지할 수 있도록 에러 데이터를 폭발적으로 주입
    send_burst("normal_error", 10, 25)   # 정상 범위 에러
    send_burst("critical_error", 20, 500) # 갑작스러운 급증 (Anomaly!)
    producer.flush()
    print("✅ Done")