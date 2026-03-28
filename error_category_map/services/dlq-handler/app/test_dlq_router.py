from kafka import KafkaProducer
import json

producer = KafkaProducer(
    bootstrap_servers='localhost:9092', # 포트포워딩 상황에 맞게 수정
    value_serializer=lambda v: json.dumps(v).encode('utf-8')
)

# 1. 리소스 에러 테스트 (재시도만 해야 함)
producer.send('orders-dlq', {
    "error_type": "TimeoutError",
    "original_payload": {"order_id": 101, "item": "Coffee"}
})

# 2. 로직 에러 테스트 (샌드박스 + 슬랙 떠야 함)
producer.send('orders-dlq', {
    "error_type": "DataTruncation",
    "original_payload": {"order_id": 102, "item": "Very looooooooong text..."}
})

producer.flush()
print("✅ 테스트 메시지 발송 완료!")