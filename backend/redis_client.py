import redis
from redis.cluster import RedisCluster, ClusterNode
import json
import time
from config import Config

_redis_pool = None
_redis_cluster_client = None

def get_redis_client():
    global _redis_pool, _redis_cluster_client
    if getattr(Config, 'REDIS_CLUSTER_MODE', False):
        if _redis_cluster_client is None:
            nodes = []
            for item in Config.REDIS_CLUSTER_NODES.split(","):
                if ":" in item:
                    host, port = item.strip().split(":")
                    nodes.append(ClusterNode(host, int(port)))
            _redis_cluster_client = RedisCluster(
                startup_nodes=nodes,
                password=Config.REDIS_PASSWORD,
                decode_responses=True
            )
        return _redis_cluster_client
    else:
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

USER_ROUTE_PREFIX = "mini_im:route:user:"
NODE_CHANNEL_PREFIX = "mini_im:node:"
BROADCAST_CHANNEL = "mini_im:broadcast"


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
        for k in r.scan_iter(f"{USER_ROUTE_PREFIX}*"):
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


# ==========================================
# Precision Gateway Router (Session Routing for 100k Concurrent)
# ==========================================
def register_user_gateway(user_id: int, node_id: str, ttl: int = None):
    """
    Binds an online user to a specific WebSocket gateway node in Redis.
    TTL matches or slightly exceeds the WebSocket heartbeat interval.
    """
    if not user_id or not node_id:
        return
    r = get_redis_client()
    expire_time = ttl or getattr(Config, 'ROUTE_TTL_SECONDS', 60)
    key = f"{USER_ROUTE_PREFIX}{user_id}"
    r.set(key, node_id, ex=expire_time)

def refresh_user_gateway(user_id: int, ttl: int = None):
    """
    Extends gateway session TTL during heartbeat ping.
    """
    if not user_id:
        return
    r = get_redis_client()
    key = f"{USER_ROUTE_PREFIX}{user_id}"
    expire_time = ttl or getattr(Config, 'ROUTE_TTL_SECONDS', 60)
    r.expire(key, expire_time)

def unregister_user_gateway(user_id: int, node_id: str = None):
    """
    Unbinds an online user from a gateway node upon disconnect.
    Safe against race conditions if node_id is provided.
    """
    if not user_id:
        return
    r = get_redis_client()
    key = f"{USER_ROUTE_PREFIX}{user_id}"
    if node_id:
        current_node = r.get(key)
        if current_node == node_id:
            r.delete(key)
    else:
        r.delete(key)

def get_user_gateway(user_id: int) -> str:
    """
    Returns node_id where the user is currently connected, or None.
    """
    try:
        r = get_redis_client()
        return r.get(f"{USER_ROUTE_PREFIX}{user_id}")
    except Exception:
        return None

def batch_get_user_gateways(user_ids: list) -> dict:
    """
    High-performance batched pipeline to retrieve gateway node_ids for a group of users
    in a single Redis round-trip. Returns {user_id: node_id}.
    """
    if not user_ids:
        return {}
    r = get_redis_client()
    pipe = r.pipeline()
    for uid in user_ids:
        pipe.get(f"{USER_ROUTE_PREFIX}{uid}")
    results = pipe.execute()
    return {uid: node for uid, node in zip(user_ids, results)}

def publish_to_gateway_node(node_id: str, event_data: dict):
    """
    Delivers a message to a specific WebSocket gateway node without cluster-wide broadcasting.
    """
    if not node_id:
        return
    channel = f"{NODE_CHANNEL_PREFIX}{node_id}"
    publish_event(channel, event_data)

def publish_to_gateways_for_users(user_ids: list, event_data: dict):
    """
    Groups users by their gateway node and sends ONE targeted message per gateway node.
    Reduces group fan-out overhead over Redis Pub/Sub by orders of magnitude.
    """
    if not user_ids:
        return
    gateways = batch_get_user_gateways(user_ids)
    from collections import defaultdict
    node_to_users = defaultdict(list)
    for uid, nid in gateways.items():
        if nid:
            node_to_users[nid].append(uid)
    
    for nid, target_uids in node_to_users.items():
        targeted_payload = {
            "target_user_ids": target_uids,
            "event": event_data.get("event"),
            "data": event_data.get("data")
        }
        publish_to_gateway_node(nid, targeted_payload)

# ==========================================
# Conversation Monotonic Sequence ID (SeqID)
# ==========================================
def get_next_seq_id(conversation_type: str, entity_a: int, entity_b: int = None) -> int:
    """
    Generates a strictly increasing monotonic 64-bit integer sequence ID for a conversation.
    Guarantees absolute chronological ordering across distributed nodes.
    """
    r = get_redis_client()
    if conversation_type == "direct":
        uid1, uid2 = sorted([int(entity_a), int(entity_b)])
        key = f"mini_im:seq:direct:{uid1}_{uid2}"
    elif conversation_type == "group":
        key = f"mini_im:seq:group:{int(entity_a)}"
    else:
        key = f"mini_im:seq:other:{entity_a}"
    return r.incr(key)
