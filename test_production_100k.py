import requests
import json
import time
import websocket
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))
from redis_client import get_user_gateway, get_redis_client, get_next_seq_id

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1/api")
WS_URL = os.getenv("WS_URL", "ws://127.0.0.1/ws")

print("=" * 65)
print("MINI-IM 100K CONCURRENCY ARCHITECTURE TEST SUITE")
print("Testing: Precision Routing, Monotonic SeqID, Delta Sync, Client ACK")
print("=" * 65)

# 1. Register test users
ts = int(time.time())
u1_name = f"user_p1_{ts}"
u2_name = f"user_p2_{ts}"

res1 = requests.post(f"{BASE_URL}/auth/register", json={"username": u1_name, "password": "secret123", "nickname": "User 100k A"})
assert res1.status_code == 201, res1.text
user1 = res1.json()["user"]
token1 = res1.json()["token"]

res2 = requests.post(f"{BASE_URL}/auth/register", json={"username": u2_name, "password": "secret123", "nickname": "User 100k B"})
assert res2.status_code == 201, res2.text
user2 = res2.json()["user"]
token2 = res2.json()["token"]

headers1 = {"Authorization": f"Bearer {token1}"}
headers2 = {"Authorization": f"Bearer {token2}"}

print(f"1. Created Users: {user1['nickname']} (ID: {user1['id']}) & {user2['nickname']} (ID: {user2['id']})")

# 2. Establish WebSocket connection for User 2 and verify Precision Session Router in Redis
ws2 = websocket.create_connection(f"{WS_URL}?token={token2}", timeout=5)
init_ack = json.loads(ws2.recv())
assert init_ack.get("event") == "connected"
node_id = init_ack["data"]["node_id"]
print(f"2a. User 2 connected to Gateway Node: {node_id}")

# Verify Redis Session Route
registered_node = get_user_gateway(user2["id"])
assert registered_node == node_id, f"Expected {node_id}, got {registered_node}"
print(f"2b. Verified Redis Precision Route: mini_im:route:user:{user2['id']} -> '{registered_node}'")

# 3. User 1 sends 3 messages to User 2 via Kafka pipeline and verifies Monotonic SeqID
msg_payloads = [
    {"conversation_type": "direct", "recipient_id": user2["id"], "msg_type": "text", "content": f"Message #{i}"}
    for i in range(1, 4)
]

for p in msg_payloads:
    r = requests.post(f"{BASE_URL}/messages/send", headers=headers1, json=p)
    assert r.status_code == 200

time.sleep(0.6)  # allow Kafka batch consumer to process

# 4. Check WebSocket delivery on User 2's socket
received_msgs = []
for _ in range(5):
    try:
        raw = ws2.recv()
        data = json.loads(raw)
        if data.get("event") == "new_message":
            received_msgs.append(data["data"])
            if len(received_msgs) == 3:
                break
    except Exception:
        break

assert len(received_msgs) == 3, f"Expected 3 messages, got {len(received_msgs)}"
seqs = [m.get("seq_id", 0) for m in received_msgs]
print(f"3. User 2 received 3 messages via Precision Gateway Router. SeqIDs: {seqs}")
assert seqs[0] < seqs[1] < seqs[2], "SeqIDs must be strictly monotonic!"
print("4. Verified Monotonic SeqID Ordering: PASSED!")

# 5. Verify Client ACK (marking message read)
first_msg_id = received_msgs[0]["id"]
ws2.send(json.dumps({"type": "ack", "msg_id": first_msg_id, "seq_id": seqs[0]}))
time.sleep(0.2)

# Verify /history shows is_read = True for first_msg_id
hist_res = requests.get(f"{BASE_URL}/messages/history?type=direct&target_id={user2['id']}", headers=headers1)
assert hist_res.status_code == 200
hist_msgs = hist_res.json()["messages"]
first_in_hist = next(m for m in hist_msgs if m["id"] == first_msg_id)
assert first_in_hist["is_read"] is True
print(f"5. Client ACK Protocol: Message {first_msg_id} marked as read successfully!")

# 6. Verify Incremental Delta Sync Protocol (/api/messages/sync)
# Sync from seqs[0] (should return messages 2 and 3)
sync_res = requests.get(
    f"{BASE_URL}/messages/sync?type=direct&target_id={user1['id']}&last_seq_id={seqs[0]}",
    headers=headers2
)
assert sync_res.status_code == 200
sync_data = sync_res.json()
assert sync_data["count"] == 2
assert sync_data["messages"][0]["seq_id"] == seqs[1]
assert sync_data["messages"][1]["seq_id"] == seqs[2]
print(f"6a. REST API Delta Sync (/api/messages/sync): Returned exactly {sync_data['count']} incremental messages!")

# 7. Verify WebSocket Delta Sync ({type: 'sync'})
ws2.send(json.dumps({
    "type": "sync",
    "conversation_type": "direct",
    "target_id": user1["id"],
    "last_seq_id": seqs[1]
}))

ws_sync_event = None
for _ in range(5):
    try:
        raw = ws2.recv()
        data = json.loads(raw)
        if data.get("event") == "sync_delta":
            ws_sync_event = data["data"]
            break
    except Exception:
        break

assert ws_sync_event is not None
assert len(ws_sync_event["messages"]) == 1
assert ws_sync_event["messages"][0]["seq_id"] == seqs[2]
print(f"6b. WebSocket Delta Sync Protocol: Returned 1 remaining delta message (SeqID: {seqs[2]})")

# Clean up
ws2.close()
time.sleep(0.2)
assert get_user_gateway(user2["id"]) is None
print("7. User 2 disconnected: Verified session unregistration from Redis Gateway Router.")

print("=" * 65)
print("ALL 100K CONCURRENCY ARCHITECTURE TESTS PASSED SUCCESSFULLY!")
print("=" * 65)
