import os
os.environ["SERVICE_ROLE"] = "gateway"
from app import create_app
from gevent.pywsgi import WSGIServer
from gevent.pool import Pool
from config import Config

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5002"))
    app = create_app("gateway")
    pool = Pool(15000)
    server = WSGIServer(("0.0.0.0", port), app, spawn=pool, backlog=2048)
    print(f"Mini IM WebSocket Gateway [{Config.NODE_ID}] started on ws://0.0.0.0:{port}/ws")
    server.serve_forever()
