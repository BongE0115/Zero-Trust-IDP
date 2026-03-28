from kafka import KafkaProducer
import json
from app.config.settings import settings

producer = KafkaProducer(
    bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
    value_serializer=lambda v: json.dumps(v).encode("utf-8")
)

def run_poc():
    # 1. 정상 데이터 (메시지가 짧음 -> 성공)
    print("📤 Sending normal message...")
    producer.send(settings.KAFKA_TOPIC_MAIN, {
        "severity": "INFO",
        "message": "Hello" 
    })

    # 2. 장애 유발 데이터 (20자 초과 -> Consumer에서 ValueError 발생 -> DLQ행)
    print("🚨 Sending TOO LONG message (Scenario A)...")
    producer.send(settings.KAFKA_TOPIC_MAIN, {
        "severity": "CRITICAL",
        "message": "This message is definitely longer than twenty characters!" 
    })
    
    producer.flush()

if __name__ == "__main__":
    run_poc()
    print("✅ PoC Data Sent!")