import gevent
import json
import re
import threading
from collections import defaultdict
from flask import request
from flask_sock import Sock
from auth import decode_token
from config import Config
from db import get_db
import time
from redis_client import (
    get_redis_client, set_user_online, set_user_offline,
    refresh_user_heartbeat, publish_event, get_user_status,
    get_cached_group_members, cache_group_members,
    register_user_gateway, refresh_user_gateway, unregister_user_gateway,
    get_user_gateway, publish_to_gateways_for_users
)
from kafka_service import send_to_kafka
from rate_limiter import check_rate_limit


def _async_update_db_user_status(user_id: int, status: str):
    try:
        with get_db() as cur:
            cur.execute("UPDATE users SET status = %s WHERE id = %s", (status, user_id))
    except Exception:
        pass

sock = Sock()

# Gateway Node Identity
NODE_ID = getattr(Config, 'NODE_ID', 'default_gateway')

# In-memory map: user_id -> set of active ws connections on THIS node
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
        print(f"WebSocket Gateway [{NODE_ID}] Redis Precision Listener thread started.")

def _redis_listener_loop():
    r = get_redis_client()
    pubsub = r.pubsub()

    # 1. High-Performance Precision Node Channel
    node_channel = f"mini_im:node:{NODE_ID}"
    pubsub.subscribe(node_channel, "mini_im:broadcast", "mini_im:presence", "mini_im:user_profile_updated")
    
    # Also pattern-subscribe to legacy channels for backwards compatibility
    pubsub.psubscribe("mini_im:user:*", "mini_im:group:*")
    print(f"Node [{NODE_ID}] subscribed to precision channel: {node_channel}")

    for message in pubsub.listen():
        msg_type = message["type"]
        if msg_type not in ["pmessage", "message"]:
            continue
        try:
            channel = message["channel"]
            raw_data = message["data"]
            data = json.loads(raw_data) if isinstance(raw_data, str) else raw_data

            # Case A: Precision Node Message (Targeted dispatch to local connections)
            if channel == node_channel:
                target_user_ids = data.get("target_user_ids")
                if target_user_ids:
                    # Filter data to transmit
                    event_payload = {
                        "event": data.get("event"),
                        "data": data.get("data")
                    }
                    for uid in target_user_ids:
                        _send_to_user(uid, event_payload)
                else:
                    # Single targeted user payload
                    uid = data.get("user_id") or data.get("data", {}).get("recipient_id")
                    if uid:
                        _send_to_user(uid, data)
                continue

            # Case B: Global Broadcast
            if channel == "mini_im:broadcast":
                _broadcast_all(data)
                continue

            # Case C: Targeted presence & profile update (push to friends)
            if channel in ["mini_im:user_profile_updated", "mini_im:presence"]:
                user_id = data.get("data", {}).get("user_id") or data.get("user", {}).get("id")
                if user_id:
                    _notify_friends(user_id, data)
                else:
                    _broadcast_all(data)
                continue

            # Case D: Backward-compatible Direct User channel
            user_match = re.match(r"^mini_im:user:(\d+)$", channel)
            if user_match:
                target_uid = int(user_match.group(1))
                _send_to_user(target_uid, data)
                continue

            # Case E: Backward-compatible Group channel
            group_match = re.match(r"^mini_im:group:(\d+)$", channel)
            if group_match:
                group_id = int(group_match.group(1))
                _send_to_group(group_id, data)
                continue

        except Exception as e:
            print(f"Error handling Redis pubsub message on [{NODE_ID}]: {e}")

def _send_to_user(user_id, data):
    with connections_lock:
        sockets = list(active_connections.get(user_id, set()))
    
    if not sockets:
        return

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
    members = get_cached_group_members(group_id)
    if members is not None:
        return members
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

    unregister_user_gateway(user_id, NODE_ID)
    set_user_offline(user_id)
    gevent.spawn(_async_update_db_user_status, user_id, "offline")

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

    # Register user to this gateway node in Redis Precision Router
    register_user_gateway(user_id, NODE_ID)
    set_user_online(user_id, "online")
    gevent.spawn(_async_update_db_user_status, user_id, "online")

    publish_event("mini_im:presence", {
        "event": "user_status_changed",
        "data": {"user_id": user_id, "status": "online", "is_online": True}
    })

    # Acknowledge connection with node identity
    try:
        ws.send(json.dumps({
            "event": "connected",
            "data": {
                "user_id": user_id,
                "node_id": NODE_ID,
                "message": f"Connected to Mini IM WebSocket Gateway ({NODE_ID})"
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

            # 1. Heartbeat Ping -> Pong + Touch TTL + Refresh Node Route
            if msg_type == "ping":
                refresh_user_heartbeat(user_id)
                refresh_user_gateway(user_id)
                try:
                    ws.send(json.dumps({"type": "pong"}))
                except Exception:
                    break
                continue

            # 2. Client Message ACK (Reliable Delivery Protocol)
            if msg_type == "ack":
                msg_id = msg_data.get("msg_id")
                if msg_id:
                    try:
                        with get_db() as cur:
                            cur.execute(
                                "UPDATE messages SET is_read = TRUE WHERE id = %s AND recipient_id = %s",
                                (msg_id, user_id)
                            )
                    except Exception as e:
                        print(f"Error processing client ACK: {e}")
                continue

            # 3. Incremental Delta Sync Protocol (Offline Message Recovery)
            if msg_type == "sync":
                conv_type = msg_data.get("conversation_type")
                target_id = msg_data.get("target_id")
                last_seq_id = msg_data.get("last_seq_id", 0)
                if conv_type and target_id is not None:
                    try:
                        with get_db() as cur:
                            if conv_type == "direct":
                                cur.execute("""
                                    SELECT m.id, m.conversation_type, m.sender_id, m.recipient_id,
                                           m.msg_type, m.content, m.media_url, m.file_name, m.file_size,
                                           m.is_read, m.is_encrypted, m.iv, m.ephemeral_key, m.encrypted_key_bundle,
                                           m.seq_id, m.created_at,
                                           json_build_object('id', u.id, 'username', u.username, 'nickname', u.nickname, 'avatar', u.avatar) as sender
                                    FROM messages m
                                    JOIN users u ON m.sender_id = u.id
                                    WHERE m.conversation_type = 'direct'
                                      AND ((m.sender_id = %s AND m.recipient_id = %s) OR (m.sender_id = %s AND m.recipient_id = %s))
                                      AND m.seq_id > %s
                                    ORDER BY m.seq_id ASC LIMIT 100;
                                """, (user_id, target_id, target_id, user_id, last_seq_id))
                            elif conv_type == "group":
                                cur.execute("""
                                    SELECT m.id, m.conversation_type, m.sender_id, m.recipient_id,
                                           m.msg_type, m.content, m.media_url, m.file_name, m.file_size,
                                           m.is_read, m.is_encrypted, m.iv, m.ephemeral_key, m.encrypted_key_bundle,
                                           m.seq_id, m.created_at,
                                           json_build_object('id', u.id, 'username', u.username, 'nickname', u.nickname, 'avatar', u.avatar) as sender
                                    FROM messages m
                                    JOIN users u ON m.sender_id = u.id
                                    WHERE m.conversation_type = 'group' AND m.recipient_id = %s AND m.seq_id > %s
                                    ORDER BY m.seq_id ASC LIMIT 100;
                                """, (target_id, last_seq_id))
                            delta_msgs = [dict(r) for r in cur.fetchall()]
                            for r in delta_msgs:
                                if r.get("created_at"):
                                    r["created_at"] = r["created_at"].isoformat()

                            ws.send(json.dumps({
                                "event": "sync_delta",
                                "data": {
                                    "conversation_type": conv_type,
                                    "target_id": target_id,
                                    "last_seq_id": last_seq_id,
                                    "messages": delta_msgs
                                }
                            }, default=str))
                    except Exception as e:
                        print(f"Error handling sync request: {e}")
                continue

            # 4. Chat message sent via WebSocket
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
                continue

            # 5. WebRTC Audio/Video Call Signaling Engine
            if msg_type == "call_invite":
                target_id = int(msg_data.get("recipient_id") or msg_data.get("target_id") or 0)
                call_id = msg_data.get("call_id")
                call_type = msg_data.get("call_type", "video")
                if target_id and call_id:
                    target_gw = get_user_gateway(target_id)
                    if not target_gw:
                        try:
                            ws.send(json.dumps({
                                "event": "call_failed",
                                "data": {"call_id": call_id, "recipient_id": target_id, "reason": "User is currently offline"}
                            }))
                        except Exception:
                            pass
                    else:
                        r = get_redis_client()
                        call_info = {
                            "call_id": call_id,
                            "caller_id": user_id,
                            "recipient_id": target_id,
                            "call_type": call_type,
                            "status": "ringing",
                            "created_at": time.time()
                        }
                        r.set(f"mini_im:call:{call_id}", json.dumps(call_info), ex=60)
                        caller_info = {
                            "id": user.get("id"),
                            "username": user.get("username"),
                            "nickname": user.get("nickname"),
                            "avatar": user.get("avatar")
                        }
                        publish_to_gateways_for_users([target_id], {
                            "event": "call_invite",
                            "data": {
                                "call_id": call_id,
                                "caller_id": user_id,
                                "caller": caller_info,
                                "recipient_id": target_id,
                                "call_type": call_type
                            }
                        })
                continue

            if msg_type == "call_ringing":
                caller_id = int(msg_data.get("caller_id") or 0)
                call_id = msg_data.get("call_id")
                if caller_id and call_id:
                    publish_to_gateways_for_users([caller_id], {
                        "event": "call_ringing",
                        "data": {"call_id": call_id, "recipient_id": user_id}
                    })
                continue

            if msg_type == "call_accept":
                caller_id = int(msg_data.get("caller_id") or 0)
                call_id = msg_data.get("call_id")
                if caller_id and call_id:
                    r = get_redis_client()
                    call_key = f"mini_im:call:{call_id}"
                    raw_call = r.get(call_key)
                    if raw_call:
                        try:
                            call_record = json.loads(raw_call)
                            call_record["status"] = "connected"
                            r.set(call_key, json.dumps(call_record), ex=3600)
                        except Exception:
                            pass
                    publish_to_gateways_for_users([caller_id], {
                        "event": "call_accept",
                        "data": {"call_id": call_id, "recipient_id": user_id}
                    })
                continue

            if msg_type == "call_reject":
                caller_id = int(msg_data.get("caller_id") or 0)
                call_id = msg_data.get("call_id")
                reason = msg_data.get("reason", "declined")
                if caller_id and call_id:
                    r = get_redis_client()
                    r.delete(f"mini_im:call:{call_id}")
                    publish_to_gateways_for_users([caller_id], {
                        "event": "call_reject",
                        "data": {"call_id": call_id, "recipient_id": user_id, "reason": reason}
                    })
                continue

            if msg_type == "call_hangup":
                target_id = int(msg_data.get("target_id") or msg_data.get("recipient_id") or msg_data.get("caller_id") or 0)
                call_id = msg_data.get("call_id")
                if call_id:
                    r = get_redis_client()
                    r.delete(f"mini_im:call:{call_id}")
                if target_id and call_id:
                    publish_to_gateways_for_users([target_id], {
                        "event": "call_hangup",
                        "data": {"call_id": call_id, "sender_id": user_id}
                    })
                continue

            if msg_type in ["webrtc_offer", "webrtc_answer", "webrtc_ice_candidate"]:
                target_id = int(msg_data.get("target_id") or msg_data.get("recipient_id") or 0)
                call_id = msg_data.get("call_id")
                if target_id and call_id:
                    publish_to_gateways_for_users([target_id], {
                        "event": msg_type,
                        "data": {
                            "call_id": call_id,
                            "sender_id": user_id,
                            "sdp": msg_data.get("sdp"),
                            "candidate": msg_data.get("candidate")
                        }
                    })
                continue

    except Exception as e:
        print(f"WebSocket closed/error for user {user_id} on [{NODE_ID}]: {e}")
    finally:
        with connections_lock:
            active_connections[user_id].discard(ws)
            is_empty = len(active_connections[user_id]) == 0
            if is_empty:
                active_connections.pop(user_id, None)

        if is_empty:
            unregister_user_gateway(user_id, NODE_ID)
            set_user_offline(user_id)
            gevent.spawn(_async_update_db_user_status, user_id, "offline")

            publish_event("mini_im:presence", {
                "event": "user_status_changed",
                "data": {"user_id": user_id, "status": "offline", "is_online": False}
            })
