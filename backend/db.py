import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor, execute_values
import json
from contextlib import contextmanager
from config import Config

# Cooperatively patch psycopg2 for gevent if gevent is running
try:
    from psycogreen.gevent import patch_psycopg
    patch_psycopg()
except ImportError:
    pass

connection_pool = None

def init_db_pool():
    global connection_pool
    if connection_pool is None:
        connection_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=Config.PG_MIN_CONN,
            maxconn=Config.PG_MAX_CONN,
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
    conn = None
    import time
    for attempt in range(5):
        try:
            conn = connection_pool.getconn()
            break
        except Exception:
            time.sleep(0.02 * (attempt + 1))
    if conn is None:
        conn = connection_pool.getconn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        if conn is not None:
            connection_pool.putconn(conn)


def ensure_monthly_partitions():
    """
    Guarantees current and upcoming monthly partitions exist, plus a DEFAULT fallback partition.
    """
    import datetime
    now = datetime.datetime.utcnow()
    with get_db() as cur:
        # Check if messages table is partitioned
        cur.execute("SELECT relkind FROM pg_class WHERE relname = 'messages';")
        row = cur.fetchone()
        if not row or row['relkind'] != 'p':
            return

        # Ensure default partition exists
        cur.execute("CREATE TABLE IF NOT EXISTS messages_default PARTITION OF messages DEFAULT;")

        # Create partitions for current month + next 3 months
        for m_offset in range(4):
            # Calculate year and month
            year = now.year + (now.month - 1 + m_offset) // 12
            month = (now.month - 1 + m_offset) % 12 + 1
            part_name = f"messages_{year}_{month:02d}"
            
            start_date = f"{year}-{month:02d}-01 00:00:00"
            if month == 12:
                end_date = f"{year + 1}-01-01 00:00:00"
            else:
                end_date = f"{year}-{month + 1:02d}-01 00:00:00"
                
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {part_name} PARTITION OF messages
                FOR VALUES FROM ('{start_date}') TO ('{end_date}');
            """)

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

    CREATE INDEX IF NOT EXISTS idx_group_members_group 
    ON group_members(group_id);

    CREATE INDEX IF NOT EXISTS idx_group_members_user 
    ON group_members(user_id);

    CREATE INDEX IF NOT EXISTS idx_messages_unread 
    ON messages(recipient_id, conversation_type, is_read)
    WHERE is_read = FALSE;

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
    ALTER TABLE messages ADD COLUMN IF NOT EXISTS seq_id BIGINT DEFAULT 0;

    CREATE INDEX IF NOT EXISTS idx_messages_seq_direct 
    ON messages(sender_id, recipient_id, seq_id)
    WHERE conversation_type = 'direct';

    CREATE INDEX IF NOT EXISTS idx_messages_seq_group 
    ON messages(recipient_id, seq_id)
    WHERE conversation_type = 'group';
    """
    with get_db() as cur:
        cur.execute(create_schema_sql)
    ensure_monthly_partitions()
    init_user_devices_table()
    print("Database tables, partitions, indexes & user_devices initialized successfully!")


def bulk_insert_messages(messages_list):
    """
    High-throughput micro-batching message persistence using execute_values.
    Inserts a list of messages in a single DB round-trip transaction.
    """
    if not messages_list:
        return []
    
    tuples_to_insert = []
    sender_ids = set()
    for m in messages_list:
        sender_ids.add(m.get("sender_id"))
        ekb = m.get("encrypted_key_bundle")
        if isinstance(ekb, dict):
            ekb_json = json.dumps(ekb)
        else:
            ekb_json = ekb
        tuples_to_insert.append((
            m.get("conversation_type"),
            m.get("sender_id"),
            m.get("recipient_id"),
            m.get("msg_type", "text"),
            m.get("content", ""),
            m.get("media_url", ""),
            m.get("file_name", ""),
            m.get("file_size", 0),
            False,
            m.get("is_encrypted", False),
            m.get("iv", ""),
            m.get("ephemeral_key", ""),
            ekb_json,
            m.get("seq_id", 0)
        ))

    sql = """
        INSERT INTO messages (
            conversation_type, sender_id, recipient_id,
            msg_type, content, media_url, file_name, file_size,
            is_read, is_encrypted, iv, ephemeral_key, encrypted_key_bundle, seq_id
        ) VALUES %s
        RETURNING id, conversation_type, sender_id, recipient_id, msg_type, content,
                  media_url, file_name, file_size, is_read, is_encrypted, iv,
                  ephemeral_key, encrypted_key_bundle, seq_id, created_at;
    """

    with get_db() as cur:
        sender_map = {}
        if sender_ids:
            cur.execute("SELECT id, username, nickname, avatar FROM users WHERE id = ANY(%s)", (list(sender_ids),))
            for row in cur.fetchall():
                sender_map[row["id"]] = dict(row)

        inserted_rows = execute_values(cur, sql, tuples_to_insert, fetch=True)
        result = []
        for row in inserted_rows:
            m_dict = dict(row)
            if m_dict.get("created_at"):
                m_dict["created_at"] = m_dict["created_at"].isoformat()
            m_dict["sender"] = sender_map.get(m_dict["sender_id"])
            result.append(m_dict)
        return result

def init_user_devices_table():
    sql = """
    CREATE TABLE IF NOT EXISTS user_devices (
        id SERIAL PRIMARY KEY,
        user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        platform VARCHAR(20) NOT NULL,
        device_token VARCHAR(255) NOT NULL,
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT uq_user_device UNIQUE (user_id, device_token)
    );

    CREATE INDEX IF NOT EXISTS idx_user_devices_user 
    ON user_devices(user_id) 
    WHERE is_active = TRUE;
    """
    with get_db() as cur:
        cur.execute(sql)
