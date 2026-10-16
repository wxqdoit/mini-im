from flask import Blueprint, request, jsonify, g
from db import get_db
from auth import hash_password, verify_password, generate_token, token_required
from redis_client import get_user_status

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

@auth_bp.route("/register", methods=["POST"])
def register():
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")
    nickname = data.get("nickname", "").strip() or username
    avatar = data.get("avatar", "")
    bio = data.get("bio", "Hello, I am using Mini IM!")

    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400

    if len(username) < 3 or len(password) < 6:
        return jsonify({"error": "Username >= 3 chars, password >= 6 chars"}), 400

    with get_db() as cur:
        cur.execute("SELECT id FROM users WHERE username = %s", (username,))
        if cur.fetchone():
            return jsonify({"error": "Username already taken"}), 409

        pwd_hash = hash_password(password)
        cur.execute(
            """
            INSERT INTO users (username, password_hash, nickname, avatar, bio, status)
            VALUES (%s, %s, %s, %s, %s, 'offline')
            RETURNING id, username, nickname, avatar, bio, status, created_at;
            """,
            (username, pwd_hash, nickname, avatar, bio)
        )
        user = cur.fetchone()

    token = generate_token(user["id"])
    return jsonify({
        "message": "Registration successful",
        "token": token,
        "user": user
    }), 201

@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")

    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400

    with get_db() as cur:
        cur.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cur.fetchone()

    if not user or not verify_password(password, user["password_hash"]):
        return jsonify({"error": "Invalid username or password"}), 401

    token = generate_token(user["id"])
    user_info = {
        "id": user["id"],
        "username": user["username"],
        "nickname": user["nickname"],
        "avatar": user["avatar"],
        "bio": user["bio"],
        "status": get_user_status(user["id"])
    }

    return jsonify({
        "message": "Login successful",
        "token": token,
        "user": user_info
    })

@auth_bp.route("/logout", methods=["POST"])
@token_required
def logout():
    user_id = g.current_user["id"]
    from websocket_server import close_user_connections
    close_user_connections(user_id)
    return jsonify({"message": "Logged out successfully"})

@auth_bp.route("/me", methods=["GET"])
@token_required
def get_current_user():
    user = g.current_user
    user["status"] = get_user_status(user["id"])
    return jsonify({"user": user})
