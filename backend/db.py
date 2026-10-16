import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from config import Config

connection_pool = None

def init_db_pool():
    global connection_pool
    if connection_pool is None:
        connection_pool = psycopg2.pool.SimpleConnectionPool(
            minconn=2,
            maxconn=20,
            host=Config.PG_HOST,
            port=Config.PG_PORT,
            dbname=Config.PG_DB,
            user=Config.PG_USER,
            password=Config.PG_PASSWORD
        )

@contextmanager
def get_db():
    if connection_pool is None:
        init_db_pool()
    conn = connection_pool.getconn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        connection_pool.putconn(conn)

def init_tables():
    create_schema_sql = """
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username VARCHAR(50) UNIQUE NOT NULL,
        password_hash VARCHAR(255) NOT NULL,
        nickname VARCHAR(100) NOT NULL,
        avatar VARCHAR(500) DEFAULT '',
        bio TEXT DEFAULT '',
        status VARCHAR(20) DEFAULT 'offline',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS friendships (
        id SERIAL PRIMARY KEY,
        user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        friend_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT uq_friendship UNIQUE (user_id, friend_id)
    );

    CREATE TABLE IF NOT EXISTS friend_requests (
        id SERIAL PRIMARY KEY,
        sender_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        receiver_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        status VARCHAR(20) DEFAULT 'pending',
        message TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS groups (
        id SERIAL PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        avatar VARCHAR(500) DEFAULT '',
        description TEXT DEFAULT '',
        owner_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS group_members (
        id SERIAL PRIMARY KEY,
        group_id INT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
        user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        role VARCHAR(20) DEFAULT 'member',
        joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT uq_group_member UNIQUE (group_id, user_id)
    );

    CREATE TABLE IF NOT EXISTS messages (
        id SERIAL PRIMARY KEY,
        conversation_type VARCHAR(20) NOT NULL,
        sender_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        recipient_id INT NOT NULL,
        msg_type VARCHAR(20) DEFAULT 'text',
        content TEXT DEFAULT '',
        media_url VARCHAR(500) DEFAULT '',
        file_name VARCHAR(255) DEFAULT '',
        file_size BIGINT DEFAULT 0,
        is_read BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_messages_direct 
    ON messages(sender_id, recipient_id, created_at)
    WHERE conversation_type = 'direct';

    CREATE INDEX IF NOT EXISTS idx_messages_group 
    ON messages(recipient_id, created_at)
    WHERE conversation_type = 'group';

    CREATE INDEX IF NOT EXISTS idx_friendships_user 
    ON friendships(user_id);

    
    CREATE TABLE IF NOT EXISTS user_keys (
        id SERIAL PRIMARY KEY,
        user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE UNIQUE,
        identity_public_key TEXT NOT NULL,
        signed_prekey TEXT DEFAULT '',
        prekey_signature TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS group_e2ee_keys (
        id SERIAL PRIMARY KEY,
        group_id INT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
        key_version INT DEFAULT 1,
        encrypted_keys JSONB NOT NULL,
        created_by INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT uq_group_key_version UNIQUE (group_id, key_version)
    );

    ALTER TABLE messages ADD COLUMN IF NOT EXISTS is_encrypted BOOLEAN DEFAULT FALSE;
    ALTER TABLE messages ADD COLUMN IF NOT EXISTS iv VARCHAR(64) DEFAULT '';
    ALTER TABLE messages ADD COLUMN IF NOT EXISTS ephemeral_key TEXT DEFAULT '';
    ALTER TABLE messages ADD COLUMN IF NOT EXISTS encrypted_key_bundle JSONB DEFAULT NULL;

    CREATE INDEX IF NOT EXISTS idx_group_members_group 
    ON group_members(group_id);
    """
    with get_db() as cur:
        cur.execute(create_schema_sql)
    print("Database tables initialized successfully!")
