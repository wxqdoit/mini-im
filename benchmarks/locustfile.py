from locust import HttpUser, task, between
import json
import websocket

class MiniIMLoadUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        import time
        self.username = f"locust_user_{int(time.time())}_{self.environment.runner.user_count}"
        res = self.client.post("/api/auth/register", json={
            "username": self.username,
            "password": "locustpass123",
            "nickname": "Locust User"
        })
        if res.status_code == 201:
            self.token = res.json()["token"]
            self.user_id = res.json()["user"]["id"]
            self.headers = {"Authorization": f"Bearer {self.token}"}
        else:
            self.token = None

    @task(3)
    def fetch_conversations(self):
        if self.token:
            self.client.get("/api/messages/conversations", headers=self.headers)

    @task(2)
    def search_users(self):
        if self.token:
            self.client.get("/api/users/search?q=alice", headers=self.headers)

    @task(5)
    def delta_sync(self):
        if self.token:
            self.client.get("/api/messages/sync?type=direct&target_id=1&last_seq_id=0", headers=self.headers)
