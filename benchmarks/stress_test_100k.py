from gevent import monkey
monkey.patch_all()
import time
import argparse
import json
import statistics
import websocket
import jwt
import datetime
import gevent
from gevent.pool import Pool

SECRET_KEY = "mini-im-super-secret-key-2026-production-grade-64-bytes-token"

def generate_bench_token(user_id):
    payload = {
        "user_id": user_id,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=24),
        "iat": datetime.datetime.utcnow()
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")

def parse_args():
    parser = argparse.ArgumentParser(description="Mini IM 100k Concurrent WebSocket Stress Tester")
    parser.add_argument("--host", default="127.0.0.1:5001", help="Host:Port to target")
    parser.add_argument("--connections", type=int, default=500, help="Number of concurrent WS connections")
    parser.add_argument("--duration", type=int, default=15, help="Duration in seconds to hold connections & ping")
    parser.add_argument("--ping-interval", type=int, default=5, help="Ping interval in seconds")
    return parser.parse_args()

stats = {
    "connected": 0,
    "failed": 0,
    "pings_sent": 0,
    "pongs_received": 0,
    "latencies": []
}

def register_user(host, index):
    username = f"bench_user_{int(time.time())}_{index}"
    url = f"http://{host}/api/auth/register"
    payload = {"username": username, "password": "benchpass123", "nickname": f"Bench User {index}"}
    try:
        res = requests.post(url, json=payload, timeout=5)
        if res.status_code == 201:
            return res.json()["token"], res.json()["user"]["id"]
    except Exception:
        pass
    return None, None

def client_worker(host, token, user_id, duration, ping_interval):
    ws_url = f"ws://{host}/ws?token={token}"
    try:
        ws = websocket.create_connection(ws_url, timeout=5)
        init_raw = ws.recv()
        stats["connected"] += 1
        
        end_time = time.time() + duration
        while time.time() < end_time:
            t0 = time.time()
            ws.send(json.dumps({"type": "ping"}))
            stats["pings_sent"] += 1
            
            raw_pong = ws.recv()
            t1 = time.time()
            rtt_ms = (t1 - t0) * 1000.0
            stats["pongs_received"] += 1
            stats["latencies"].append(rtt_ms)
            
            gevent.sleep(ping_interval)
            
        ws.close()
    except Exception as e:
        stats["failed"] += 1
        if stats["failed"] <= 3: print("WORKER EXCEPTION:", type(e), e)

def main():
    args = parse_args()
    print("=" * 65)
    print(f"MINI IM WEBSOCKET STRESS TEST: {args.connections} TARGET CONNECTIONS")
    print(f"Target: http://{args.host} | Duration: {args.duration}s | Ping Interval: {args.ping_interval}s")
    print("=" * 65)

    print("Phase 1: Instant provisioning of JWT tokens & Redis Profile Cache...")
    users = []
    base_uid = 900000
    from redis_client import cache_user_profile
    for i in range(args.connections):
        uid = base_uid + i
        tok = generate_bench_token(uid)
        cache_user_profile({
            "id": uid,
            "username": f"stress_user_{uid}",
            "nickname": f"Stress User {uid}",
            "avatar": "",
            "bio": "",
            "status": "online"
        })
        users.append((tok, uid))

    print(f"Provisioned {len(users)} users successfully!")
    if not users:
        print("Failed to provision users. Aborting.")
        return

    print(f"Phase 2: Ramping up {len(users)} concurrent WebSocket connections...")
    ws_pool = Pool(len(users))
    t_start = time.time()
    
    for tok, uid in users:
        ws_pool.spawn(client_worker, args.host, tok, uid, args.duration, args.ping_interval)
        gevent.sleep(0.02)  # Smooth 50 conn/sec ramp-up to prevent client-side socket congestion

    ws_pool.join()
    t_total = time.time() - t_start

    print("=" * 65)
    print("STRESS TEST SUMMARY REPORT:")
    print(f"Total Elapsed Time: {t_total:.2f}s")
    print(f"Successful Connections: {stats['connected']} / {len(users)}")
    print(f"Failed / Dropped: {stats['failed']}")
    print(f"Pings Sent: {stats['pings_sent']} | Pongs Received: {stats['pongs_received']}")

    if stats["latencies"]:
        lat = sorted(stats["latencies"])
        p50 = statistics.median(lat)
        p95 = lat[int(len(lat) * 0.95)]
        p99 = lat[int(len(lat) * 0.99)]
        avg = statistics.mean(lat)
        print(f"Ping-Pong RTT Latency: Avg={avg:.2f}ms | P50={p50:.2f}ms | P95={p95:.2f}ms | P99={p99:.2f}ms")
    print("=" * 65)

if __name__ == "__main__":
    main()
