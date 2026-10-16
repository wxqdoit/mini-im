import time
import requests
import json
from concurrent.futures import ThreadPoolExecutor

BASE_URL = "http://127.0.0.1:5001/api"

def main():
    print("=" * 65)
    print("MINI IM HIGH-THROUGHPUT PIPELINE (TPS) BENCHMARK")
    print("Testing: Multi-User Concurrent Ingestion + Kafka Batching + Partitioned DB")
    print("=" * 65)

    # Use seeded users
    seeded_users = ["alice", "bob", "charlie", "diana"]
    tokens = []
    
    print("Logging into pre-seeded accounts...")
    for u in seeded_users:
        r = requests.post(f"{BASE_URL}/auth/login", json={"username": u, "password": "123456"})
        if r.status_code == 200:
            tok = r.json()["token"]
            uid = r.json()["user"]["id"]
            tokens.append({"username": u, "token": tok, "id": uid, "headers": {"Authorization": f"Bearer {tok}"}})
    
    print(f"Logged into {len(tokens)} sender accounts successfully!")
    recipient = tokens[0]  # alice is recipient
    senders = tokens[1:]   # bob, charlie, diana are senders

    MSGS_PER_SENDER = 25
    TOTAL_MESSAGES = len(senders) * MSGS_PER_SENDER

    print(f"Blasting {TOTAL_MESSAGES} messages from {len(senders)} senders to {recipient['username']}...")
    success_count = [0]
    errors = [0]

    tasks = []
    for s in senders:
        for m_idx in range(MSGS_PER_SENDER):
            tasks.append((s["headers"], s["id"], m_idx))

    def send_task(item):
        hdrs, sender_id, m_idx = item
        payload = {
            "conversation_type": "direct",
            "recipient_id": recipient["id"],
            "msg_type": "text",
            "content": f"Benchmark message #{m_idx} from sender {sender_id}"
        }
        try:
            r = requests.post(f"{BASE_URL}/messages/send", headers=hdrs, json=payload, timeout=5)
            if r.status_code == 200:
                success_count[0] += 1
            else:
                errors[0] += 1
        except Exception:
            errors[0] += 1

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=10) as ex:
        list(ex.map(send_task, tasks))
    t_send = time.time() - t0

    tps = success_count[0] / t_send if t_send > 0 else 0
    print(f"Ingestion Result: {success_count[0]} / {TOTAL_MESSAGES} msgs sent successfully in {t_send:.3f}s -> {tps:.2f} TPS!")

    # Allow Kafka micro-batch consumer to persist into PostgreSQL
    time.sleep(1.0)

    # Verify messages in partitioned table via /sync
    sync_res = requests.get(f"{BASE_URL}/messages/sync?type=direct&target_id={recipient['id']}&last_seq_id=0&limit=100", headers=senders[0]["headers"])
    assert sync_res.status_code == 200
    print(f"PostgreSQL Partitioned Table Verified: {sync_res.json()['count']} messages delta synchronized via SeqID.")

    print("=" * 65)
    print(f"BENCHMARK COMPLETE! Ingestion Rate: {tps:.2f} TPS | Errors: {errors[0]}")
    print("=" * 65)

if __name__ == "__main__":
    main()
