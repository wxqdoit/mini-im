import time
import uuid
from functools import wraps
from flask import request, jsonify, g
from redis_client import get_redis_client

def check_rate_limit(key: str, limit: int, window_seconds: int) -> bool:
    """
    Sliding window rate limiter using Redis sorted sets (ZSET).
    Returns True if request is allowed, False if exceeded.
    """
    try:
        r = get_redis_client()
        now = time.time()
        clear_before = now - window_seconds
        member = f"{now:.6f}:{uuid.uuid4().hex[:6]}"
        
        pipe = r.pipeline()
        pipe.zremrangebyscore(key, 0, clear_before)
        pipe.zcard(key)
        pipe.zadd(key, {member: now})
        pipe.expire(key, window_seconds + 5)
        res = pipe.execute()
        
        current_count = res[1]
        return current_count < limit
    except Exception as e:
        # Fail-open if Redis temporary glitch to avoid denying service
        print(f"Rate limiter warning: {e}")
        return True

def rate_limit(key_prefix: str, limit: int, window_seconds: int, by_user: bool = False):
    """
    Decorator for Flask routes to throttle requests.
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if by_user and hasattr(g, "current_user") and g.current_user:
                identifier = f"user:{g.current_user['id']}"
            else:
                identifier = f"ip:{request.remote_addr or 'unknown'}"

            redis_key = f"mini_im:ratelimit:{key_prefix}:{identifier}"
            allowed = check_rate_limit(redis_key, limit, window_seconds)
            
            if not allowed:
                return jsonify({
                    "error": "Too many requests. Please try again later.",
                    "retry_after": window_seconds
                }), 429

            return f(*args, **kwargs)
        return decorated
    return decorator
