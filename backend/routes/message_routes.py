import datetime
from flask import Blueprint, request, jsonify, g
from db import get_db
from auth import token_required
from config import Config
from kafka_service import send_to_kafka
from redis_client import is_user_online, get_user_status

message_bp = Blueprint("messages", __name__, url_prefix="/api/messages")

@message_bp.route("/send", methods=["POST"])
@token_required
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

    if msg_type == "text" and not content:
        return jsonify({"error": "Content cannot be empty"}), 400

    if msg_type in ["image", "file"] and not media_url:
        return jsonify({"error": "media_url required for media message"}), 400

    message_payload = {
        "event_type": "chat_message",
        "conversation_type": conv_type,
        "sender_id": sender_id,
        "recipient_id": int(recipient_id),
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
           m.is_read, m.is_encrypted, m.iv, m.ephemeral_key, m.encrypted_key_bundle, m.created_at,
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

    with get_db() as cur:
        cur.execute(sql, tuple(params))
        messages = cur.fetchall()

    # Reverse so they are chronological
    messages.reverse()

    return jsonify({"messages": messages})

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

        for f in friends:
            # Get latest message
            cur.execute("""
                SELECT id, msg_type, content, media_url, created_at, sender_id, is_encrypted
                FROM messages
                WHERE conversation_type = 'direct'
                  AND ((sender_id = %s AND recipient_id = %s) OR (sender_id = %s AND recipient_id = %s))
                ORDER BY id DESC LIMIT 1;
            """, (user_id, f["id"], f["id"], user_id))
            last_msg = cur.fetchone()

            # Count unread messages
            cur.execute("""
                SELECT COUNT(*) as unread
                FROM messages
                WHERE conversation_type = 'direct'
                  AND sender_id = %s AND recipient_id = %s AND is_read = FALSE;
            """, (f["id"], user_id))
            unread_res = cur.fetchone()

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

            conversations.append({
                "conversation_id": f"direct_{f['id']}",
                "type": "direct",
                "target_id": f["id"],
                "name": f["nickname"],
                "avatar": f["avatar"],
                "bio": f["bio"],
                "is_online": is_user_online(f["id"]),
                "status": get_user_status(f["id"]),
                "last_message": last_preview,
                "last_time": last_time,
                "unread_count": unread_res["unread"] if unread_res else 0
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

    # Sort conversations by last message time (most recent first)
    conversations.sort(key=lambda c: c["last_time"] or "", reverse=True)

    return jsonify({"conversations": conversations})
