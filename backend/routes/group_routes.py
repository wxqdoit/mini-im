from flask import Blueprint, request, jsonify, g
from db import get_db
from auth import token_required
from redis_client import is_user_online, get_user_status, publish_event

group_bp = Blueprint("groups", __name__, url_prefix="/api/groups")

@group_bp.route("", methods=["POST"])
@token_required
def create_group():
    user_id = g.current_user["id"]
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    description = data.get("description", "").strip()
    avatar = data.get("avatar", "")

    if not name:
        return jsonify({"error": "Group name is required"}), 400

    with get_db() as cur:
        # Create group
        cur.execute("""
            INSERT INTO groups (name, description, avatar, owner_id)
            VALUES (%s, %s, %s, %s)
            RETURNING id, name, description, avatar, owner_id, created_at;
        """, (name, description, avatar, user_id))
        new_group = cur.fetchone()
        group_id = new_group["id"]

        # Add creator as owner member
        cur.execute("""
            INSERT INTO group_members (group_id, user_id, role)
            VALUES (%s, %s, 'owner');
        """, (group_id, user_id))

    return jsonify({
        "message": "Group created successfully",
        "group": new_group
    }), 201

@group_bp.route("", methods=["GET"])
@token_required
def get_my_groups():
    user_id = g.current_user["id"]
    with get_db() as cur:
        sql = """
        SELECT g.id, g.name, g.avatar, g.description, g.owner_id, g.created_at,
               gm.role,
               (SELECT COUNT(*) FROM group_members WHERE group_id = g.id) as member_count
        FROM groups g
        JOIN group_members gm ON g.id = gm.group_id
        WHERE gm.user_id = %s
        ORDER BY g.created_at DESC;
        """
        cur.execute(sql, (user_id,))
        groups = cur.fetchall()

    return jsonify({"groups": groups})

@group_bp.route("/search", methods=["GET"])
@token_required
def search_groups():
    query = request.args.get("q", "").strip()
    user_id = g.current_user["id"]
    
    if not query:
        return jsonify({"groups": []})

    with get_db() as cur:
        sql = """
        SELECT g.id, g.name, g.avatar, g.description, g.owner_id, g.created_at,
               (SELECT COUNT(*) FROM group_members WHERE group_id = g.id) as member_count,
               EXISTS(SELECT 1 FROM group_members WHERE group_id = g.id AND user_id = %s) as is_member
        FROM groups g
        WHERE g.name ILIKE %s OR g.description ILIKE %s
        LIMIT 20;
        """
        pattern = f"%{query}%"
        cur.execute(sql, (user_id, pattern, pattern))
        groups = cur.fetchall()

    return jsonify({"groups": groups})

@group_bp.route("/<int:group_id>", methods=["GET"])
@token_required
def get_group_detail(group_id):
    user_id = g.current_user["id"]
    with get_db() as cur:
        cur.execute("""
            SELECT g.id, g.name, g.avatar, g.description, g.owner_id, g.created_at,
                   (SELECT COUNT(*) FROM group_members WHERE group_id = g.id) as member_count,
                   EXISTS(SELECT 1 FROM group_members WHERE group_id = g.id AND user_id = %s) as is_member,
                   (SELECT role FROM group_members WHERE group_id = g.id AND user_id = %s) as my_role
            FROM groups g
            WHERE g.id = %s;
        """, (user_id, user_id, group_id))
        group = cur.fetchone()

        if not group:
            return jsonify({"error": "Group not found"}), 404

    return jsonify({"group": group})

@group_bp.route("/<int:group_id>/join", methods=["POST"])
@token_required
def join_group(group_id):
    user_id = g.current_user["id"]
    with get_db() as cur:
        cur.execute("SELECT id, name FROM groups WHERE id = %s", (group_id,))
        group = cur.fetchone()
        if not group:
            return jsonify({"error": "Group not found"}), 404

        cur.execute("SELECT 1 FROM group_members WHERE group_id = %s AND user_id = %s", (group_id, user_id))
        if cur.fetchone():
            return jsonify({"error": "Already a member of this group"}), 400

        cur.execute("""
            INSERT INTO group_members (group_id, user_id, role)
            VALUES (%s, %s, 'member');
        """, (group_id, user_id))

    # Notify group channel
    publish_event(f"mini_im:group:{group_id}", {
        "event": "member_joined",
        "data": {
            "group_id": group_id,
            "user": g.current_user
        }
    })

    group_name = group["name"]
    return jsonify({"message": f"Successfully joined {group_name}"})

@group_bp.route("/<int:group_id>/members", methods=["GET"])
@token_required
def get_group_members(group_id):
    with get_db() as cur:
        sql = """
        SELECT gm.id as membership_id, gm.role, gm.joined_at,
               u.id as user_id, u.username, u.nickname, u.avatar, u.bio
        FROM group_members gm
        JOIN users u ON gm.user_id = u.id
        WHERE gm.group_id = %s
        ORDER BY 
            CASE gm.role 
                WHEN 'owner' THEN 1 
                WHEN 'admin' THEN 2 
                ELSE 3 
            END,
            u.nickname ASC;
        """
        cur.execute(sql, (group_id,))
        members = cur.fetchall()

    for m in members:
        m["is_online"] = is_user_online(m["user_id"])
        m["status"] = get_user_status(m["user_id"])

    return jsonify({"members": members})

@group_bp.route("/<int:group_id>/invite", methods=["POST"])
@token_required
def invite_to_group(group_id):
    inviter_id = g.current_user["id"]
    data = request.get_json() or {}
    user_ids = data.get("user_ids", [])  # list of user IDs

    if not user_ids:
        return jsonify({"error": "user_ids list is required"}), 400

    added_users = []
    with get_db() as cur:
        cur.execute("SELECT id FROM groups WHERE id = %s", (group_id,))
        if not cur.fetchone():
            return jsonify({"error": "Group not found"}), 404

        for uid in user_ids:
            cur.execute("""
                INSERT INTO group_members (group_id, user_id, role)
                VALUES (%s, %s, 'member')
                ON CONFLICT (group_id, user_id) DO NOTHING
                RETURNING user_id;
            """, (group_id, uid))
            res = cur.fetchone()
            if res:
                added_users.append(uid)

    # Publish notification to group
    if added_users:
        publish_event(f"mini_im:group:{group_id}", {
            "event": "members_invited",
            "data": {
                "group_id": group_id,
                "added_user_ids": added_users,
                "inviter": g.current_user
            }
        })

    return jsonify({
        "message": f"Added {len(added_users)} member(s)",
        "added_user_ids": added_users
    })

@group_bp.route("/<int:group_id>/leave", methods=["POST"])
@token_required
def leave_group(group_id):
    user_id = g.current_user["id"]
    with get_db() as cur:
        cur.execute("SELECT owner_id FROM groups WHERE id = %s", (group_id,))
        group = cur.fetchone()
        if not group:
            return jsonify({"error": "Group not found"}), 404

        is_owner = (group["owner_id"] == user_id)

        # Remove from members
        cur.execute("DELETE FROM group_members WHERE group_id = %s AND user_id = %s", (group_id, user_id))

        if is_owner:
            # Pick next member to be owner, or delete group if empty
            cur.execute("SELECT user_id FROM group_members WHERE group_id = %s ORDER BY joined_at ASC LIMIT 1", (group_id,))
            next_owner = cur.fetchone()
            if next_owner:
                cur.execute("UPDATE groups SET owner_id = %s WHERE id = %s", (next_owner["user_id"], group_id))
                cur.execute("UPDATE group_members SET role = 'owner' WHERE group_id = %s AND user_id = %s", (group_id, next_owner["user_id"]))
            else:
                cur.execute("DELETE FROM groups WHERE id = %s", (group_id,))

    publish_event(f"mini_im:group:{group_id}", {
        "event": "member_left",
        "data": {
            "group_id": group_id,
            "user_id": user_id
        }
    })

    return jsonify({"message": "Left group successfully"})

@group_bp.route("/<int:group_id>", methods=["DELETE"])
@token_required
def disband_group(group_id):
    user_id = g.current_user["id"]
    with get_db() as cur:
        cur.execute("SELECT owner_id FROM groups WHERE id = %s", (group_id,))
        group = cur.fetchone()
        if not group:
            return jsonify({"error": "Group not found"}), 404

        if group["owner_id"] != user_id:
            return jsonify({"error": "Only group owner can disband the group"}), 403

        cur.execute("DELETE FROM groups WHERE id = %s", (group_id,))

    publish_event(f"mini_im:group:{group_id}", {
        "event": "group_disbanded",
        "data": {"group_id": group_id}
    })

    return jsonify({"message": "Group disbanded successfully"})
