from db import get_db, init_tables
from auth import hash_password

def seed():
    init_tables()
    pwd_hash = hash_password("123456")

    demo_users = [
        ("alice", pwd_hash, "爱丽丝 Alice", "https://api.dicebear.com/7.x/bottts/svg?seed=Alice", "全栈开发工程师 & 设计爱好者 🚀"),
        ("bob", pwd_hash, "鲍勃 Bob", "https://api.dicebear.com/7.x/bottts/svg?seed=Bob", "Python / 分布式架构师 💻"),
        ("charlie", pwd_hash, "查理 Charlie", "https://api.dicebear.com/7.x/bottts/svg?seed=Charlie", "产品经理 & 极客 📱"),
        ("diana", pwd_hash, "戴安娜 Diana", "https://api.dicebear.com/7.x/bottts/svg?seed=Diana", "UI/UX 设计师 🎨")
    ]

    with get_db() as cur:
        # Insert users
        user_ids = {}
        for username, p_hash, nickname, avatar, bio in demo_users:
            cur.execute("""
                INSERT INTO users (username, password_hash, nickname, avatar, bio, status)
                VALUES (%s, %s, %s, %s, %s, 'offline')
                ON CONFLICT (username) DO UPDATE 
                SET nickname = EXCLUDED.nickname, avatar = EXCLUDED.avatar, bio = EXCLUDED.bio
                RETURNING id, username;
            """, (username, p_hash, nickname, avatar, bio))
            row = cur.fetchone()
            user_ids[username] = row["id"]

        alice_id = user_ids["alice"]
        bob_id = user_ids["bob"]
        charlie_id = user_ids["charlie"]
        diana_id = user_ids["diana"]

        # Insert friendships: Alice <-> Bob, Alice <-> Charlie
        cur.execute("""
            INSERT INTO friendships (user_id, friend_id) VALUES
            (%s, %s), (%s, %s),
            (%s, %s), (%s, %s)
            ON CONFLICT DO NOTHING;
        """, (alice_id, bob_id, bob_id, alice_id, alice_id, charlie_id, charlie_id, alice_id))

        # Insert a pending friend request from Diana to Alice
        cur.execute("""
            INSERT INTO friend_requests (sender_id, receiver_id, status, message)
            VALUES (%s, %s, 'pending', 'Hi Alice! 我是戴安娜，想和你聊聊新项目的UI设计~')
            ON CONFLICT DO NOTHING;
        """, (diana_id, alice_id))

        # Insert groups
        cur.execute("""
            INSERT INTO groups (name, avatar, description, owner_id)
            VALUES (%s, %s, %s, %s)
            RETURNING id;
        """, (
            "技术极客探讨交流群 🚀", 
            "https://api.dicebear.com/7.x/shapes/svg?seed=TechGeek", 
            "探讨 Python, Postgres, Redis, Kafka, React 前沿架构实践！",
            alice_id
        ))
        tech_group_id = cur.fetchone()["id"]

        # Group members
        cur.execute("""
            INSERT INTO group_members (group_id, user_id, role) VALUES
            (%s, %s, 'owner'),
            (%s, %s, 'member'),
            (%s, %s, 'member')
            ON CONFLICT DO NOTHING;
        """, (tech_group_id, alice_id, tech_group_id, bob_id, tech_group_id, charlie_id))

        # Insert some initial messages
        cur.execute("""
            INSERT INTO messages (conversation_type, sender_id, recipient_id, msg_type, content, is_read)
            VALUES 
            ('direct', %s, %s, 'text', 'Hi Alice! 欢迎体验 Mini-IM 全栈系统，基于 Kafka + Postgres + Redis + MinIO！', TRUE),
            ('direct', %s, %s, 'text', '嗨 Bob！实时 WebSocket 和消息持久化都很顺畅 👍', TRUE),
            ('group', %s, %s, 'text', '欢迎大家加入【技术极客探讨交流群】！🎉', TRUE),
            ('group', %s, %s, 'text', 'Kafka 消费者与 Redis Pub/Sub 双重广播已就绪。', TRUE)
        """, (bob_id, alice_id, alice_id, bob_id, alice_id, tech_group_id, bob_id, tech_group_id))

    print(f"Seed data created successfully! Users: {list(user_ids.keys())}")

if __name__ == "__main__":
    seed()
