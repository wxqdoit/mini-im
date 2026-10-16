from flask import Blueprint, request, jsonify, g
from db import get_db
from auth import token_required
from redis_client import set_user_online, get_users_presence_batch, publish_event, cache_user_profile
from rate_limiter import rate_limit

user_bp = Blueprint("users", __name__, url_prefix="/api/users")

@user_bp.route("/profile", methods=["PUT"])
@token_required
def update_profile():
    data = request.get_json() or {}
    user_id = g.current_user["id"]
    
    nickname = data.get("nickname")
    bio = data.get("bio")
    avatar = data.get("avatar")
    status = data.get("status")

    update_fields = []
    params = []

    if nickname is not None:
        update_fields.append("nickname = %s")
        params.append(nickname.strip())
    if bio is not None:
        update_fields.append("bio = %s")
        params.append(bio.strip())
    if avatar is not None:
        update_fields.append("avatar = %s")
        params.append(avatar.strip())
    if status is not None:
        update_fields.append("status = %s")
        params.append(status.strip())
        set_user_online(user_id, status.strip())

    if not update_fields:
        return jsonify({"error": "No fields to update"}), 400

    update_fields.append("updated_at = CURRENT_TIMESTAMP")
    params.append(user_id)

    sql = f"UPDATE users SET {', '.join(update_fields)} WHERE id = %s RETURNING id, username, nickname, avatar, bio, status, updated_at;"
    
    with get_db() as cur:
        cur.execute(sql, tuple(params))
        updated_user = dict(cur.fetchone())

    if updated_user.get("updated_at"):
        updated_user["updated_at"] = updated_user["updated_at"].isoformat()

    # Synchronize Redis cache immediately
    cache_user_profile(updated_user)

    # Broadcast status / profile update
    publish_event("mini_im:user_profile_updated", {"user": updated_user})
    if status is not None:
        publish_event("mini_im:presence", {
            "event": "user_status_changed",
            "data": {
                "user_id": user_id,
                "status": status.strip(),
                "is_online": True
            }
        })

    return jsonify({
        "message": "Profile updated successfully",
        "user": updated_user
    })

@user_bp.route("/search", methods=["GET"])
@token_required
@rate_limit("search_users", limit=30, window_seconds=60, by_user=True)
def search_users():
    query = request.args.get("q", "").strip()
    current_user_id = g.current_user["id"]
    
    if not query:
        return jsonify({"users": []})

    with get_db() as cur:
        sql = """
        SELECT id, username, nickname, avatar, bio,
            EXISTS(SELECT 1 FROM friendships WHERE user_id = %s AND friend_id = users.id) as is_friend,
            EXISTS(SELECT 1 FROM friend_requests WHERE sender_id = %s AND receiver_id = users.id AND status = 'pending') as request_sent
        FROM users
        WHERE id != %s AND (username ILIKE %s OR nickname ILIKE %s)
        LIMIT 20;
        """
        search_pattern = f"%{query}%"
        cur.execute(sql, (current_user_id, current_user_id, current_user_id, search_pattern, search_pattern))
        users = [dict(u) for u in cur.fetchall()]

    # Batch presence check
    user_ids = [u["id"] for u in users]
    presence_map = get_users_presence_batch(user_ids)

    for u in users:
        p = presence_map.get(u["id"], {"is_online": False, "status": "offline"})
        u["is_online"] = p["is_online"]
        u["status"] = p["status"]

    return jsonify({"users": users})

@user_bp.route("/device-token", methods=["POST"])
@token_required
def register_device_token():
    user_id = g.current_user["id"]
    data = request.get_json() or {}
    platform = data.get("platform", "web").strip().lower()
    device_token = data.get("device_token", "").strip()

    if not device_token:
        return jsonify({"error": "device_token is required"}), 400

    if platform not in ["ios", "android", "web"]:
        platform = "web"

    with get_db() as cur:
        cur.execute("""
            INSERT INTO user_devices (user_id, platform, device_token, is_active, updated_at)
            VALUES (%s, %s, %s, TRUE, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id, device_token)
            DO UPDATE SET 
                is_active = TRUE,
                platform = EXCLUDED.platform,
                updated_at = CURRENT_TIMESTAMP;
        """, (user_id, platform, device_token))

    return jsonify({"message": "Device token registered successfully", "platform": platform})

@user_bp.route("/device-token", methods=["DELETE"])
@token_required
def unregister_device_token():
    user_id = g.current_user["id"]
    data = request.get_json() or {}
    device_token = data.get("device_token")

    with get_db() as cur:
        if device_token:
            cur.execute("""
                UPDATE user_devices SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = %s AND device_token = %s;
            """, (user_id, device_token))
        else:
            cur.execute("""
                UPDATE user_devices SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = %s;
            """, (user_id,))

    return jsonify({"message": "Device token(s) deactivated successfully"})

@user_bp.route("/push-notifications", methods=["GET"])
@token_required
def get_my_push_notifications():
    from push_service import get_user_push_logs
    user_id = g.current_user["id"]
    limit = int(request.args.get("limit", 20))
    logs = get_user_push_logs(user_id=user_id, limit=limit)
    return jsonify({"notifications": logs})
