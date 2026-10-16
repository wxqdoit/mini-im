import requests
import json
import time
import os

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1/api")

print("=" * 65)
print("TEST 2: OFFLINE PUSH NOTIFICATION & E2EE PRIVACY SHIELD TEST")
print("Target: Device Token API + Offline Detection + Masked Push Dispatch")
print("=" * 65)

ts = int(time.time())
# 1. Register User A (Sender) and User B (Offline Recipient)
res_a = requests.post(f"{BASE_URL}/auth/register", json={
    "username": f"sender_a_{ts}",
    "password": "password123",
    "nickname": "Alice Sender"
})
assert res_a.status_code == 201, res_a.text
token_a = res_a.json()["token"]
user_a = res_a.json()["user"]
headers_a = {"Authorization": f"Bearer {token_a}"}

res_b = requests.post(f"{BASE_URL}/auth/register", json={
    "username": f"recipient_b_{ts}",
    "password": "password123",
    "nickname": "Bob Recipient"
})
assert res_b.status_code == 201, res_b.text
token_b = res_b.json()["token"]
user_b = res_b.json()["user"]
headers_b = {"Authorization": f"Bearer {token_b}"}

print(f"1. Registered Sender Alice (ID: {user_a['id']}) & Recipient Bob (ID: {user_b['id']})")

# 2. Bob registers device tokens (iOS & Web)
dev_token_ios = f"apns_device_token_{user_b['id']}_abcdef"
res = requests.post(f"{BASE_URL}/users/device-token", headers=headers_b, json={
    "platform": "ios",
    "device_token": dev_token_ios
})
assert res.status_code == 200, res.text
assert res.json()["platform"] == "ios"
print(f"2a. Registered iOS device token for Bob: {dev_token_ios}")

dev_token_web = f"web_push_token_{user_b['id']}_123456"
res = requests.post(f"{BASE_URL}/users/device-token", headers=headers_b, json={
    "platform": "web",
    "device_token": dev_token_web
})
assert res.status_code == 200, res.text
print(f"2b. Registered Web device token for Bob: {dev_token_web}")

# 3. Bob is completely OFFLINE (no WebSocket connection established)
# Alice sends a regular plain text message to Bob
plain_text = "Hey Bob, please check this offline push notification!"
res = requests.post(f"{BASE_URL}/messages/send", headers=headers_a, json={
    "conversation_type": "direct",
    "recipient_id": user_b["id"],
    "msg_type": "text",
    "content": plain_text
})
assert res.status_code == 200

# Allow Kafka batch consumer to process message & trigger offline push
time.sleep(0.8)

# 4. Check push notifications received by Bob
res_push = requests.get(f"{BASE_URL}/users/push-notifications?limit=10", headers=headers_b)
assert res_push.status_code == 200, res_push.text
notifications = res_push.json()["notifications"]
assert len(notifications) >= 1, f"Expected at least 1 notification, got {len(notifications)}"

latest_notif = notifications[0]
print(f"3. Verified Offline Push for Plain Message:")
print(f"   Title: {latest_notif['title']}")
print(f"   Body: {latest_notif['body']}")
print(f"   Device Count: {latest_notif['device_count']}")
print(f"   Status: {latest_notif['status']}")
assert latest_notif["title"] == user_a["nickname"]
assert plain_text in latest_notif["body"]
assert latest_notif["device_count"] == 2
assert dev_token_ios in latest_notif["tokens"]

# 5. E2EE Privacy Shield Verification:
# Alice sends an E2EE encrypted message to Bob (is_encrypted=True)
fake_ciphertext = "AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA="
res = requests.post(f"{BASE_URL}/messages/send", headers=headers_a, json={
    "conversation_type": "direct",
    "recipient_id": user_b["id"],
    "msg_type": "text",
    "content": fake_ciphertext,
    "is_encrypted": True,
    "iv": "123456789012"
})
assert res.status_code == 200
time.sleep(0.8)

res_push = requests.get(f"{BASE_URL}/users/push-notifications?limit=10", headers=headers_b)
notifications = res_push.json()["notifications"]
e2ee_notif = notifications[0]

print(f"4. Verified Offline Push for E2EE Encrypted Message:")
print(f"   Title: {e2ee_notif['title']}")
print(f"   Body: {e2ee_notif['body']}")
assert fake_ciphertext not in e2ee_notif["body"], "Ciphertext MUST NOT leak into push body!"
assert "[端到端加密消息" in e2ee_notif["body"], f"Expected E2EE masked body, got: {e2ee_notif['body']}"
print("   E2EE Privacy Shield Check: PASSED! Zero ciphertext leaked to push provider.")

# 6. Unregister device tokens on logout
res_del = requests.delete(f"{BASE_URL}/users/device-token", headers=headers_b, json={
    "device_token": dev_token_ios
})
assert res_del.status_code == 200
print(f"5. Deactivated iOS device token on logout.")

print("=" * 65)
print("SUCCESS: OFFLINE PUSH NOTIFICATIONS FULLY VERIFIED!")
print("=" * 65)
