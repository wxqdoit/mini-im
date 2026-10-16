import os
import time
os.environ["SERVICE_ROLE"] = "worker"
from app import create_app
from kafka_service import start_kafka_consumer, _stop_consumer

if __name__ == "__main__":
    print("Starting Mini IM Dedicated Kafka Batch Consumer Worker...")
    app = create_app("worker")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        _stop_consumer.set()
        print("Worker stopped gracefully.")
