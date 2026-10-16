import json
import threading
import time
from confluent_kafka import Producer, Consumer, KafkaError
from confluent_kafka.admin import AdminClient, NewTopic
from config import Config
from db import get_db, bulk_insert_messages
from redis_client import (
    publish_event, get_next_seq_id, get_cached_group_members,
    cache_group_members, publish_to_gateways_for_users
)

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
                NewTopic(Config.KAFKA_MSG_TOPIC, num_partitions=4, replication_factor=1)
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
            'linger.ms': 5,
            'batch.num.messages': 1000,
            'queue.buffering.max.messages': 100000,
        }
        _kafka_producer = Producer(conf)
    return _kafka_producer

def send_to_kafka(topic, key, data):
    """
    Non-blocking asynchronous message production into Kafka topic.
    Automatically assigns monotonic 64-bit sequence ID (SeqID) to guarantee total order.
    """
    try:
        # Assign monotonic sequence ID if not already present
        if not data.get("seq_id"):
            conv_type = data.get("conversation_type")
            sender_id = data.get("sender_id")
            recipient_id = data.get("recipient_id")
            if conv_type == "direct" and sender_id and recipient_id:
                data["seq_id"] = get_next_seq_id("direct", sender_id, recipient_id)
            elif conv_type == "group" and recipient_id:
                data["seq_id"] = get_next_seq_id("group", recipient_id)

        producer = get_kafka_producer()
        payload = json.dumps(data, default=str).encode('utf-8')
        producer.produce(
            topic,
            key=str(key).encode('utf-8'),
            value=payload,
            callback=delivery_report
        )
        producer.poll(0)
        return True
    except Exception as e:
        print(f"Failed to produce to Kafka: {e}")
        # High-availability Fallback: process directly so messages are never lost
        try:
            _process_kafka_batch([data])
            return True
        except Exception as ex:
            print(f"Fallback direct processing error: {ex}")
            return False

def delivery_report(err, msg):
    if err is not None:
        print(f"Message delivery to Kafka failed: {err}")

def start_kafka_consumer():
    """
    Starts the Kafka consumer background thread with micro-batching.
    """
    ensure_topic_exists()
    global _consumer_thread
    if _consumer_thread is None or not _consumer_thread.is_alive():
        _stop_consumer.clear()
        _consumer_thread = threading.Thread(target=_kafka_consumer_loop, daemon=True)
        _consumer_thread.start()
        print("Kafka micro-batching consumer background thread started.")

def _kafka_consumer_loop():
    def on_assign(c, partitions):
        print(f"Kafka consumer assigned partitions: {partitions}")

    conf = {
        'bootstrap.servers': Config.KAFKA_BOOTSTRAP_SERVERS,
        'group.id': Config.KAFKA_CONSUMER_GROUP,
        'auto.offset.reset': 'earliest',
        'enable.auto.commit': True,
        'session.timeout.ms': 6000,
        'heartbeat.interval.ms': 1000
    }
    
    batch_size = getattr(Config, 'KAFKA_BATCH_SIZE', 200)
    batch_timeout = getattr(Config, 'KAFKA_BATCH_TIMEOUT_MS', 50) / 1000.0

    while not _stop_consumer.is_set():
        try:
            consumer = Consumer(conf)
            consumer.subscribe([Config.KAFKA_MSG_TOPIC], on_assign=on_assign)
            print(f"Kafka consumer subscribed to {Config.KAFKA_MSG_TOPIC} (batch_size={batch_size})")
            
            while not _stop_consumer.is_set():
                msgs = consumer.consume(num_messages=batch_size, timeout=batch_timeout)
                if not msgs:
                    time.sleep(0.01)
                    continue

                batch_items = []
                for msg in msgs:
                    if msg.error():
                        if msg.error().code() == KafkaError._PARTITION_EOF:
                            continue
                        print(f"Kafka consumer error: {msg.error()}")
                        continue
                    try:
                        payload = json.loads(msg.value().decode('utf-8'))
                        if payload.get("event_type") == "chat_message":
                            batch_items.append(payload)
                    except Exception as ex:
                        print(f"Error decoding Kafka message: {ex}")
                
                if batch_items:
                    try:
                        _process_kafka_batch(batch_items)
                    except Exception as ex:
                        print(f"Error processing Kafka batch: {ex}")
            
            consumer.close()
        except Exception as e:
            print(f"Kafka consumer connection error: {e}. Retrying in 2 seconds...")
            time.sleep(2)

def _get_group_members_cached(group_id: int) -> set:
    members = get_cached_group_members(group_id)
    if members is not None:
        return members
    try:
        with get_db() as cur:
            cur.execute("SELECT user_id FROM group_members WHERE group_id = %s", (group_id,))
            m_ids = [row["user_id"] for row in cur.fetchall()]
        cache_group_members(group_id, m_ids)
        return set(m_ids)
    except Exception as e:
        print(f"Error fetching group members: {e}")
        return set()

def _process_kafka_batch(messages_batch: list):
    """
    Consumes a micro-batch of chat messages, saves them into PostgreSQL via bulk_insert_messages,
    and dispatches them using Precision Gateway Routing.
    """
    if not messages_batch:
        return

    # 1. Bulk insert all messages in one DB round trip
    persisted_messages = bulk_insert_messages(messages_batch)

    # 2. Dispatch events with Precision Routing
    for saved_msg in persisted_messages:
        conv_type = saved_msg.get("conversation_type")
        sender_id = saved_msg.get("sender_id")
        recipient_id = saved_msg.get("recipient_id")
        
        event_payload = {
            "event": "new_message",
            "data": saved_msg
        }

        if conv_type == "direct":
            # Precision routing directly to sender & recipient active gateway nodes
            publish_to_gateways_for_users([recipient_id, sender_id], event_payload)
        elif conv_type == "group":
            member_ids = _get_group_members_cached(recipient_id)
            if member_ids:
                publish_to_gateways_for_users(list(member_ids), event_payload)

def _process_kafka_message(single_data: dict):
    _process_kafka_batch([single_data])
