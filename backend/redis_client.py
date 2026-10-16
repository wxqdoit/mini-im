import redis
import json
import time
from config import Config

_redis_pool = None

def get_redis_client():
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = redis.ConnectionPool(
            host=Config.REDIS_HOST,
            port=Config.REDIS_PORT,
            password=Config.REDIS_PASSWORD,
            decode_responses=True,
            max_connections=1000
        )
    return redis.Redis(connection_pool=_redis_pool)

ONLINE_USERS_KEY = "mini_im:online_users"
USER_STATUS_KEY = "mini_im:user_status:"
USER_HEARTBEAT_PREFIX = "mini_im:heartbeat:"
HEARTBEAT_TTL = 45  # Heartbeat expires after 45s (clients ping every 15-20s)

USER_CACHE_PREFIX = "mini_im:cache:user:"
GROUP_MEMBERS_CACHE_PREFIX = "mini_im:cache:group_members:"

def reset_all_online_presence():
    """
    Called on backend startup to clean up dead sessions from past runs.
    Uses non-blocking SCAN instead of KEYS to avoid blocking Redis event loop.
    """
    try:
        r = get_redis_client()
        r.delete(ONLINE_USERS_KEY)
        
        # Non-blocking scan for heartbeats and statuses
        pipe = r.pipeline()
        for k in r.scan_iter(f"{USER_HEARTBEAT_PREFIX}*"):
            pipe.delete(k)
        for k in r.scan_iter(f"{USER_STATUS_KEY}*"):
            pipe.delete(k)
        for k in r.scan_iter(f"{USER_CACHE_PREFIX}*"):
            pipe.delete(k)
        for k in r.scan_iter(f"{GROUP_MEMBERS_CACHE_PREFIX}*"):
            pipe.delete(k)
        pipe.execute()
        print("Redis online presence & caches reset successfully on startup.")
    except Exception as e:
        print(f"Warning resetting Redis online presence: {e}")

    try:
        from db import get_db
        with get_db() as cur:
            cur.execute("UPDATE users SET status = 'offline';")
        print("PostgreSQL all users reset to 'offline' on startup.")
    except Exception as e:
        print(f"Warning resetting DB users status to offline: {e}")

# ==========================================
# User Profile Cache (Eliminates Token Auth DB reads)
# ==========================================
def cache_user_profile(user_dict: dict, ttl: int = 900):
    if not user_dict or not user_dict.get("id"):
        return
    try:
        r = get_redis_client()
        key = f"{USER_CACHE_PREFIX}{user_dict['id']}"
        r.set(key, json.dumps(user_dict, default=str), ex=ttl)
    except Exception as e:
        print(f"Warning caching user profile: {e}")

def get_cached_user_profile(user_id: int):
    try:
        r = get_redis_client()
        raw = r.get(f"{USER_CACHE_PREFIX}{user_id}")
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return None

def invalidate_user_cache(user_id: int):
    try:
        r = get_redis_client()
        r.delete(f"{USER_CACHE_PREFIX}{user_id}")
    except Exception:
        pass

# ==========================================
# Group Members Cache (O(1) Fan-out & Validation)
# ==========================================
def cache_group_members(group_id: int, member_ids: list, ttl: int = 3600):
    try:
        r = get_redis_client()
        key = f"{GROUP_MEMBERS_CACHE_PREFIX}{group_id}"
        pipe = r.pipeline()
        pipe.delete(key)
        if member_ids:
            pipe.sadd(key, *[str(uid) for uid in member_ids])
            pipe.expire(key, ttl)
        pipe.execute()
    except Exception as e:
        print(f"Warning caching group members: {e}")

def get_cached_group_members(group_id: int):
    try:
        r = get_redis_client()
        key = f"{GROUP_MEMBERS_CACHE_PREFIX}{group_id}"
        if r.exists(key):
            return {int(uid) for uid in r.smembers(key)}
    except Exception:
        pass
    return None

def add_group_member_cache(group_id: int, user_id: int):
    try:
        r = get_redis_client()
        key = f"{GROUP_MEMBERS_CACHE_PREFIX}{group_id}"
        if r.exists(key):
            r.sadd(key, str(user_id))
    except Exception:
        pass

def remove_group_member_cache(group_id: int, user_id: int):
    try:
        r = get_redis_client()
        key = f"{GROUP_MEMBERS_CACHE_PREFIX}{group_id}"
        if r.exists(key):
            r.srem(key, str(user_id))
    except Exception:
        pass

def invalidate_group_members_cache(group_id: int):
    try:
        r = get_redis_client()
        r.delete(f"{GROUP_MEMBERS_CACHE_PREFIX}{group_id}")
    except Exception:
        pass

# ==========================================
# Presence & Heartbeat
# ==========================================
def set_user_online(user_id, status="online"):
    r = get_redis_client()
    uid_str = str(user_id)
    pipe = r.pipeline()
    pipe.sadd(ONLINE_USERS_KEY, uid_str)
    pipe.set(f"{USER_STATUS_KEY}{uid_str}", status)
    pipe.set(f"{USER_HEARTBEAT_PREFIX}{uid_str}", "1", ex=HEARTBEAT_TTL)
    pipe.execute()

def refresh_user_heartbeat(user_id):
    r = get_redis_client()
    uid_str = str(user_id)
    pipe = r.pipeline()
    pipe.sadd(ONLINE_USERS_KEY, uid_str)
    pipe.set(f"{USER_HEARTBEAT_PREFIX}{uid_str}", "1", ex=HEARTBEAT_TTL)
    pipe.execute()

def set_user_offline(user_id):
    r = get_redis_client()
    uid_str = str(user_id)
    pipe = r.pipeline()
    pipe.srem(ONLINE_USERS_KEY, uid_str)
    pipe.delete(f"{USER_HEARTBEAT_PREFIX}{uid_str}")
    pipe.set(f"{USER_STATUS_KEY}{uid_str}", "offline")
    pipe.execute()

def is_user_online(user_id):
    r = get_redis_client()
    uid_str = str(user_id)
    has_heartbeat = r.exists(f"{USER_HEARTBEAT_PREFIX}{uid_str}")
    if has_heartbeat:
        return True
    
    # Clean up stale record
    if r.sismember(ONLINE_USERS_KEY, uid_str):
        r.srem(ONLINE_USERS_KEY, uid_str)
    r.set(f"{USER_STATUS_KEY}{uid_str}", "offline")
    return False

def get_user_status(user_id):
    if not is_user_online(user_id):
        return "offline"
    r = get_redis_client()
    uid_str = str(user_id)
    status = r.get(f"{USER_STATUS_KEY}{uid_str}")
    return status or "online"

def get_users_presence_batch(user_ids: list) -> dict:
    """
    High-performance batched pipeline to retrieve is_online and status for multiple users
    in a single Redis round-trip.
    """
    if not user_ids:
        return {}
    r = get_redis_client()
    pipe = r.pipeline()
    for uid in user_ids:
        uid_str = str(uid)
        pipe.exists(f"{USER_HEARTBEAT_PREFIX}{uid_str}")
        pipe.get(f"{USER_STATUS_KEY}{uid_str}")
    results = pipe.execute()
    
    presence_map = {}
    for idx, uid in enumerate(user_ids):
        has_heartbeat = bool(results[idx * 2])
        raw_status = results[idx * 2 + 1]
        presence_map[uid] = {
            "is_online": has_heartbeat,
            "status": raw_status if (has_heartbeat and raw_status) else "offline"
        }
    return presence_map

def publish_event(channel, event_data):
    """
    Publish real-time event to Redis channel with datetime serialization
    """
    r = get_redis_client()
    payload = json.dumps(event_data, default=str)
    r.publish(channel, payload)
