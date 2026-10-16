import datetime
import jwt
from functools import wraps
from flask import request, jsonify, g
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config
from db import get_db
from redis_client import get_cached_user_profile, cache_user_profile

def hash_password(password: str) -> str:
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

        # 1. Fast path: check Redis cache
        cached_user = get_cached_user_profile(user_id)
        if cached_user:
            return cached_user

        # 2. Slow path: fetch from DB and populate cache
        with get_db() as cur:
            cur.execute("SELECT id, username, nickname, avatar, bio, status FROM users WHERE id = %s", (user_id,))
            user = cur.fetchone()
            if user:
                user_dict = dict(user)
                cache_user_profile(user_dict)
                return user_dict
            return None
    except Exception:
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
