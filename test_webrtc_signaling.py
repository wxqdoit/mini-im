import requests
import json
import time
import websocket
import os
import sys

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1/api")
WS_URL = os.getenv("WS_URL", "ws://127.0.0.1/ws")

print("=" * 65)
print("TEST 3: WEBRTC AUDIO & VIDEO CALL SIGNALING ENGINE TEST")
print("Target: Call Invite -> Ringing -> Accept -> SDP Offer/Answer -> ICE -> Hangup")
print("=" * 65)

ts = int(time.time())
# 1. Register Alice and Bob
res_a = requests.post(f"{BASE_URL}/auth/register", json={
    "username": f"webrtc_alice_{ts}", "password": "password123", "nickname": "Alice Call"
})
assert res_a.status_code == 201
token_a = res_a.json()["token"]
user_a = res_a.json()["user"]

res_b = requests.post(f"{BASE_URL}/auth/register", json={
    "username": f"webrtc_bob_{ts}", "password": "password123", "nickname": "Bob Call"
})
assert res_b.status_code == 201
token_b = res_b.json()["token"]
user_b = res_b.json()["user"]

print(f"1. Registered Callers: Alice (ID: {user_a['id']}) & Bob (ID: {user_b['id']})")

# 2. Establish WebSocket connections for Alice and Bob
ws_a = websocket.create_connection(f"{WS_URL}?token={token_a}", timeout=5)
ws_b = websocket.create_connection(f"{WS_URL}?token={token_b}", timeout=5)

# Consume connected ack frames
ack_a = json.loads(ws_a.recv())
ack_b = json.loads(ws_b.recv())
assert ack_a.get("event") == "connected"
assert ack_b.get("event") == "connected"
print(f"2. Established WebSocket connections (Alice node: {ack_a['data']['node_id']}, Bob node: {ack_b['data']['node_id']})")

def wait_for_event(ws, expected_event, timeout=3):
    start = time.time()
    while time.time() - start < timeout:
        try:
            raw = ws.recv()
            data = json.loads(raw)
            if data.get("event") == expected_event:
                return data["data"]
        except Exception:
            pass
    raise TimeoutError(f"Timeout waiting for event: {expected_event}")

call_id = f"test_call_{ts}"

# 3. Alice initiates Video Call Invite to Bob
ws_a.send(json.dumps({
    "type": "call_invite",
    "call_id": call_id,
    "recipient_id": user_b["id"],
    "call_type": "video"
}))
print(f"3. Alice dispatched 'call_invite' to Bob (Call ID: {call_id})")

# 4. Bob receives call_invite
invite_data = wait_for_event(ws_b, "call_invite")
assert invite_data["call_id"] == call_id
assert invite_data["caller_id"] == user_a["id"]
assert invite_data["call_type"] == "video"
print(f"4. Bob received 'call_invite' with Caller: {invite_data['caller']['nickname']}")

# 5. Bob responds with call_ringing
ws_b.send(json.dumps({
    "type": "call_ringing",
    "call_id": call_id,
    "caller_id": user_a["id"]
}))

ringing_data = wait_for_event(ws_a, "call_ringing")
assert ringing_data["call_id"] == call_id
print(f"5. Alice received 'call_ringing' confirmation from Bob.")

# 6. Bob accepts call
ws_b.send(json.dumps({
    "type": "call_accept",
    "call_id": call_id,
    "caller_id": user_a["id"]
}))

accept_data = wait_for_event(ws_a, "call_accept")
assert accept_data["call_id"] == call_id
print(f"6. Alice received 'call_accept' from Bob.")

# 7. Alice sends WebRTC SDP Offer to Bob
mock_sdp_offer = {"type": "offer", "sdp": "v=0\r\no=alice 123456 2 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\n"}
ws_a.send(json.dumps({
    "type": "webrtc_offer",
    "call_id": call_id,
    "target_id": user_b["id"],
    "sdp": mock_sdp_offer
}))

offer_data = wait_for_event(ws_b, "webrtc_offer")
assert offer_data["sdp"]["type"] == "offer"
assert offer_data["sender_id"] == user_a["id"]
print(f"7. Bob received WebRTC SDP Offer from Alice.")

# 8. Bob sends WebRTC SDP Answer to Alice
mock_sdp_answer = {"type": "answer", "sdp": "v=0\r\no=bob 654321 2 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\n"}
ws_b.send(json.dumps({
    "type": "webrtc_answer",
    "call_id": call_id,
    "target_id": user_a["id"],
    "sdp": mock_sdp_answer
}))

answer_data = wait_for_event(ws_a, "webrtc_answer")
assert answer_data["sdp"]["type"] == "answer"
assert answer_data["sender_id"] == user_b["id"]
print(f"8. Alice received WebRTC SDP Answer from Bob.")

# 9. Exchange ICE Candidates
mock_candidate = {"candidate": "candidate:1 1 UDP 2122260223 127.0.0.1 50000 typ host", "sdpMid": "0", "sdpMLineIndex": 0}
ws_a.send(json.dumps({
    "type": "webrtc_ice_candidate",
    "call_id": call_id,
    "target_id": user_b["id"],
    "candidate": mock_candidate
}))

ice_data = wait_for_event(ws_b, "webrtc_ice_candidate")
assert ice_data["candidate"]["sdpMid"] == "0"
print(f"9. Bob received ICE Candidate from Alice.")

# 10. Alice hangs up call
ws_a.send(json.dumps({
    "type": "call_hangup",
    "call_id": call_id,
    "target_id": user_b["id"]
}))

hangup_data = wait_for_event(ws_b, "call_hangup")
assert hangup_data["call_id"] == call_id
print(f"10. Bob received 'call_hangup' from Alice. Call teardown complete.")

# 11. Test calling an OFFLINE user -> should receive call_failed
ws_a.send(json.dumps({
    "type": "call_invite",
    "call_id": f"offline_call_{ts}",
    "recipient_id": 999999, # non-existent or offline user
    "call_type": "audio"
}))

failed_data = wait_for_event(ws_a, "call_failed")
assert failed_data["reason"] == "User is currently offline"
print(f"11. Verified offline call rejection: Received 'call_failed' ({failed_data['reason']})")

ws_a.close()
ws_b.close()

print("=" * 65)
print("SUCCESS: WEBRTC CALL SIGNALING ENGINE FULLY VERIFIED!")
print("=" * 65)
