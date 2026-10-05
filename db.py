import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def now_iso():
    return datetime.now(timezone.utc).isoformat()


class Database:

    def __init__(self, path):
        self.path = Path(path)

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._init()

    def _connect(self):
        connection = sqlite3.connect(
            self.path,
            timeout=30,
        )

        connection.execute(
            "PRAGMA journal_mode=WAL"
        )

        connection.execute(
            "PRAGMA foreign_keys=ON"
        )

        return connection

    def _init(self):
        with self._connect() as c:

            c.execute(
                """
                CREATE TABLE IF NOT EXISTS posts(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prompt TEXT NOT NULL,
                    text TEXT NOT NULL,
                    image_path TEXT,
                    status TEXT NOT NULL DEFAULT 'draft',
                    scheduled_at TEXT,
                    created_at TEXT NOT NULL,
                    published_at TEXT
                )
                """
            )

            c.execute(
                """
                CREATE TABLE IF NOT EXISTS topic_nodes(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT NOT NULL,
                    parent_id INTEGER,
                    depth INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    source_post_id INTEGER,
                    created_at TEXT NOT NULL,
                    used_at TEXT
                )
                """
            )

            c.execute(
                """
                CREATE TABLE IF NOT EXISTS automation(
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    active INTEGER NOT NULL DEFAULT 0,
                    root_topic TEXT,
                    last_post_id INTEGER,
                    next_run_at TEXT,
                    start_time TEXT,
                    interval_hours INTEGER NOT NULL DEFAULT 4
                )
                """
            )

            c.execute(
                """
                CREATE TABLE IF NOT EXISTS content_feedback(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    post_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    note TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )

            columns = {
                row[1]
                for row in c.execute(
                    "PRAGMA table_info(automation)"
                ).fetchall()
            }

            if "start_time" not in columns:
                c.execute(
                    """
                    ALTER TABLE automation
                    ADD COLUMN start_time TEXT
                    """
                )

            if "interval_hours" not in columns:
                c.execute(
                    """
                    ALTER TABLE automation
                    ADD COLUMN interval_hours
                    INTEGER NOT NULL DEFAULT 4
                    """
                )

            c.execute(
                """
                INSERT OR IGNORE INTO automation(
                    id,
                    active,
                    interval_hours
                )
                VALUES(1, 0, 4)
                """
            )

            c.execute(
                """
                UPDATE automation
                SET interval_hours = 4
                WHERE interval_hours IS NULL
                   OR interval_hours < 1
                """
            )

            c.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_posts_status
                ON posts(status)
                """
            )

            c.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_posts_created
                ON posts(created_at)
                """
            )

            c.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_topics_status
                ON topic_nodes(status)
                """
            )

            c.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_topics_depth
                ON topic_nodes(depth)
                """
            )

            c.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_feedback_post
                ON content_feedback(post_id)
                """
            )

            c.commit()

    def create_post(
        self,
        prompt,
        text,
        image_path=None,
        scheduled_at=None,
    ):
        with self._connect() as c:
            cur = c.execute(
                """
                INSERT INTO posts(
                    prompt,
                    text,
                    image_path,
                    status,
                    scheduled_at,
                    created_at
                )
                VALUES(?,?,?,?,?,?)
                """,
                (
                    prompt,
                    text,
                    image_path,
                    "draft",
                    scheduled_at,
                    now_iso(),
                ),
            )

            c.commit()

            return cur.lastrowid

    def get_post(self, post_id):
        with self._connect() as c:
            return c.execute(
                """
                SELECT
                    id,
                    prompt,
                    text,
                    image_path,
                    status,
                    scheduled_at,
                    created_at,
                    published_at
                FROM posts
                WHERE id=?
                """,
                (post_id,),
            ).fetchone()

    def get_posts_by_status(
        self,
        status,
        limit=20,
    ):
        limit = max(1, int(limit))

        with self._connect() as c:
            return c.execute(
                """
                SELECT
                    id,
                    prompt,
                    text,
                    image_path,
                    status,
                    scheduled_at,
                    created_at,
                    published_at
                FROM posts
                WHERE status=?
                ORDER BY id DESC
                LIMIT ?
                """,
                (
                    status,
                    limit,
                ),
            ).fetchall()

    def update_post(
        self,
        post_id,
        status,
    ):
        published_at = (
            now_iso()
            if status == "published"
            else None
        )

        with self._connect() as c:
            c.execute(
                """
                UPDATE posts
                SET status=?,
                    published_at=?
                WHERE id=?
                """,
                (
                    status,
                    published_at,
                    post_id,
                ),
            )

            c.commit()

    def update_post_text(
        self,
        post_id,
        text,
    ):
        with self._connect() as c:
            c.execute(
                """
                UPDATE posts
                SET text=?
                WHERE id=?
                """,
                (
                    text,
                    post_id,
                ),
            )

            c.commit()

    def get_last_post_text(self):
        with self._connect() as c:
            row = c.execute(
                """
                SELECT text
                FROM posts
                WHERE status='published'
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()

            return row[0] if row else None

    def add_feedback(
        self,
        post_id,
        action,
        note=None,
    ):
        with self._connect() as c:
            c.execute(
                """
                INSERT INTO content_feedback(
                    post_id,
                    action,
                    note,
                    created_at
                )
                VALUES(?,?,?,?)
                """,
                (
                    post_id,
                    action,
                    note,
                    now_iso(),
                ),
            )

            c.commit()

    def add_topic(
        self,
        topic,
        parent_id=None,
        depth=0,
        source_post_id=None,
    ):
        if topic is None:
            return None

        topic = str(topic).strip()

        if not topic:
            return None

        normalized = " ".join(
            topic.casefold().split()
        )

        with self._connect() as c:
            rows = c.execute(
                """
                SELECT id, topic
                FROM topic_nodes
                WHERE status != 'used'
                """
            ).fetchall()

            for row_id, existing in rows:
                existing_normalized = " ".join(
                    existing.casefold().split()
                )

                if existing_normalized == normalized:
                    return row_id

            cur = c.execute(
                """
                INSERT INTO topic_nodes(
                    topic,
                    parent_id,
                    depth,
                    status,
                    source_post_id,
                    created_at
                )
                VALUES(?,?,?,?,?,?)
                """,
                (
                    topic,
                    parent_id,
                    depth,
                    "pending",
                    source_post_id,
                    now_iso(),
                ),
            )

            c.commit()

            return cur.lastrowid

    def add_topics(
        self,
        topics,
        parent_id=None,
        depth=0,
        source_post_id=None,
    ):
        ids = []

        if not topics:
            return ids

        for topic in topics:
            row_id = self.add_topic(
                topic,
                parent_id=parent_id,
                depth=depth,
                source_post_id=source_post_id,
            )

            if row_id:
                ids.append(row_id)

        return ids

    def claim_next_topic(self):
        with self._connect() as c:
            row = c.execute(
                """
                SELECT
                    id,
                    topic,
                    parent_id,
                    depth
                FROM topic_nodes
                WHERE status='pending'
                ORDER BY depth ASC, id ASC
                LIMIT 1
                """
            ).fetchone()

            if not row:
                return None

            updated = c.execute(
                """
                UPDATE topic_nodes
                SET status='processing'
                WHERE id=?
                  AND status='pending'
                """,
                (row[0],),
            )

            if updated.rowcount != 1:
                return None

            c.commit()

            return row

    def mark_topic_used(
        self,
        topic_id,
    ):
        with self._connect() as c:
            c.execute(
                """
                UPDATE topic_nodes
                SET status='used',
                    used_at=?
                WHERE id=?
                """,
                (
                    now_iso(),
                    topic_id,
                ),
            )

            c.commit()

    def reset_processing(self):
        with self._connect() as c:
            c.execute(
                """
                UPDATE topic_nodes
                SET status='pending'
                WHERE status='processing'
                """
            )

            c.commit()

    def get_topic(
        self,
        topic_id,
    ):
        with self._connect() as c:
            return c.execute(
                """
                SELECT
                    id,
                    topic,
                    parent_id,
                    depth,
                    status,
                    source_post_id,
                    created_at,
                    used_at
                FROM topic_nodes
                WHERE id=?
                """,
                (topic_id,),
            ).fetchone()

    def start_automation(
        self,
        root_topic,
        next_run_at,
        start_time=None,
        interval_hours=None,
    ):
        with self._connect() as c:
            current = c.execute(
                """
                SELECT
                    start_time,
                    interval_hours
                FROM automation
                WHERE id=1
                """
            ).fetchone()

            if current:
                if start_time is None:
                    start_time = current[0]

                if interval_hours is None:
                    interval_hours = current[1]

            if interval_hours is None:
                interval_hours = 4

            interval_hours = int(interval_hours)

            if interval_hours < 1 or interval_hours > 24:
                raise ValueError(
                    "interval_hours must be between 1 and 24."
                )

            c.execute(
                """
                UPDATE automation
                SET active=1,
                    root_topic=?,
                    next_run_at=?,
                    start_time=?,
                    interval_hours=?
                WHERE id=1
                """,
                (
                    root_topic,
                    next_run_at,
                    start_time,
                    interval_hours,
                ),
            )

            c.commit()

    def stop_automation(self):
        with self._connect() as c:
            c.execute(
                """
                UPDATE automation
                SET active=0,
                    next_run_at=NULL
                WHERE id=1
                """
            )

            c.commit()

    def set_next_run(
        self,
        next_run_at,
    ):
        with self._connect() as c:
            c.execute(
                """
                UPDATE automation
                SET next_run_at=?
                WHERE id=1
                """,
                (next_run_at,),
            )

            c.commit()

    def set_start_time(
        self,
        start_time,
    ):
        with self._connect() as c:
            c.execute(
                """
                UPDATE automation
                SET start_time=?
                WHERE id=1
                """,
                (start_time,),
            )

            c.commit()

    def set_interval_hours(
        self,
        interval_hours,
    ):
        interval_hours = int(interval_hours)

        if interval_hours < 1 or interval_hours > 24:
            raise ValueError(
                "interval_hours must be between 1 and 24."
            )

        with self._connect() as c:
            c.execute(
                """
                UPDATE automation
                SET interval_hours=?
                WHERE id=1
                """,
                (interval_hours,),
            )

            c.commit()

    def set_automation_schedule(
        self,
        start_time,
        interval_hours,
        next_run_at=None,
        active=None,
        root_topic=None,
    ):
        interval_hours = int(interval_hours)

        if interval_hours < 1 or interval_hours > 24:
            raise ValueError(
                "interval_hours must be between 1 and 24."
            )

        with self._connect() as c:
            current = c.execute(
                """
                SELECT
                    active,
                    root_topic
                FROM automation
                WHERE id=1
                """
            ).fetchone()

            current_active = (
                current[0]
                if current
                else 0
            )

            current_root = (
                current[1]
                if current
                else None
            )

            if active is None:
                active = current_active

            if root_topic is None:
                root_topic = current_root

            c.execute(
                """
                UPDATE automation
                SET start_time=?,
                    interval_hours=?,
                    next_run_at=?,
                    active=?,
                    root_topic=?
                WHERE id=1
                """,
                (
                    start_time,
                    interval_hours,
                    next_run_at,
                    int(bool(active)),
                    root_topic,
                ),
            )

            c.commit()

    def get_automation(self):
        with self._connect() as c:
            return c.execute(
                """
                SELECT
                    active,
                    root_topic,
                    last_post_id,
                    next_run_at,
                    start_time,
                    interval_hours
                FROM automation
                WHERE id=1
                """
            ).fetchone()

    def set_last_post(
        self,
        post_id,
    ):
        with self._connect() as c:
            c.execute(
                """
                UPDATE automation
                SET last_post_id=?
                WHERE id=1
                """,
                (post_id,),
            )

            c.commit()

    def stats(self):
        with self._connect() as c:
            pending = c.execute(
                """
                SELECT COUNT(*)
                FROM topic_nodes
                WHERE status='pending'
                """
            ).fetchone()[0]

            processing = c.execute(
                """
                SELECT COUNT(*)
                FROM topic_nodes
                WHERE status='processing'
                """
            ).fetchone()[0]

            used = c.execute(
                """
                SELECT COUNT(*)
                FROM topic_nodes
                WHERE status='used'
                """
            ).fetchone()[0]

            posts = c.execute(
                """
                SELECT COUNT(*)
                FROM posts
                WHERE status='published'
                """
            ).fetchone()[0]

            drafts = c.execute(
                """
                SELECT COUNT(*)
                FROM posts
                WHERE status='draft'
                """
            ).fetchone()[0]

            return (
                posts,
                pending,
                used,
                processing,
                drafts,
            )
