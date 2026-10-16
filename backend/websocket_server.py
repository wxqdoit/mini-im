import json
import re
import threading
from collections import defaultdict
from flask import request
from flask_sock import Sock
from auth import decode_token
from config import Config
from db import get_db
from redis_client import (
    get_redis_client, set_user_online, set_user_offline,
    refresh_user_heartbeat, publish_event, get_user_status
)
from kafka_service import send_to_kafka

sock = Sock()

# In-memory map: user_id -> set of active ws connections
active_connections = defaultdict(set)
connections_lock = threading.Lock()
_redis_pubsub_thread = None

def register_websocket(app):
    sock.init_app(app)
    start_redis_pubsub_listener()

def start_redis_pubsub_listener():
    global _redis_pubsub_thread
    if _redis_pubsub_thread is None or not _redis_pubsub_thread.is_alive():
        _redis_pubsub_thread = threading.Thread(target=_redis_listener_loop, daemon=True)
        _redis_pubsub_thread.start()
        print("Redis Pub/Sub listener thread started.")

def _redis_listener_loop():
    r = get_redis_client()
    pubsub = r.pubsub()
    pubsub.psubscribe("mini_im:*")
    print("Subscribed to Redis pattern 'mini_im:*'")

    for message in pubsub.listen():
        if message["type"] not in ["pmessage", "message"]:
            continue
        try:
            channel = message["channel"]
            raw_data = message["data"]
            data = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
            
            # 1. Direct user event: mini_im:user:<user_id>
            user_match = re.match(r"^mini_im:user:(\d+)$", channel)
            if user_match:
                target_uid = int(user_match.group(1))
                _send_to_user(target_uid, data)
                continue

            # 2. Group event: mini_im:group:<group_id>
            group_match = re.match(r"^mini_im:group:(\d+)$", channel)
            if group_match:
                group_id = int(group_match.group(1))
                _send_to_group(group_id, data)
                continue

            # 3. Global broadcast events (profile updates, status changes)
            if channel in ["mini_im:user_profile_updated", "mini_im:presence"]:
                _broadcast_all(data)
                continue

        except Exception as e:
            print(f"Error handling Redis pubsub message: {e}")

def _send_to_user(user_id, data):
    with connections_lock:
        sockets = list(active_connections.get(user_id, set()))
    
    dead_sockets = []
    payload_str = json.dumps(data, default=str)
    for ws in sockets:
        try:
            ws.send(payload_str)
        except Exception:
            dead_sockets.append(ws)

    if dead_sockets:
        with connections_lock:
            for dws in dead_sockets:
                active_connections[user_id].discard(dws)

def _send_to_group(group_id, data):
    member_ids = []
    try:
        with get_db() as cur:
            cur.execute("SELECT user_id FROM group_members WHERE group_id = %s", (group_id,))
            member_ids = [row["user_id"] for row in cur.fetchall()]
    except Exception as e:
        print(f"Error fetching group members for group {group_id}: {e}")
        return

    payload_str = json.dumps(data, default=str)
    for uid in member_ids:
        with connections_lock:
            sockets = list(active_connections.get(uid, set()))
        dead_sockets = []
        for ws in sockets:
            try:
                ws.send(payload_str)
            except Exception:
                dead_sockets.append(ws)
        if dead_sockets:
            with connections_lock:
                for dws in dead_sockets:
                    active_connections[uid].discard(dws)

def _broadcast_all(data):
    payload_str = json.dumps(data, default=str)
    with connections_lock:
        all_sockets = [ws for s in active_connections.values() for ws in s]
    for ws in all_sockets:
        try:
            ws.send(payload_str)
        except Exception:
            pass

def close_user_connections(user_id):
    """
    Called when user logs out: closes sockets and marks user offline.
    """
    with connections_lock:
        sockets = list(active_connections.get(user_id, set()))
        active_connections.pop(user_id, None)

    for ws in sockets:
        try:
            ws.close(1000, "Logged out")
        except Exception:
            pass

    set_user_offline(user_id)
    try:
        with get_db() as cur:
            cur.execute("UPDATE users SET status = 'offline' WHERE id = %s", (user_id,))
    except Exception:
        pass

    publish_event("mini_im:presence", {
        "event": "user_status_changed",
        "data": {"user_id": user_id, "status": "offline", "is_online": False}
    })

@sock.route("/ws")
def handle_websocket(ws):
    token = request.args.get("token")
    user = None
    if token:
        user = decode_token(token)

    if not user:
        try:
            init_msg_raw = ws.receive(timeout=10)
            if not init_msg_raw:
                ws.close()
                return
            init_msg = json.loads(init_msg_raw)
            if init_msg.get("type") == "auth":
                user = decode_token(init_msg.get("token", ""))
        except Exception:
            ws.close()
            return

    if not user:
        try:
            ws.send(json.dumps({"error": "Unauthorized"}))
            ws.close()
        except Exception:
            pass
        return

    user_id = user["id"]
    with connections_lock:
        active_connections[user_id].add(ws)

    set_user_online(user_id, "online")
    try:
        with get_db() as cur:
            cur.execute("UPDATE users SET status = 'online' WHERE id = %s", (user_id,))
    except Exception:
        pass

    publish_event("mini_im:presence", {
        "event": "user_status_changed",
        "data": {"user_id": user_id, "status": "online", "is_online": True}
    })

    # Acknowledge connection
    try:
        ws.send(json.dumps({
            "event": "connected",
            "data": {
                "user_id": user_id,
                "message": "Connected to Mini IM WebSocket Server"
            }
        }))
    except Exception:
        pass

    try:
        while True:
            # Receive with 35s timeout: clients ping every 15-20s.
            # If no ping/message is received within 35s, cleanly terminate zombie session.
            raw_msg = ws.receive(timeout=35)
            if raw_msg is None:
                # Timed out or connection closed
                break
            
            try:
                msg_data = json.loads(raw_msg)
            except Exception:
                continue

            msg_type = msg_data.get("type")

            # Heartbeat Ping -> Pong + Touch TTL
            if msg_type == "ping":
                refresh_user_heartbeat(user_id)
                try:
                    ws.send(json.dumps({"type": "pong"}))
                except Exception:
                    break
                continue

            # Chat message sent via WebSocket
            if msg_type == "chat_message":
                conv_type = msg_data.get("conversation_type")
                recipient_id = msg_data.get("recipient_id")
                content = msg_data.get("content", "")
                m_type = msg_data.get("msg_type", "text")
                media_url = msg_data.get("media_url", "")
                file_name = msg_data.get("file_name", "")
                file_size = msg_data.get("file_size", 0)
                is_encrypted = msg_data.get("is_encrypted", False)
                iv = msg_data.get("iv", "")
                ephemeral_key = msg_data.get("ephemeral_key", "")
                encrypted_key_bundle = msg_data.get("encrypted_key_bundle", None)

                if conv_type and recipient_id:
                    kafka_payload = {
                        "event_type": "chat_message",
                        "conversation_type": conv_type,
                        "sender_id": user_id,
                        "recipient_id": int(recipient_id),
                        "msg_type": m_type,
                        "content": content,
                        "media_url": media_url,
                        "file_name": file_name,
                        "file_size": file_size,
                        "is_encrypted": is_encrypted,
                        "iv": iv,
                        "ephemeral_key": ephemeral_key,
                        "encrypted_key_bundle": encrypted_key_bundle
                    }
                    send_to_kafka(
                        Config.KAFKA_MSG_TOPIC,
                        f"{conv_type}:{recipient_id}",
                        kafka_payload
                    )

    except Exception as e:
        print(f"WebSocket closed/error for user {user_id}: {e}")
    finally:
        with connections_lock:
            active_connections[user_id].discard(ws)
            is_empty = len(active_connections[user_id]) == 0
            if is_empty:
                active_connections.pop(user_id, None)

        if is_empty:
            set_user_offline(user_id)
            try:
                with get_db() as cur:
                    cur.execute("UPDATE users SET status = 'offline' WHERE id = %s", (user_id,))
            except Exception:
                pass

            publish_event("mini_im:presence", {
                "event": "user_status_changed",
                "data": {"user_id": user_id, "status": "offline", "is_online": False}
            })
