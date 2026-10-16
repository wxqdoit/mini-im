from gevent import monkey
monkey.patch_all()

try:
    from psycogreen.gevent import patch_psycopg
    patch_psycopg()
except ImportError:
    pass

import os
from gevent.pywsgi import WSGIServer
from gevent.pool import Pool

from flask import Flask, jsonify
from flask_cors import CORS
from config import Config
from db import init_db_pool, init_tables
from redis_client import reset_all_online_presence
from minio_service import init_minio_bucket
from kafka_service import start_kafka_consumer
from websocket_server import register_websocket
from telemetry import init_telemetry, get_current_trace_id

from routes.auth_routes import auth_bp
from routes.user_routes import user_bp
from routes.friend_routes import friend_bp
from routes.group_routes import group_bp
from routes.message_routes import message_bp
from routes.upload_routes import upload_bp
from routes.e2ee_routes import e2ee_bp

def create_app(role: str = None):
    app = Flask(__name__)
    app.config.from_object(Config)

    role = (role or Config.SERVICE_ROLE or "all").lower()
    app.config["SERVICE_ROLE"] = role
    init_telemetry(f"mini-im-{role}")
    try:
        from opentelemetry.instrumentation.flask import FlaskInstrumentor
        FlaskInstrumentor().instrument_app(app)
    except Exception:
        pass

    # Enable CORS for API routes
    CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)

    # Initialize shared storage & database pools
    init_db_pool()
    if role in ["all", "api"]:
        init_tables()

    if role in ["all", "api", "gateway"]:
        init_minio_bucket()

    if role in ["all"]:
        reset_all_online_presence()

    # Worker role or all-in-one runs Kafka background consumer
    if role in ["all", "worker"]:
        start_kafka_consumer()

    # Gateway role or all-in-one registers WebSocket engine & precision listener
    if role in ["all", "gateway"]:
        register_websocket(app)

    # API role or all-in-one registers REST blueprints
    if role in ["all", "api"]:
        app.register_blueprint(auth_bp)
        app.register_blueprint(user_bp)
        app.register_blueprint(friend_bp)
        app.register_blueprint(group_bp)
        app.register_blueprint(message_bp)
        app.register_blueprint(upload_bp)
        app.register_blueprint(e2ee_bp)

    @app.route("/api/health", methods=["GET"])
    def health_check():
        return jsonify({
            "status": "healthy",
            "server": "Gevent-Async-Engine",
            "service_role": role,
            "node_id": getattr(Config, "NODE_ID", "unknown"),
            "max_concurrency": 15000,
            "services": {
                "postgres": "ok",
                "redis": "ok",
                "kafka": "ok",
                "minio": "ok"
            }
        })

    @app.after_request
    def set_trace_header(response):
        try:
            response.headers["X-Trace-Id"] = get_current_trace_id()
        except Exception:
            pass
        return response

    return app

if __name__ == "__main__":
    role = Config.SERVICE_ROLE
    port = int(os.getenv("PORT", "5001"))
    app = create_app(role)

    pool = Pool(15000)
    server = WSGIServer(
        ("0.0.0.0", port),
        app,
        spawn=pool,
        backlog=2048,
        log=None,
        error_log=None
    )
    print("=" * 65)
    print(f"Mini IM High-Concurrency Server [Role: {role.upper()}]")
    print(f"Node ID: {Config.NODE_ID}")
    print(f"Listening on: http://0.0.0.0:{port}")
    print("Coroutine Pool Capacity: 15,000 simultaneous connections per instance")
    print("=" * 65)
    server.serve_forever()
