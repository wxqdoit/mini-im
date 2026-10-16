from flask import Blueprint, request, jsonify, g
from db import get_db
from auth import token_required
from redis_client import set_user_online, get_user_status, is_user_online, publish_event

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

    for u in users:
        u["is_online"] = is_user_online(u["id"])
        u["status"] = get_user_status(u["id"])

    return jsonify({"users": users})
