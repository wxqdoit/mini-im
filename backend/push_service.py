import json
import time
from config import Config
from db import get_db
from redis_client import get_redis_client

class BasePushProvider:
    def send_push(self, user_id: int, devices: list, title: str, body: str, data: dict):
        raise NotImplementedError

class MockPushProvider(BasePushProvider):
    def send_push(self, user_id: int, devices: list, title: str, body: str, data: dict):
        record = {
            "user_id": user_id,
            "device_count": len(devices),
            "tokens": [d.get("device_token") for d in devices],
            "title": title,
            "body": body,
            "data": data,
            "timestamp": time.time(),
            "status": "delivered_mock"
        }
        try:
            r = get_redis_client()
            payload_str = json.dumps(record, default=str)
            r.lpush("mini_im:push_log:recent", payload_str)
            r.ltrim("mini_im:push_log:recent", 0, 500)
            r.lpush(f"mini_im:push_log:user:{user_id}", payload_str)
            r.ltrim(f"mini_im:push_log:user:{user_id}", 0, 100)
        except Exception as e:
            print(f"[PushService] Warning recording push to Redis: {e}")

        print(f"[PushService] [MOCK] Successfully delivered push to User {user_id} ({len(devices)} devices): [{title}] {body}")
        return True

class APNsProvider(BasePushProvider):
    def send_push(self, user_id: int, devices: list, title: str, body: str, data: dict):
        # Fallback to mock if APNs credentials not configured in environment
        if not getattr(Config, "APNs_KEY_PATH", None):
            return MockPushProvider().send_push(user_id, devices, title, body, data)
        # Production APNs HTTP/2 implementation hook
        print(f"[PushService] [APNs] Sent push to User {user_id}")
        return True

class FCMProvider(BasePushProvider):
    def send_push(self, user_id: int, devices: list, title: str, body: str, data: dict):
        # Fallback to mock if FCM credentials not configured in environment
        if not getattr(Config, "FCM_CREDENTIALS_PATH", None):
            return MockPushProvider().send_push(user_id, devices, title, body, data)
        # Production FCM implementation hook
        print(f"[PushService] [FCM] Sent push to User {user_id}")
        return True

_providers = {
    "mock": MockPushProvider(),
    "apns": APNsProvider(),
    "fcm": FCMProvider(),
}

def get_push_provider() -> BasePushProvider:
    provider_name = getattr(Config, "PUSH_NOTIFICATION_PROVIDER", "mock").lower()
    return _providers.get(provider_name, _providers["mock"])

def get_user_active_devices(user_id: int) -> list:
    try:
        with get_db() as cur:
            cur.execute("""
                SELECT platform, device_token, updated_at 
                FROM user_devices 
                WHERE user_id = %s AND is_active = TRUE;
            """, (user_id,))
            return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print(f"[PushService] Error querying user devices: {e}")
        return []

def dispatch_offline_notification(user_id: int, message: dict):
    """
    Constructs and dispatches push notification for an offline recipient.
    Strictly safeguards E2EE content: if is_encrypted is True, hides ciphertext!
    """
    if not user_id or not message:
        return

    sender = message.get("sender") or {}
    sender_name = sender.get("nickname") or sender.get("username") or "有人"
    conv_type = message.get("conversation_type", "direct")
    
    # 1. Format Title
    if conv_type == "group":
        title = f"群聊新消息"
    else:
        title = f"{sender_name}"

    # 2. Format Body with E2EE Zero-Knowledge Protection
    is_encrypted = message.get("is_encrypted", False)
    if is_encrypted:
        body = "[端到端加密消息 (请打开 App 查看)]"
    else:
        msg_type = message.get("msg_type", "text")
        if msg_type == "image":
            body = "[图片]"
        elif msg_type == "file":
            file_name = message.get("file_name", "文件")
            body = f"[文件] {file_name}"
        else:
            raw_content = message.get("content", "")
            body = (raw_content[:80] + "...") if len(raw_content) > 80 else raw_content

    # 3. Notification custom payload
    payload = {
        "conversation_type": conv_type,
        "sender_id": message.get("sender_id"),
        "recipient_id": message.get("recipient_id"),
        "msg_id": message.get("id"),
        "seq_id": message.get("seq_id", 0),
        "is_encrypted": is_encrypted
    }

    devices = get_user_active_devices(user_id)
    provider = get_push_provider()
    provider.send_push(user_id, devices, title, body, payload)

def get_user_push_logs(user_id: int = None, limit: int = 20) -> list:
    try:
        r = get_redis_client()
        key = f"mini_im:push_log:user:{user_id}" if user_id else "mini_im:push_log:recent"
        raw_items = r.lrange(key, 0, limit - 1)
        return [json.loads(item) for item in raw_items]
    except Exception:
        return []
