import os
os.environ["SERVICE_ROLE"] = "api"
from app import create_app
from gevent.pywsgi import WSGIServer
from gevent.pool import Pool
from config import Config

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5001"))
    app = create_app("api")
    pool = Pool(15000)
    server = WSGIServer(("0.0.0.0", port), app, spawn=pool, backlog=2048)
    print(f"Mini IM API Microservice started on http://0.0.0.0:{port}")
    server.serve_forever()
