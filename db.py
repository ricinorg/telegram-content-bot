import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path


def now_iso():
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self):
        return sqlite3.connect(self.path)

    def _init(self):
        with self._connect() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS posts(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                prompt TEXT NOT NULL,
                text TEXT NOT NULL,
                image_path TEXT,
                status TEXT NOT NULL DEFAULT 'draft',
                scheduled_at TEXT,
                created_at TEXT NOT NULL,
                published_at TEXT
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS topic_nodes(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                parent_id INTEGER,
                depth INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                source_post_id INTEGER,
                created_at TEXT NOT NULL,
                used_at TEXT
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS automation(
                id INTEGER PRIMARY KEY CHECK(id=1),
                active INTEGER NOT NULL DEFAULT 0,
                root_topic TEXT,
                last_post_id INTEGER,
                next_run_at TEXT
            )""")
            c.execute("INSERT OR IGNORE INTO automation(id, active) VALUES(1,0)")
            c.commit()

    def create_post(self, prompt, text, image_path=None, scheduled_at=None):
        with self._connect() as c:
            cur = c.execute(
                "INSERT INTO posts(prompt,text,image_path,scheduled_at,created_at) VALUES(?,?,?,?,?)",
                (prompt, text, image_path, scheduled_at, now_iso()),
            )
            c.commit()
            return cur.lastrowid

    def get_post(self, i):
        with self._connect() as c:
            return c.execute(
                "SELECT id,prompt,text,image_path,status,scheduled_at,created_at,published_at "
                "FROM posts WHERE id=?", (i,)
            ).fetchone()

    def update_post(self, i, status):
        pub = now_iso() if status == "published" else None
        with self._connect() as c:
            c.execute("UPDATE posts SET status=?,published_at=? WHERE id=?", (status, pub, i))
            c.commit()

    def add_topic(self, topic, parent_id=None, depth=0, source_post_id=None):
        topic = topic.strip()
        if not topic:
            return None
        normalized = " ".join(topic.casefold().split())
        with self._connect() as c:
            rows = c.execute(
                "SELECT id,topic FROM topic_nodes WHERE status!='used'"
            ).fetchall()
            for rid, existing in rows:
                if " ".join(existing.casefold().split()) == normalized:
                    return rid
            cur = c.execute(
                "INSERT INTO topic_nodes(topic,parent_id,depth,status,source_post_id,created_at) "
                "VALUES(?,?,?,?,?,?)",
                (topic, parent_id, depth, "pending", source_post_id, now_iso()),
            )
            c.commit()
            return cur.lastrowid

    def add_topics(self, topics, parent_id=None, depth=0, source_post_id=None):
        ids = []
        for topic in topics:
            rid = self.add_topic(topic, parent_id, depth, source_post_id)
            if rid:
                ids.append(rid)
        return ids

    def claim_next_topic(self):
        with self._connect() as c:
            row = c.execute(
                "SELECT id,topic,parent_id,depth FROM topic_nodes "
                "WHERE status='pending' ORDER BY depth ASC,id ASC LIMIT 1"
            ).fetchone()
            if not row:
                return None
            c.execute(
                "UPDATE topic_nodes SET status='processing' WHERE id=? AND status='pending'",
                (row[0],)
            )
            c.commit()
            return row

    def mark_topic_used(self, topic_id):
        with self._connect() as c:
            c.execute(
                "UPDATE topic_nodes SET status='used',used_at=? WHERE id=?",
                (now_iso(), topic_id)
            )
            c.commit()

    def reset_processing(self):
        with self._connect() as c:
            c.execute("UPDATE topic_nodes SET status='pending' WHERE status='processing'")
            c.commit()

    def get_topic(self, topic_id):
        with self._connect() as c:
            return c.execute(
                "SELECT id,topic,parent_id,depth,status,source_post_id,created_at,used_at "
                "FROM topic_nodes WHERE id=?", (topic_id,)
            ).fetchone()

    def get_last_post_text(self):
        with self._connect() as c:
            row = c.execute(
                "SELECT text FROM posts WHERE status='published' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return row[0] if row else None

    def start_automation(self, root_topic, next_run_at):
        with self._connect() as c:
            c.execute(
                "UPDATE automation SET active=1,root_topic=?,next_run_at=? WHERE id=1",
                (root_topic, next_run_at),
            )
            c.commit()

    def stop_automation(self):
        with self._connect() as c:
            c.execute("UPDATE automation SET active=0,next_run_at=NULL WHERE id=1")
            c.commit()

    def set_next_run(self, next_run_at):
        with self._connect() as c:
            c.execute("UPDATE automation SET next_run_at=? WHERE id=1", (next_run_at,))
            c.commit()

    def get_automation(self):
        with self._connect() as c:
            return c.execute(
                "SELECT active,root_topic,last_post_id,next_run_at FROM automation WHERE id=1"
            ).fetchone()

    def set_last_post(self, post_id):
        with self._connect() as c:
            c.execute("UPDATE automation SET last_post_id=? WHERE id=1", (post_id,))
            c.commit()

    def stats(self):
        with self._connect() as c:
            pending = c.execute("SELECT COUNT(*) FROM topic_nodes WHERE status='pending'").fetchone()[0]
            used = c.execute("SELECT COUNT(*) FROM topic_nodes WHERE status='used'").fetchone()[0]
            posts = c.execute("SELECT COUNT(*) FROM posts WHERE status='published'").fetchone()[0]
            return posts, pending, used
