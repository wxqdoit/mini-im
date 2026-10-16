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
    refresh_user_heartbeat, publish_event, get_user_status,
    get_cached_group_members, cache_group_members
)
from kafka_service import send_to_kafka
from rate_limiter import check_rate_limit

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

            # 3. Targeted presence & profile update: push only to friends to eliminate O(N^2) broadcast storms
            if channel in ["mini_im:user_profile_updated", "mini_im:presence"]:
                user_id = data.get("data", {}).get("user_id") or data.get("user", {}).get("id")
                if user_id:
                    _notify_friends(user_id, data)
                else:
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

def _get_group_members_fast(group_id: int):
    """
    Cached group member retrieval. Checks Redis first; falls back to DB on cache miss.
    """
    members = get_cached_group_members(group_id)
    if members is not None:
        return members
    
    # Query DB and cache in Redis
    try:
        with get_db() as cur:
            cur.execute("SELECT user_id FROM group_members WHERE group_id = %s", (group_id,))
            member_ids = [row["user_id"] for row in cur.fetchall()]
        cache_group_members(group_id, member_ids)
        return set(member_ids)
    except Exception as e:
        print(f"Error fetching group members for group {group_id}: {e}")
        return set()

def _send_to_group(group_id, data):
    member_ids = _get_group_members_fast(group_id)
    payload_str = json.dumps(data, default=str)
    
    for uid in member_ids:
        with connections_lock:
            sockets = list(active_connections.get(uid, set()))
        if not sockets:
            continue
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

def _notify_friends(user_id, data):
    """
    Targeted fan-out: only notify friends of status/profile updates rather than full-world broadcast.
    """
    friend_ids = []
    try:
        with get_db() as cur:
            cur.execute("SELECT friend_id FROM friendships WHERE user_id = %s", (user_id,))
            friend_ids = [row["friend_id"] for row in cur.fetchall()]
    except Exception as e:
        print(f"Error fetching friends for presence notification: {e}")
        return

    for fid in friend_ids:
        _send_to_user(fid, data)

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
            raw_msg = ws.receive(timeout=35)
            if raw_msg is None:
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
                # Rate limit: max 25 msgs per 5s per user
                rl_key = f"mini_im:ratelimit:ws_chat:{user_id}"
                if not check_rate_limit(rl_key, limit=25, window_seconds=5):
                    try:
                        ws.send(json.dumps({"error": "Rate limit exceeded. Please slow down."}))
                    except Exception:
                        break
                    continue

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
                    recipient_id = int(recipient_id)
                    # Security check: group membership verification
                    if conv_type == "group":
                        members = _get_group_members_fast(recipient_id)
                        if user_id not in members:
                            try:
                                ws.send(json.dumps({"error": "Forbidden: You are not a member of this group"}))
                            except Exception:
                                break
                            continue

                    kafka_payload = {
                        "event_type": "chat_message",
                        "conversation_type": conv_type,
                        "sender_id": user_id,
                        "recipient_id": recipient_id,
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
