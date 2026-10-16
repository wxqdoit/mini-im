import os

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "mini-im-super-secret-key-2026")
    JWT_EXPIRATION_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", "72"))
    
    # PostgreSQL Configuration
    PG_HOST = os.getenv("POSTGRES_HOST", "127.0.0.1")
    PG_PORT = int(os.getenv("POSTGRES_PORT", "5433"))
    PG_USER = os.getenv("POSTGRES_USER", "postgres")
    PG_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgrespassword")
    PG_DB = os.getenv("POSTGRES_DB", "mini_im_db")
    
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
    # Public URL prefix for browser access
    MINIO_PUBLIC_URL = os.getenv("MINIO_PUBLIC_URL", "http://127.0.0.1:9000")
