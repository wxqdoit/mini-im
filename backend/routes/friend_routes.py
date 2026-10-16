from flask import Blueprint, request, jsonify, g
from db import get_db
from auth import token_required
from redis_client import is_user_online, get_user_status, publish_event

friend_bp = Blueprint("friends", __name__, url_prefix="/api/friends")

@friend_bp.route("", methods=["GET"])
@token_required
def get_friends():
    user_id = g.current_user["id"]
    with get_db() as cur:
        sql = """
        SELECT u.id, u.username, u.nickname, u.avatar, u.bio, f.created_at as friendship_date
        FROM friendships f
        JOIN users u ON f.friend_id = u.id
        WHERE f.user_id = %s
        ORDER BY u.nickname ASC;
        """
        cur.execute(sql, (user_id,))
        friends = cur.fetchall()

    for f in friends:
        f["is_online"] = is_user_online(f["id"])
        f["status"] = get_user_status(f["id"])

    return jsonify({"friends": friends})

@friend_bp.route("/request", methods=["POST"])
@token_required
def send_friend_request():
    sender_id = g.current_user["id"]
    data = request.get_json() or {}
    receiver_id = data.get("receiver_id")
    message = data.get("message", "Let's be friends!").strip()

    if not receiver_id:
        return jsonify({"error": "receiver_id is required"}), 400

    if sender_id == receiver_id:
        return jsonify({"error": "Cannot add yourself as friend"}), 400

    with get_db() as cur:
        # Check if already friends
        cur.execute("SELECT 1 FROM friendships WHERE user_id = %s AND friend_id = %s", (sender_id, receiver_id))
        if cur.fetchone():
            return jsonify({"error": "You are already friends"}), 400

        # Check existing pending request
        cur.execute("""
            SELECT id, status FROM friend_requests 
            WHERE sender_id = %s AND receiver_id = %s AND status = 'pending'
        """, (sender_id, receiver_id))
        if cur.fetchone():
            return jsonify({"error": "Friend request already sent"}), 400

        # Insert friend request
        cur.execute("""
            INSERT INTO friend_requests (sender_id, receiver_id, status, message)
            VALUES (%s, %s, 'pending', %s)
            RETURNING id, created_at;
        """, (sender_id, receiver_id, message))
        req_row = cur.fetchone()

    # Notify receiver via Redis
    publish_event(f"mini_im:user:{receiver_id}", {
        "event": "friend_request_received",
        "data": {
            "request_id": req_row["id"],
            "sender": g.current_user,
            "message": message
        }
    })

    return jsonify({
        "message": "Friend request sent",
        "request_id": req_row["id"]
    }), 201

@friend_bp.route("/requests", methods=["GET"])
@token_required
def get_friend_requests():
    user_id = g.current_user["id"]
    with get_db() as cur:
        # Received requests
        cur.execute("""
            SELECT r.id, r.message, r.status, r.created_at,
                   u.id as user_id, u.username, u.nickname, u.avatar, u.bio
            FROM friend_requests r
            JOIN users u ON r.sender_id = u.id
            WHERE r.receiver_id = %s AND r.status = 'pending'
            ORDER BY r.created_at DESC;
        """, (user_id,))
        received = cur.fetchall()

        # Sent requests
        cur.execute("""
            SELECT r.id, r.message, r.status, r.created_at,
                   u.id as user_id, u.username, u.nickname, u.avatar, u.bio
            FROM friend_requests r
            JOIN users u ON r.receiver_id = u.id
            WHERE r.sender_id = %s AND r.status = 'pending'
            ORDER BY r.created_at DESC;
        """, (user_id,))
        sent = cur.fetchall()

    return jsonify({
        "received": received,
        "sent": sent
    })

@friend_bp.route("/requests/<int:req_id>/respond", methods=["POST"])
@token_required
def respond_friend_request(req_id):
    user_id = g.current_user["id"]
    data = request.get_json() or {}
    action = data.get("action")  # 'accept' or 'reject'

    if action not in ["accept", "reject"]:
        return jsonify({"error": "Action must be 'accept' or 'reject'"}), 400

    with get_db() as cur:
        cur.execute("""
            SELECT id, sender_id, receiver_id, status 
            FROM friend_requests 
            WHERE id = %s AND receiver_id = %s;
        """, (req_id, user_id))
        req_item = cur.fetchone()

        if not req_item:
            return jsonify({"error": "Request not found"}), 404

        if req_item["status"] != "pending":
            return jsonify({"error": f"Request already {req_item['status']}"}), 400

        sender_id = req_item["sender_id"]

        if action == "accept":
            # Update request
            cur.execute("UPDATE friend_requests SET status = 'accepted', updated_at = CURRENT_TIMESTAMP WHERE id = %s;", (req_id,))
            
            # Insert bidirectional friendship
            cur.execute("""
                INSERT INTO friendships (user_id, friend_id)
                VALUES (%s, %s)
                ON CONFLICT (user_id, friend_id) DO NOTHING;
            """, (user_id, sender_id))
            
            cur.execute("""
                INSERT INTO friendships (user_id, friend_id)
                VALUES (%s, %s)
                ON CONFLICT (user_id, friend_id) DO NOTHING;
            """, (sender_id, user_id))

            # Notify sender
            publish_event(f"mini_im:user:{sender_id}", {
                "event": "friend_request_accepted",
                "data": {
                    "friend": g.current_user
                }
            })
        else:
            cur.execute("UPDATE friend_requests SET status = 'rejected', updated_at = CURRENT_TIMESTAMP WHERE id = %s;", (req_id,))

    return jsonify({"message": f"Request {action}ed successfully"})

@friend_bp.route("/<int:friend_id>", methods=["DELETE"])
@token_required
def delete_friend(friend_id):
    user_id = g.current_user["id"]
    with get_db() as cur:
        cur.execute("""
            DELETE FROM friendships 
            WHERE (user_id = %s AND friend_id = %s)
               OR (user_id = %s AND friend_id = %s);
        """, (user_id, friend_id, friend_id, user_id))

    # Notify both sides
    publish_event(f"mini_im:user:{friend_id}", {
        "event": "friend_deleted",
        "data": {"user_id": user_id}
    })
    publish_event(f"mini_im:user:{user_id}", {
        "event": "friend_deleted",
        "data": {"user_id": friend_id}
    })

    return jsonify({"message": "Friend removed successfully"})
