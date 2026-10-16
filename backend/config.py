import os
import warnings

class Config:
    # In production, SECRET_KEY must be provided via environment variables.
    SECRET_KEY = os.getenv("SECRET_KEY", "mini-im-super-secret-key-2026-production-grade-64-bytes-token")
    ENV = os.getenv("ENV", "development")
    if ENV == "production" and SECRET_KEY == "mini-im-super-secret-key-2026-production-grade-64-bytes-token":
        raise RuntimeError("FATAL: In production, SECRET_KEY must be explicitly set via environment variable.")

    JWT_EXPIRATION_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", "72"))
    
    # PostgreSQL Configuration with thread-safe pool sizing
    PG_HOST = os.getenv("POSTGRES_HOST", "127.0.0.1")
    PG_PORT = int(os.getenv("POSTGRES_PORT", "5433"))
    PG_USER = os.getenv("POSTGRES_USER", "postgres")
    PG_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgrespassword")
    PG_DB = os.getenv("POSTGRES_DB", "mini_im_db")
    PG_MIN_CONN = int(os.getenv("PG_MIN_CONN", "5"))
    PG_MAX_CONN = int(os.getenv("PG_MAX_CONN", "100"))
    
    # Redis Configuration
    REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
    REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)
    
    # Kafka Configuration
    KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:9092")
    KAFKA_MSG_TOPIC = os.getenv("KAFKA_MSG_TOPIC", "mini_im_messages")
    KAFKA_CONSUMER_GROUP = os.getenv("KAFKA_CONSUMER_GROUP", "mini_im_consumer_group")
    
    # MinIO Configuration
    MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "127.0.0.1:9000")
    MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
    MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadminpassword")
    MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"
    MINIO_BUCKET = os.getenv("MINIO_BUCKET", "mini-im-media")
    MINIO_PUBLIC_URL = os.getenv("MINIO_PUBLIC_URL", "http://127.0.0.1:9000")

    # Security & Upload Configuration
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", str(25 * 1024 * 1024)))  # 25 MB max payload
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "svg", "pdf", "txt", "doc", "docx", "xls", "xlsx", "zip", "mp4", "mp3"}
