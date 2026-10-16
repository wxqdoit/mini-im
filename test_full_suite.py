import requests
import json
import time
import websocket

BASE_URL = "http://127.0.0.1:5001/api"
WS_URL = "ws://127.0.0.1:5001/ws"

print("="*60)
print("MINI-IM FULL MVP END-TO-END AUTOMATED TEST SUITE")
print("Stack: Python + PostgreSQL + Redis + Flask + Kafka + MinIO + WSS + React")
print("="*60)

# Step 1: Health check
res = requests.get(f"{BASE_URL}/health")
assert res.status_code == 200
data = res.json()
print("1. Health Check:", data)
assert data["services"]["postgres"] == "ok"
assert data["services"]["redis"] == "ok"
assert data["services"]["kafka"] == "ok"
assert data["services"]["minio"] == "ok"

# Step 2: Register & Login Test Users
uname1 = f"tester_a_{int(time.time())}"
uname2 = f"tester_b_{int(time.time())}"

res = requests.post(f"{BASE_URL}/auth/register", json={
    "username": uname1, "password": "password123", "nickname": "Tester Alpha", "bio": "Alpha Bio"
})
assert res.status_code == 201, res.text
token_a = res.json()["token"]
user_a = res.json()["user"]
headers_a = {"Authorization": f"Bearer {token_a}"}
print(f"2a. Registered User A: {user_a['username']} (ID: {user_a['id']})")

res = requests.post(f"{BASE_URL}/auth/register", json={
    "username": uname2, "password": "password123", "nickname": "Tester Beta", "bio": "Beta Bio"
})
assert res.status_code == 201, res.text
token_b = res.json()["token"]
user_b = res.json()["user"]
headers_b = {"Authorization": f"Bearer {token_b}"}
print(f"2b. Registered User B: {user_b['username']} (ID: {user_b['id']})")

# Step 3: Modify Profile & Upload Avatar to MinIO
avatar_content = b"fake_avatar_image_bytes_png_header"
files = {"file": ("avatar.png", avatar_content, "image/png")}
res = requests.post(f"{BASE_URL}/upload", headers=headers_a, files=files, data={"folder": "avatars"})
assert res.status_code == 201, res.text
avatar_url = res.json()["url"]
print(f"3a. Uploaded avatar to MinIO: {avatar_url}")

res = requests.put(f"{BASE_URL}/users/profile", headers=headers_a, json={
    "nickname": "Tester Alpha Pro",
    "bio": "Full-Stack Engineer & Architect",
    "avatar": avatar_url,
    "status": "online"
})
assert res.status_code == 200, res.text
print(f"3b. Updated User A Profile: Nickname='{res.json()['user']['nickname']}', Status='{res.json()['user']['status']}'")

# Step 4: Search User & Send Friend Request
res = requests.get(f"{BASE_URL}/users/search?q={uname2}", headers=headers_a)
search_results = res.json()["users"]
assert len(search_results) >= 1
print(f"4a. User A searched for User B: found {len(search_results)} match")

res = requests.post(f"{BASE_URL}/friends/request", headers=headers_a, json={
    "receiver_id": user_b["id"],
    "message": "Hello Beta, let's connect!"
})
assert res.status_code == 201, res.text
req_id = res.json()["request_id"]
print(f"4b. User A sent friend request to User B (Req ID: {req_id})")

# User B checks received requests and accepts
res = requests.get(f"{BASE_URL}/friends/requests", headers=headers_b)
received = res.json()["received"]
assert any(r["id"] == req_id for r in received)
print(f"4c. User B received request from User A: '{received[0]['message']}'")

res = requests.post(f"{BASE_URL}/friends/requests/{req_id}/respond", headers=headers_b, json={"action": "accept"})
assert res.status_code == 200, res.text
print("4d. User B accepted friend request.")

# Verify friendship in both directions
res_a_friends = requests.get(f"{BASE_URL}/friends", headers=headers_a).json()["friends"]
res_b_friends = requests.get(f"{BASE_URL}/friends", headers=headers_b).json()["friends"]
assert any(f["id"] == user_b["id"] for f in res_a_friends)
assert any(f["id"] == user_a["id"] for f in res_b_friends)
print(f"4e. Verified bidirectional friendship! (A friends count: {len(res_a_friends)}, B friends count: {len(res_b_friends)})")

# Step 5: WebSocket Real-time Connection for User B
ws_b = websocket.WebSocket()
ws_b.connect(f"{WS_URL}?token={token_b}")
time.sleep(0.5)

# Step 6: User A sends Text Message via Kafka Pipeline
res = requests.post(f"{BASE_URL}/messages/send", headers=headers_a, json={
    "conversation_type": "direct",
    "recipient_id": user_b["id"],
    "msg_type": "text",
    "content": "Hello User B! This message traveled through Kafka broker!"
})
assert res.status_code == 200, res.text
print("6a. User A sent direct text message via Kafka pipeline")

# User B receives message via WebSocket
ws_b.settimeout(4.0)
received_chat = None
for _ in range(10):
    try:
        raw = ws_b.recv()
        f = json.loads(raw)
        if f.get("event") == "new_message":
            received_chat = f["data"]
            break
    except Exception as ex:
        print("DEBUG EXCEPTION:", ex)
        break
assert received_chat is not None
print(f"6b. User B received real-time WebSocket push: '{received_chat['content']}' (from ID: {received_chat['sender_id']})")

# Step 7: Send Media Message (Image upload to MinIO + send media message)
media_file_content = b"fake_png_chat_image_data_payload_12345"
files = {"file": ("demo_screenshot.png", media_file_content, "image/png")}
res = requests.post(f"{BASE_URL}/upload", headers=headers_a, files=files, data={"folder": "chat"})
assert res.status_code == 201
media_data = res.json()
print(f"7a. Uploaded media image to MinIO: {media_data['url']} (size: {media_data['file_size']} bytes)")

res = requests.post(f"{BASE_URL}/messages/send", headers=headers_a, json={
    "conversation_type": "direct",
    "recipient_id": user_b["id"],
    "msg_type": "image",
    "content": "[图片]",
    "media_url": media_data["url"],
    "file_name": media_data["file_name"],
    "file_size": media_data["file_size"]
})
assert res.status_code == 200
print("7b. User A sent media message via Kafka")

received_media = None
for _ in range(10):
    try:
        raw = ws_b.recv()
        f = json.loads(raw)
        if f.get("event") == "new_message":
            received_media = f["data"]
            break
    except Exception as ex:
        print("DEBUG EXCEPTION:", ex)
        break
assert received_media is not None
assert received_media["msg_type"] == "image"
print(f"7c. User B received media message via WebSocket with MinIO URL: {received_media['media_url']}")

# Step 8: Group Management (Create, Join, Members, Group Message)
res = requests.post(f"{BASE_URL}/groups", headers=headers_a, json={
    "name": "E2E Architecture Study Group",
    "description": "Kafka, Redis, PG, MinIO, React, WSS",
    "avatar": "https://api.dicebear.com/7.x/shapes/svg?seed=ArchGroup"
})
assert res.status_code == 201
group = res.json()["group"]
group_id = group["id"]
print(f"8a. User A created group: '{group['name']}' (Group ID: {group_id})")

# User A invites User B to group
res = requests.post(f"{BASE_URL}/groups/{group_id}/invite", headers=headers_a, json={
    "user_ids": [user_b["id"]]
})
assert res.status_code == 200
print(f"8b. User A invited User B to group: {res.json()['added_user_ids']}")

# Check group members
res = requests.get(f"{BASE_URL}/groups/{group_id}/members", headers=headers_b)
members = res.json()["members"]
assert len(members) == 2
print(f"8c. Group has {len(members)} members: {[m['nickname'] for m in members]}")

# User B sends message to group via WebSocket
ws_b.send(json.dumps({
    "type": "chat_message",
    "conversation_type": "group",
    "recipient_id": group_id,
    "msg_type": "text",
    "content": "Hello everyone in the study group!"
}))
print("8d. User B sent group message via WebSocket")

# Wait 1s and query group message history
time.sleep(1.2)
res = requests.get(f"{BASE_URL}/messages/history?type=group&target_id={group_id}", headers=headers_a)
group_msgs = res.json()["messages"]
assert len(group_msgs) >= 1
print(f"8e. User A read group history: {len(group_msgs)} messages. Latest: '{group_msgs[-1]['content']}'")

# Step 9: Conversations overview
res = requests.get(f"{BASE_URL}/messages/conversations", headers=headers_a)
convs = res.json()["conversations"]
assert len(convs) >= 2
print(f"9. User A Conversations overview: {len(convs)} active chats -> {[c['name'] for c in convs]}")

# Step 10: Cleanup & Management (Delete friend, leave group)
res = requests.post(f"{BASE_URL}/groups/{group_id}/leave", headers=headers_b)
assert res.status_code == 200
print("10a. User B left group.")

res = requests.delete(f"{BASE_URL}/groups/{group_id}", headers=headers_a)
assert res.status_code == 200
print("10b. User A disbanded group.")

res = requests.delete(f"{BASE_URL}/friends/{user_b['id']}", headers=headers_a)
assert res.status_code == 200
print("10c. User A unfriended User B.")

ws_b.close()

print("\n" + "="*60)
print("SUCCESS: 10/10 TEST SUITES PASSED! ALL MVP CRITERIA VERIFIED!")
print("="*60)
