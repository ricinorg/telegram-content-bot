import sqlite3
from datetime import datetime, timezone
from pathlib import Path

class Database:
    def __init__(self,path):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True); self._init()
    def _connect(self): return sqlite3.connect(self.path)
    def _init(self):
        with self._connect() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS posts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,prompt TEXT NOT NULL,text TEXT NOT NULL,
            image_path TEXT,status TEXT NOT NULL DEFAULT 'draft',scheduled_at TEXT,
            created_at TEXT NOT NULL,published_at TEXT)'''); c.commit()
    def create_post(self,prompt,text,image_path=None):
        with self._connect() as c:
            cur=c.execute("INSERT INTO posts(prompt,text,image_path,created_at) VALUES(?,?,?,?)",
                          (prompt,text,image_path,datetime.now(timezone.utc).isoformat()))
            c.commit(); return cur.lastrowid
    def get_post(self,i):
        with self._connect() as c:
            return c.execute("SELECT id,prompt,text,image_path,status,scheduled_at,created_at,published_at FROM posts WHERE id=?",(i,)).fetchone()
    def update_post(self,i,status):
        pub=datetime.now(timezone.utc).isoformat() if status=="published" else None
        with self._connect() as c:
            c.execute("UPDATE posts SET status=?,published_at=? WHERE id=?",(status,pub,i)); c.commit()
