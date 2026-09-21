import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class Database:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self):
        return sqlite3.connect(self.path)

    def _init(self):
        with self._connect() as conn:
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prompt TEXT NOT NULL,
                    text TEXT NOT NULL,
                    image_path TEXT,
                    status TEXT NOT NULL DEFAULT 'draft',
                    scheduled_at TEXT,
                    created_at TEXT NOT NULL,
                    published_at TEXT
                )
                '''
            )
            conn.commit()

    def create_post(self, prompt: str, text: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO posts(prompt, text, created_at) VALUES (?, ?, ?)",
                (prompt, text, now),
            )
            conn.commit()
            return int(cur.lastrowid)

    def get_post(self, post_id: int):
        with self._connect() as conn:
            return conn.execute(
                "SELECT id, prompt, text, image_path, status, scheduled_at, created_at, published_at "
                "FROM posts WHERE id = ?",
                (post_id,),
            ).fetchone()

    def update_post(self, post_id: int, status: str):
        published_at = (
            datetime.now(timezone.utc).isoformat()
            if status == "published"
            else None
        )
        with self._connect() as conn:
            conn.execute(
                "UPDATE posts SET status = ?, published_at = ? WHERE id = ?",
                (status, published_at, post_id),
            )
            conn.commit()
