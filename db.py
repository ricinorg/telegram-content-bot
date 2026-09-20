from pathlib import Path
import sqlite3
from contextlib import contextmanager


SCHEMA = '''
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt TEXT NOT NULL,
    text TEXT,
    image_path TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    scheduled_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    published_at TEXT
);
'''


class Database:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def create_post(self, prompt: str, text: str | None = None) -> int:
        with self.connection() as conn:
            cur = conn.execute(
                "INSERT INTO posts(prompt, text) VALUES(?, ?)",
                (prompt, text),
            )
            return int(cur.lastrowid)

    def get_post(self, post_id: int):
        with self.connection() as conn:
            return conn.execute(
                "SELECT id, prompt, text, image_path, status, scheduled_at, created_at, published_at "
                "FROM posts WHERE id = ?",
                (post_id,),
            ).fetchone()

    def update_post(self, post_id: int, **fields) -> None:
        allowed = {"text", "image_path", "status", "scheduled_at", "published_at"}
        fields = {k: v for k, v in fields.items() if k in allowed}
        if not fields:
            return
        clause = ", ".join(f"{key} = ?" for key in fields)
        with self.connection() as conn:
            conn.execute(
                f"UPDATE posts SET {clause} WHERE id = ?",
                (*fields.values(), post_id),
            )
