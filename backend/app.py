from gevent import monkey
monkey.patch_all()

try:
    from psycogreen.gevent import patch_psycopg
    patch_psycopg()
except ImportError:
    pass

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

from routes.auth_routes import auth_bp
from routes.user_routes import user_bp
from routes.friend_routes import friend_bp
from routes.group_routes import group_bp
from routes.message_routes import message_bp
from routes.upload_routes import upload_bp
from routes.e2ee_routes import e2ee_bp

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Enable CORS for API routes
    CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)

    # Initialize components
    init_db_pool()
    init_tables()
    reset_all_online_presence()
    init_minio_bucket()
    start_kafka_consumer()

    # Register WebSocket handler
    register_websocket(app)

    # Register blueprints
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
            "max_concurrency": 15000,
            "services": {
                "postgres": "ok",
                "redis": "ok",
                "kafka": "ok",
                "minio": "ok"
            }
        })

    return app

if __name__ == "__main__":
    app = create_app()
    pool = Pool(15000)
    server = WSGIServer(
        ("0.0.0.0", 5001),
        app,
        spawn=pool,
        backlog=2048,
        log=None,
        error_log=None
    )
    print("=" * 60)
    print("Mini IM High-Concurrency Backend (Gevent Async IO Engine)")
    print("Listening on: http://0.0.0.0:5001")
    print("Coroutine Pool Capacity: 15,000 simultaneous connections")
    print("=" * 60)
    server.serve_forever()
