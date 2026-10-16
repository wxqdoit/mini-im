import datetime
import jwt
from functools import wraps
from flask import request, jsonify, g
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config
from db import get_db

def hash_password(password: str) -> str:
    # Use pbkdf2:sha256 which is universal across all Python and SSL builds
    return generate_password_hash(password, method="pbkdf2:sha256")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return check_password_hash(hashed_password, plain_password)

def generate_token(user_id: int) -> str:
    payload = {
        "user_id": user_id,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=Config.JWT_EXPIRATION_HOURS),
        "iat": datetime.datetime.utcnow()
    }
    return jwt.encode(payload, Config.SECRET_KEY, algorithm="HS256")

def decode_token(token: str):
    try:
        payload = jwt.decode(token, Config.SECRET_KEY, algorithms=["HS256"])
        user_id = payload.get("user_id")
        if not user_id:
            return None
        with get_db() as cur:
            cur.execute("SELECT id, username, nickname, avatar, bio, status FROM users WHERE id = %s", (user_id,))
            user = cur.fetchone()
            return user
    except Exception as e:
        return None

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return jsonify({"error": "Authorization token required"}), 401
        
        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return jsonify({"error": "Invalid token header format"}), 401
        
        token = parts[1]
        user = decode_token(token)
        if not user:
            return jsonify({"error": "Invalid or expired token"}), 401
        
        g.current_user = user
        return f(*args, **kwargs)
    return decorated
