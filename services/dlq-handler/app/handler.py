from kafka import KafkaConsumer, KafkaProducer
from kubernetes import client, config
import json
import os
import time


def getenv(name: str, default: str = "") -> str:
    return os.getenv(name, default)


KAFKA_BOOTSTRAP = getenv("KAFKA_BOOTSTRAP", "kafka.kafka-poc.svc.cluster.local:9092")
DLQ_TOPIC = getenv("DLQ_TOPIC", "orders-dlq")
REPLAY_TOPIC = getenv("REPLAY_TOPIC", "orders-replay")
GROUP_ID = getenv("GROUP_ID", "orders-dlq-handler")

SANDBOX_NAMESPACE = getenv("SANDBOX_NAMESPACE", "forensic-sandbox")
SANDBOX_DEPLOYMENT = getenv("SANDBOX_DEPLOYMENT", "forensic-sandbox-app")
MONGO_DEPLOYMENT = getenv("MONGO_DEPLOYMENT", "mongodb-temp")

AUTO_SCALE_SANDBOX = getenv("AUTO_SCALE_SANDBOX", "true").lower() == "true"
AUTO_REPLAY = getenv("AUTO_REPLAY", "true").lower() == "true"


def get_producer():
    for _ in range(60):
        try:
            return KafkaProducer(
                bootstrap_servers=KAFKA_BOOTSTRAP,
                value_serializer=lambda v: json.dumps(v).encode("utf-8")
            )
        except Exception as e:
            print(f"[WARN] Kafka producer init failed: {e}")
            time.sleep(2)
    raise RuntimeError("Kafka producer init failed")


def get_consumer():
    for _ in range(60):
        try:
            return KafkaConsumer(
                DLQ_TOPIC,
                bootstrap_servers=KAFKA_BOOTSTRAP,
                group_id=GROUP_ID,
                auto_offset_reset="earliest",
                enable_auto_commit=True,
                value_deserializer=lambda m: json.loads(m.decode("utf-8"))
            )
        except Exception as e:
            print(f"[WARN] Kafka consumer init failed: {e}")
            time.sleep(2)
    raise RuntimeError("Kafka consumer init failed")


def get_apps_api():
    for _ in range(30):
        try:
            config.load_incluster_config()
            return client.AppsV1Api()
        except Exception as e:
            print(f"[WARN] Kubernetes API init failed: {e}")
            time.sleep(2)
    raise RuntimeError("Kubernetes API init failed")


def scale_deployment(apps_api: client.AppsV1Api, namespace: str, name: str, replicas: int):
    body = {"spec": {"replicas": replicas}}
    apps_api.patch_namespaced_deployment_scale(
        name=name,
        namespace=namespace,
        body=body
    )
    print(f"[SCALE] {namespace}/{name} -> replicas={replicas}")


producer = get_producer()
consumer = get_consumer()
apps_api = get_apps_api()

print(
    f"[INFO] DLQ handler started. dlq={DLQ_TOPIC}, replay={REPLAY_TOPIC}, "
    f"sandbox={SANDBOX_NAMESPACE}/{SANDBOX_DEPLOYMENT}, mongo={MONGO_DEPLOYMENT}"
)

for message in consumer:
    failure_event = message.value
    print(f"[DLQ DETECTED] {failure_event}")

    original_payload = failure_event.get("original_payload", {})

    if AUTO_SCALE_SANDBOX:
        try:
            scale_deployment(apps_api, SANDBOX_NAMESPACE, MONGO_DEPLOYMENT, 1)
            scale_deployment(apps_api, SANDBOX_NAMESPACE, SANDBOX_DEPLOYMENT, 1)
        except Exception as e:
            print(f"[ERROR] Failed to scale sandbox resources: {e}")

    if AUTO_REPLAY:
        try:
            producer.send(REPLAY_TOPIC, original_payload)
            producer.flush()
            print(f"[REPLAY] sent to {REPLAY_TOPIC}: {original_payload}")
        except Exception as e:
            print(f"[ERROR] Failed to publish replay event: {e}")