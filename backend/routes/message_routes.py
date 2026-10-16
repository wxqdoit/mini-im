import datetime
from flask import Blueprint, request, jsonify, g
from db import get_db
from auth import token_required
from config import Config
from kafka_service import send_to_kafka
from redis_client import get_users_presence_batch
from rate_limiter import rate_limit

message_bp = Blueprint("messages", __name__, url_prefix="/api/messages")

@message_bp.route("/send", methods=["POST"])
@token_required
@rate_limit("send_msg", limit=30, window_seconds=5, by_user=True)
def send_message():
    sender_id = g.current_user["id"]
    data = request.get_json() or {}
    
    conv_type = data.get("conversation_type")  # 'direct' or 'group'
    recipient_id = data.get("recipient_id")
    msg_type = data.get("msg_type", "text")    # 'text', 'image', 'file'
    content = data.get("content", "").strip()
    media_url = data.get("media_url", "")
    file_name = data.get("file_name", "")
    file_size = data.get("file_size", 0)
    is_encrypted = data.get("is_encrypted", False)
    iv = data.get("iv", "")
    ephemeral_key = data.get("ephemeral_key", "")
    encrypted_key_bundle = data.get("encrypted_key_bundle", None)

    if not conv_type or not recipient_id:
        return jsonify({"error": "conversation_type and recipient_id are required"}), 400

    recipient_id = int(recipient_id)

    # Security check: group membership verification
    if conv_type == "group":
        with get_db() as cur:
            cur.execute("SELECT 1 FROM group_members WHERE group_id = %s AND user_id = %s", (recipient_id, sender_id))
            if not cur.fetchone():
                return jsonify({"error": "Forbidden: You are not a member of this group"}), 403

    if msg_type == "text" and not content:
        return jsonify({"error": "Content cannot be empty"}), 400

    if msg_type in ["image", "file"] and not media_url:
        return jsonify({"error": "media_url required for media message"}), 400

    message_payload = {
        "event_type": "chat_message",
        "conversation_type": conv_type,
        "sender_id": sender_id,
        "recipient_id": recipient_id,
        "msg_type": msg_type,
        "content": content,
        "media_url": media_url,
        "file_name": file_name,
        "file_size": file_size,
        "is_encrypted": is_encrypted,
        "iv": iv,
        "ephemeral_key": ephemeral_key,
        "encrypted_key_bundle": encrypted_key_bundle,
        "created_at": datetime.datetime.utcnow().isoformat()
    }

    # Ingest message via Kafka
    kafka_key = f"{conv_type}:{recipient_id}"
    ok = send_to_kafka(Config.KAFKA_MSG_TOPIC, kafka_key, message_payload)

    return jsonify({
        "status": "queued" if ok else "failed",
        "message": "Message sent via Kafka pipeline" if ok else "Failed to send message to Kafka"
    }), 200 if ok else 500

@message_bp.route("/history", methods=["GET"])
@token_required
def get_message_history():
    current_user_id = g.current_user["id"]
    conv_type = request.args.get("type")  # 'direct' or 'group'
    target_id = request.args.get("target_id", type=int)
    limit = min(request.args.get("limit", default=50, type=int), 100)
    before_id = request.args.get("before_id", type=int)

    if not conv_type or not target_id:
        return jsonify({"error": "type and target_id are required"}), 400

    with get_db() as cur:
        # Security check: group membership authorization (prevents IDOR)
        if conv_type == "group":
            cur.execute("SELECT 1 FROM group_members WHERE group_id = %s AND user_id = %s", (target_id, current_user_id))
            if not cur.fetchone():
                return jsonify({"error": "Forbidden: You are not a member of this group"}), 403

        params = []
        where_clauses = ["m.conversation_type = %s"]
        params.append(conv_type)

        if conv_type == "direct":
            where_clauses.append("((m.sender_id = %s AND m.recipient_id = %s) OR (m.sender_id = %s AND m.recipient_id = %s))")
            params.extend([current_user_id, target_id, target_id, current_user_id])
        elif conv_type == "group":
            where_clauses.append("m.recipient_id = %s")
            params.append(target_id)
        else:
            return jsonify({"error": "Invalid conversation type"}), 400

        if before_id:
            where_clauses.append("m.id < %s")
            params.append(before_id)

        params.append(limit)

        sql = f"""
        SELECT m.id, m.conversation_type, m.sender_id, m.recipient_id,
               m.msg_type, m.content, m.media_url, m.file_name, m.file_size,
               m.is_read, m.is_encrypted, m.iv, m.ephemeral_key, m.encrypted_key_bundle, m.seq_id, m.created_at,
               json_build_object(
                   'id', u.id,
                   'username', u.username,
                   'nickname', u.nickname,
                   'avatar', u.avatar
               ) as sender
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        WHERE {' AND '.join(where_clauses)}
        ORDER BY m.id DESC
        LIMIT %s;
        """
        cur.execute(sql, tuple(params))
        messages = cur.fetchall()

    # Reverse so they are chronological
    messages.reverse()

    return jsonify({"messages": messages})


@message_bp.route("/sync", methods=["GET"])
@token_required
def sync_messages():
    """
    Incremental delta message synchronization by monotonic seq_id.
    Enables reliable client offline catch-up without missing or repeating messages.
    """
    current_user_id = g.current_user["id"]
    conv_type = request.args.get("type")
    target_id = request.args.get("target_id", type=int)
    last_seq_id = request.args.get("last_seq_id", default=0, type=int)
    limit = min(request.args.get("limit", default=50, type=int), 200)

    if not conv_type or target_id is None:
        return jsonify({"error": "type and target_id are required"}), 400

    with get_db() as cur:
        if conv_type == "group":
            cur.execute("SELECT 1 FROM group_members WHERE group_id = %s AND user_id = %s", (target_id, current_user_id))
            if not cur.fetchone():
                return jsonify({"error": "Forbidden: You are not a member of this group"}), 403

        if conv_type == "direct":
            sql = """
            SELECT m.id, m.conversation_type, m.sender_id, m.recipient_id,
                   m.msg_type, m.content, m.media_url, m.file_name, m.file_size,
                   m.is_read, m.is_encrypted, m.iv, m.ephemeral_key, m.encrypted_key_bundle,
                   m.seq_id, m.created_at,
                   json_build_object(
                       'id', u.id,
                       'username', u.username,
                       'nickname', u.nickname,
                       'avatar', u.avatar
                   ) as sender
            FROM messages m
            JOIN users u ON m.sender_id = u.id
            WHERE m.conversation_type = 'direct'
              AND ((m.sender_id = %s AND m.recipient_id = %s) OR (m.sender_id = %s AND m.recipient_id = %s))
              AND m.seq_id > %s
            ORDER BY m.seq_id ASC
            LIMIT %s;
            """
            cur.execute(sql, (current_user_id, target_id, target_id, current_user_id, last_seq_id, limit))
        elif conv_type == "group":
            sql = """
            SELECT m.id, m.conversation_type, m.sender_id, m.recipient_id,
                   m.msg_type, m.content, m.media_url, m.file_name, m.file_size,
                   m.is_read, m.is_encrypted, m.iv, m.ephemeral_key, m.encrypted_key_bundle,
                   m.seq_id, m.created_at,
                   json_build_object(
                       'id', u.id,
                       'username', u.username,
                       'nickname', u.nickname,
                       'avatar', u.avatar
                   ) as sender
            FROM messages m
            JOIN users u ON m.sender_id = u.id
            WHERE m.conversation_type = 'group' AND m.recipient_id = %s AND m.seq_id > %s
            ORDER BY m.seq_id ASC
            LIMIT %s;
            """
            cur.execute(sql, (target_id, last_seq_id, limit))
        else:
            return jsonify({"error": "Invalid conversation type"}), 400

        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            if r.get("created_at"):
                r["created_at"] = r["created_at"].isoformat()

    return jsonify({
        "conversation_type": conv_type,
        "target_id": target_id,
        "last_seq_id": last_seq_id,
        "count": len(rows),
        "messages": rows
    })

@message_bp.route("/read", methods=["POST"])
@token_required
def mark_read():
    current_user_id = g.current_user["id"]
    data = request.get_json() or {}
    sender_id = data.get("sender_id")

    if sender_id:
        with get_db() as cur:
            cur.execute("""
                UPDATE messages 
                SET is_read = TRUE 
                WHERE conversation_type = 'direct' 
                  AND sender_id = %s 
                  AND recipient_id = %s 
                  AND is_read = FALSE;
            """, (sender_id, current_user_id))

    return jsonify({"message": "Marked as read"})

@message_bp.route("/conversations", methods=["GET"])
@token_required
def get_conversations():
    user_id = g.current_user["id"]
    conversations = []

    with get_db() as cur:
        # 1. Direct conversations (friends)
        sql_friends = """
        SELECT u.id, u.username, u.nickname, u.avatar, u.bio
        FROM friendships f
        JOIN users u ON f.friend_id = u.id
        WHERE f.user_id = %s;
        """
        cur.execute(sql_friends, (user_id,))
        friends = cur.fetchall()

        # Batch fetch unread counts in ONE query instead of N loop queries
        cur.execute("""
            SELECT sender_id, COUNT(*) as unread
            FROM messages
            WHERE conversation_type = 'direct' AND recipient_id = %s AND is_read = FALSE
            GROUP BY sender_id;
        """, (user_id,))
        unread_map = {row["sender_id"]: row["unread"] for row in cur.fetchall()}

        # Batch fetch online statuses from Redis in ONE pipeline round-trip
        friend_ids = [f["id"] for f in friends]
        presence_map = get_users_presence_batch(friend_ids)

        for f in friends:
            cur.execute("""
                SELECT id, msg_type, content, media_url, created_at, sender_id, is_encrypted
                FROM messages
                WHERE conversation_type = 'direct'
                  AND ((sender_id = %s AND recipient_id = %s) OR (sender_id = %s AND recipient_id = %s))
                ORDER BY id DESC LIMIT 1;
            """, (user_id, f["id"], f["id"], user_id))
            last_msg = cur.fetchone()

            last_preview = ""
            last_time = None
            if last_msg:
                last_time = last_msg["created_at"].isoformat() if last_msg["created_at"] else None
                if last_msg.get("is_encrypted"):
                    last_preview = "🔒 [端到端加密]"
                elif last_msg["msg_type"] == "text":
                    last_preview = last_msg["content"]
                elif last_msg["msg_type"] == "image":
                    last_preview = "[图片]"
                else:
                    last_preview = "[文件]"

            p_info = presence_map.get(f["id"], {"is_online": False, "status": "offline"})

            conversations.append({
                "conversation_id": f"direct_{f['id']}",
                "type": "direct",
                "target_id": f["id"],
                "name": f["nickname"],
                "avatar": f["avatar"],
                "bio": f["bio"],
                "is_online": p_info["is_online"],
                "status": p_info["status"],
                "last_message": last_preview,
                "last_time": last_time,
                "unread_count": unread_map.get(f["id"], 0)
            })

        # 2. Group conversations
        sql_groups = """
        SELECT g.id, g.name, g.avatar, g.description
        FROM groups g
        JOIN group_members gm ON g.id = gm.group_id
        WHERE gm.user_id = %s;
        """
        cur.execute(sql_groups, (user_id,))
        groups = cur.fetchall()

        for g_row in groups:
            cur.execute("""
                SELECT m.id, m.msg_type, m.content, m.created_at, m.is_encrypted, u.nickname as sender_nickname
                FROM messages m
                JOIN users u ON m.sender_id = u.id
                WHERE m.conversation_type = 'group' AND m.recipient_id = %s
                ORDER BY m.id DESC LIMIT 1;
            """, (g_row["id"],))
            last_msg = cur.fetchone()

            last_preview = ""
            last_time = None
            if last_msg:
                last_time = last_msg["created_at"].isoformat() if last_msg["created_at"] else None
                prefix = f"{last_msg['sender_nickname']}: "
                if last_msg.get("is_encrypted"):
                    last_preview = prefix + "🔒 [端到端加密]"
                elif last_msg["msg_type"] == "text":
                    last_preview = prefix + last_msg["content"]
                elif last_msg["msg_type"] == "image":
                    last_preview = prefix + "[图片]"
                else:
                    last_preview = prefix + "[文件]"

            conversations.append({
                "conversation_id": f"group_{g_row['id']}",
                "type": "group",
                "target_id": g_row["id"],
                "name": g_row["name"],
                "avatar": g_row["avatar"],
                "description": g_row["description"],
                "is_online": True,
                "last_message": last_preview,
                "last_time": last_time,
                "unread_count": 0
            })

    # Sort conversations by latest message time
    conversations.sort(key=lambda c: c["last_time"] or "", reverse=True)

    return jsonify({"conversations": conversations})
