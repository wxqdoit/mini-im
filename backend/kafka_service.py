import json
import threading
import time
from confluent_kafka import Producer, Consumer, KafkaError
from confluent_kafka.admin import AdminClient, NewTopic
from config import Config
from db import get_db
from redis_client import publish_event, set_user_online

_kafka_producer = None
_consumer_thread = None
_stop_consumer = threading.Event()

def ensure_topic_exists():
    try:
        admin = AdminClient({'bootstrap.servers': Config.KAFKA_BOOTSTRAP_SERVERS})
        meta = admin.list_topics(timeout=3)
        if Config.KAFKA_MSG_TOPIC not in meta.topics:
            print(f"Creating Kafka topic '{Config.KAFKA_MSG_TOPIC}'...")
            futures = admin.create_topics([
                NewTopic(Config.KAFKA_MSG_TOPIC, num_partitions=1, replication_factor=1)
            ])
            for t, f in futures.items():
                f.result()
            print(f"Kafka topic '{Config.KAFKA_MSG_TOPIC}' created.")
    except Exception as e:
        print(f"Warning checking/creating Kafka topic: {e}")

def get_kafka_producer():
    global _kafka_producer
    if _kafka_producer is None:
        conf = {
            'bootstrap.servers': Config.KAFKA_BOOTSTRAP_SERVERS,
            'client.id': 'mini_im_producer',
            'retries': 3,
            'retry.backoff.ms': 100,
            'linger.ms': 0, # Send immediately without batch delay
        }
        _kafka_producer = Producer(conf)
    return _kafka_producer

def send_to_kafka(topic, key, data):
    """
    Produce message to Kafka topic and flush immediately for real-time delivery.
    """
    try:
        producer = get_kafka_producer()
        payload = json.dumps(data, default=str).encode('utf-8')
        producer.produce(
            topic,
            key=str(key).encode('utf-8'),
            value=payload,
            callback=delivery_report
        )
        producer.flush(timeout=1.0)
        return True
    except Exception as e:
        print(f"Failed to produce to Kafka: {e}")
        # Fallback: process directly so messages never get lost
        try:
            _process_kafka_message(data)
            return True
        except Exception as ex:
            print(f"Fallback direct processing error: {ex}")
            return False

def delivery_report(err, msg):
    if err is not None:
        print(f"Message delivery to Kafka failed: {err}")

def start_kafka_consumer():
    """
    Starts the Kafka consumer background thread.
    """
    ensure_topic_exists()
    global _consumer_thread
    if _consumer_thread is None or not _consumer_thread.is_alive():
        _stop_consumer.clear()
        _consumer_thread = threading.Thread(target=_kafka_consumer_loop, daemon=True)
        _consumer_thread.start()
        print("Kafka consumer background thread started.")

def _kafka_consumer_loop():
    conf = {
        'bootstrap.servers': Config.KAFKA_BOOTSTRAP_SERVERS,
        'group.id': Config.KAFKA_CONSUMER_GROUP,
        'auto.offset.reset': 'latest',
        'enable.auto.commit': True
    }
    
    while not _stop_consumer.is_set():
        try:
            consumer = Consumer(conf)
            consumer.subscribe([Config.KAFKA_MSG_TOPIC])
            print(f"Kafka consumer subscribed to {Config.KAFKA_MSG_TOPIC}")
            
            while not _stop_consumer.is_set():
                msg = consumer.poll(timeout=0.2)
                if msg is None:
                    continue
                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        continue
                    else:
                        print(f"Kafka consumer error: {msg.error()}")
                        time.sleep(1)
                        continue
                
                try:
                    payload = json.loads(msg.value().decode('utf-8'))
                    _process_kafka_message(payload)
                except Exception as ex:
                    print(f"Error processing Kafka message: {ex}")
            
            consumer.close()
        except Exception as e:
            print(f"Kafka consumer connection error: {e}. Retrying in 2 seconds...")
            time.sleep(2)

def _process_kafka_message(data):
    """
    Consumes chat message from Kafka, saves it into PostgreSQL,
    and publishes real-time notification to Redis channels.
    """
    event_type = data.get("event_type", "chat_message")
    if event_type != "chat_message":
        return

    conv_type = data.get("conversation_type")  # 'direct' or 'group'
    sender_id = data.get("sender_id")
    recipient_id = data.get("recipient_id")
    msg_type = data.get("msg_type", "text")
    content = data.get("content", "")
    media_url = data.get("media_url", "")
    file_name = data.get("file_name", "")
    file_size = data.get("file_size", 0)
    is_encrypted = data.get("is_encrypted", False)
    iv = data.get("iv", "")
    ephemeral_key = data.get("ephemeral_key", "")
    encrypted_key_bundle = data.get("encrypted_key_bundle", None)
    if isinstance(encrypted_key_bundle, dict):
        encrypted_key_bundle_json = json.dumps(encrypted_key_bundle)
    else:
        encrypted_key_bundle_json = encrypted_key_bundle

    # 1. Insert into PostgreSQL
    saved_msg = None
    with get_db() as cur:
        # Fetch sender info
        cur.execute("SELECT id, username, nickname, avatar FROM users WHERE id = %s", (sender_id,))
        sender = cur.fetchone()

        insert_sql = """
            INSERT INTO messages (
                conversation_type, sender_id, recipient_id, 
                msg_type, content, media_url, file_name, file_size, 
                is_read, is_encrypted, iv, ephemeral_key, encrypted_key_bundle
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, FALSE, %s, %s, %s, %s)
            RETURNING id, created_at;
        """
        cur.execute(insert_sql, (
            conv_type, sender_id, recipient_id, 
            msg_type, content, media_url, file_name, file_size,
            is_encrypted, iv, ephemeral_key, encrypted_key_bundle_json
        ))
        row = cur.fetchone()
        
        saved_msg = {
            "id": row["id"],
            "conversation_type": conv_type,
            "sender_id": sender_id,
            "recipient_id": recipient_id,
            "msg_type": msg_type,
            "content": content,
            "media_url": media_url,
            "file_name": file_name,
            "file_size": file_size,
            "is_read": False,
            "is_encrypted": is_encrypted,
            "iv": iv,
            "ephemeral_key": ephemeral_key,
            "encrypted_key_bundle": encrypted_key_bundle,
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "sender": dict(sender) if sender else None
        }

    # 2. Publish to Redis for WebSocket distribution
    event_payload = {
        "event": "new_message",
        "data": saved_msg
    }

    if conv_type == "direct":
        # Notify receiver
        publish_event(f"mini_im:user:{recipient_id}", event_payload)
        # Notify sender (for multi-tab / acknowledgment)
        publish_event(f"mini_im:user:{sender_id}", event_payload)
    elif conv_type == "group":
        # Notify all group members via group channel
        publish_event(f"mini_im:group:{recipient_id}", event_payload)
