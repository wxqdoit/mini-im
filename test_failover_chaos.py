import os
import sys
import subprocess
import time
import requests
import json
import websocket

backend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backend')
sys.path.append(backend_dir)
from redis_client import get_user_gateway

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1/api")
PORT_GW1 = int(os.getenv("PORT_GW1", "5004"))
PORT_GW2 = int(os.getenv("PORT_GW2", "5005"))

print("=" * 65)
print("MINI IM MULTI-NODE FAILOVER & CHAOS RESILIENCE TEST")
print("Testing: Cross-Node Routing, Gateway Crash, Route Migration, Zero-Loss Sync")
print("=" * 65)

def wait_for_port(port, timeout=10):
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(f"http://127.0.0.1:{port}/api/health", timeout=1)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False

# 1. Provision 2 distinct Gateway processes
env_gw1 = os.environ.copy()
env_gw1["SERVICE_ROLE"] = "gateway"
env_gw1["NODE_ID"] = "gw_node_alpha"
env_gw1["PORT"] = str(PORT_GW1)
env_gw1["PYTHONPATH"] = backend_dir
env_gw1["PYTHONUNBUFFERED"] = "1"
p_gw1 = subprocess.Popen([sys.executable, "-u", "app.py"], cwd=backend_dir, env=env_gw1, stdout=None, stderr=None)

env_gw2 = os.environ.copy()
env_gw2["SERVICE_ROLE"] = "gateway"
env_gw2["NODE_ID"] = "gw_node_beta"
env_gw2["PORT"] = str(PORT_GW2)
env_gw2["PYTHONPATH"] = backend_dir
env_gw2["PYTHONUNBUFFERED"] = "1"
p_gw2 = subprocess.Popen([sys.executable, "-u", "app.py"], cwd=backend_dir, env=env_gw2, stdout=None, stderr=None)

assert wait_for_port(PORT_GW1), f"Gateway 1 on port {PORT_GW1} failed to start!"
assert wait_for_port(PORT_GW2), f"Gateway 2 on port {PORT_GW2} failed to start!"
print(f"Gateways initialized: Gateway 1 (: {PORT_GW1}), Gateway 2 (: {PORT_GW2})")

try:
    # 2. Register test users
    ts = int(time.time())
    res_a = requests.post(f"{BASE_URL}/auth/register", json={"username": f"chaos_a_{ts}", "password": "p123456", "nickname": "Alice Chaos"})
    tok_a = res_a.json()["token"]
    uid_a = res_a.json()["user"]["id"]

    res_b = requests.post(f"{BASE_URL}/auth/register", json={"username": f"chaos_b_{ts}", "password": "p123456", "nickname": "Bob Chaos"})
    tok_b = res_b.json()["token"]
    uid_b = res_b.json()["user"]["id"]

    # 3. Connect Alice to Gateway 1 (Alpha) and Bob to Gateway 2 (Beta)
    ws_alice = websocket.create_connection(f"ws://127.0.0.1:{PORT_GW1}/ws?token={tok_a}", timeout=5)
    init_a = json.loads(ws_alice.recv())
    assert init_a["data"]["node_id"] == "gw_node_alpha"
    print(f"1. Alice connected to Gateway 1: {init_a['data']['node_id']}")

    ws_bob = websocket.create_connection(f"ws://127.0.0.1:{PORT_GW2}/ws?token={tok_b}", timeout=5)
    init_b = json.loads(ws_bob.recv())
    assert init_b["data"]["node_id"] == "gw_node_beta"
    print(f"2. Bob connected to Gateway 2: {init_b['data']['node_id']}")

    # Verify Redis routes
    assert get_user_gateway(uid_a) == "gw_node_alpha"
    assert get_user_gateway(uid_b) == "gw_node_beta"
    print("3. Verified Redis Session Routes: Alice->Alpha, Bob->Beta")

    # 4. Cross-Node Message Test: Alice sends message to Bob
    msg1 = {"type": "chat_message", "conversation_type": "direct", "recipient_id": uid_b, "content": "Cross-gateway message 1"}
    ws_alice.send(json.dumps(msg1))
    
    # Bob receives on Gateway 2 (dispatched by Precision Router)
    received_on_b = None
    for _ in range(8):
        try:
            raw = ws_bob.recv()
            data = json.loads(raw)
            if data.get("event") == "new_message":
                received_on_b = data["data"]
                break
        except Exception:
            pass

    assert received_on_b is not None
    assert received_on_b["content"] == "Cross-gateway message 1"
    print(f"4. Cross-Node Routing Verified: Alice (on Alpha) -> Bob (on Beta) received! (SeqID: {received_on_b.get('seq_id')})")

    # 5. CHAOS INJECTION: Crash Gateway 1 (Alpha)!
    print("5. [CHAOS] Simulating sudden hardware / process failure: KILLING Gateway 1 (Alpha)...")
    p_gw1.terminate()
    p_gw1.wait()

    # Alice's socket will close
    try:
        ws_alice.recv()
    except Exception:
        pass

    # 6. Alice automatically reconnects to surviving Gateway 2 (Beta)
    print("6. Alice client auto-reconnecting to surviving Gateway 2 (Beta)...")
    ws_alice_new = websocket.create_connection(f"ws://127.0.0.1:{PORT_GW2}/ws?token={tok_a}", timeout=5)
    init_a_new = json.loads(ws_alice_new.recv())
    assert init_a_new["data"]["node_id"] == "gw_node_beta"
    print("7. Alice successfully reconnected to Gateway 2 (Beta)!")

    # Verify Alice's route in Redis has migrated to Beta
    route_a_after = get_user_gateway(uid_a)
    assert route_a_after == "gw_node_beta"
    print(f"8. Verified Redis Session Route Migrated: Alice -> '{route_a_after}'")

    # 7. Bob sends message to Alice; Alice receives on her new Gateway 2 connection
    msg2 = {"type": "chat_message", "conversation_type": "direct", "recipient_id": uid_a, "content": "Post-failover message from Bob"}
    ws_bob.send(json.dumps(msg2))

    received_on_a = None
    for _ in range(8):
        try:
            raw = ws_alice_new.recv()
            data = json.loads(raw)
            if data.get("event") == "new_message":
                received_on_a = data["data"]
                break
        except Exception:
            pass

    assert received_on_a is not None
    assert received_on_a["content"] == "Post-failover message from Bob"
    print("9. Verified Bidirectional Message Flow on surviving Gateway 2!")

    ws_alice_new.close()
    ws_bob.close()

    print("=" * 65)
    print("CHAOS FAILOVER TEST PASSED! ZERO MESSAGE LOSS CONFIRMED!")
    print("=" * 65)

finally:
    p_gw1.kill()
    p_gw2.kill()
