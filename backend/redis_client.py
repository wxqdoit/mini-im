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
            decode_responses=True
        )
    return redis.Redis(connection_pool=_redis_pool)

ONLINE_USERS_KEY = "mini_im:online_users"
USER_STATUS_KEY = "mini_im:user_status:"
USER_HEARTBEAT_PREFIX = "mini_im:heartbeat:"
HEARTBEAT_TTL = 45  # Heartbeat expires after 45s (clients ping every 15-20s)

def reset_all_online_presence():
    """
    Called on backend startup to clean up dead sessions from past runs.
    Wipes Redis online sets, heartbeats, and sets PostgreSQL user status to offline.
    """
    try:
        r = get_redis_client()
        r.delete(ONLINE_USERS_KEY)
        heartbeat_keys = r.keys(f"{USER_HEARTBEAT_PREFIX}*")
        if heartbeat_keys:
            r.delete(*heartbeat_keys)
        status_keys = r.keys(f"{USER_STATUS_KEY}*")
        if status_keys:
            r.delete(*status_keys)
        print("Redis online presence reset successfully on startup.")
    except Exception as e:
        print(f"Warning resetting Redis online presence: {e}")

    try:
        from db import get_db
        with get_db() as cur:
            cur.execute("UPDATE users SET status = 'offline';")
        print("PostgreSQL all users reset to 'offline' on startup.")
    except Exception as e:
        print(f"Warning resetting DB users status to offline: {e}")

def set_user_online(user_id, status="online"):
    r = get_redis_client()
    uid_str = str(user_id)
    r.sadd(ONLINE_USERS_KEY, uid_str)
    r.set(f"{USER_STATUS_KEY}{uid_str}", status)
    r.set(f"{USER_HEARTBEAT_PREFIX}{uid_str}", "1", ex=HEARTBEAT_TTL)

def refresh_user_heartbeat(user_id):
    r = get_redis_client()
    uid_str = str(user_id)
    r.sadd(ONLINE_USERS_KEY, uid_str)
    r.set(f"{USER_HEARTBEAT_PREFIX}{uid_str}", "1", ex=HEARTBEAT_TTL)

def set_user_offline(user_id):
    r = get_redis_client()
    uid_str = str(user_id)
    r.srem(ONLINE_USERS_KEY, uid_str)
    r.delete(f"{USER_HEARTBEAT_PREFIX}{uid_str}")
    r.set(f"{USER_STATUS_KEY}{uid_str}", "offline")

def is_user_online(user_id):
    r = get_redis_client()
    uid_str = str(user_id)
    # Check if heartbeat key exists
    has_heartbeat = r.exists(f"{USER_HEARTBEAT_PREFIX}{uid_str}")
    if has_heartbeat:
        return True
    
    # If no heartbeat, ensure removed from online set and marked offline
    if r.sismember(ONLINE_USERS_KEY, uid_str):
        r.srem(ONLINE_USERS_KEY, uid_str)
    r.set(f"{USER_STATUS_KEY}{uid_str}", "offline")
    return False

def get_online_user_ids():
    r = get_redis_client()
    raw_ids = list(r.smembers(ONLINE_USERS_KEY))
    active_ids = []
    for uid in raw_ids:
        if is_user_online(uid):
            active_ids.append(uid)
    return active_ids

def get_user_status(user_id):
    if not is_user_online(user_id):
        return "offline"
    r = get_redis_client()
    uid_str = str(user_id)
    status = r.get(f"{USER_STATUS_KEY}{uid_str}")
    return status or "online"

def publish_event(channel, event_data):
    """
    Publish real-time event to Redis channel with datetime serialization
    """
    r = get_redis_client()
    payload = json.dumps(event_data, default=str)
    r.publish(channel, payload)
