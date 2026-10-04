# database.py

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional


# ============================================================
# Helpers
# ============================================================

def now_iso() -> str:
    """Return current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


# ============================================================
# Database
# ============================================================

class Database:
    """
    SQLite database manager for posts, topics and automation.

    The class keeps the original public API while adding:
    - Safe initialization
    - Automatic migrations
    - SQLite foreign keys
    - WAL mode
    - Busy timeout
    - Topic indexes
    - Safer topic claiming
    - Processing timeout recovery
    - Validation
    """

    VALID_POST_STATUSES = {
        "draft",
        "scheduled",
        "published",
        "failed",
    }

    VALID_TOPIC_STATUSES = {
        "pending",
        "processing",
        "used",
    }

    MIN_INTERVAL_HOURS = 1
    MAX_INTERVAL_HOURS = 24

    def __init__(self, path: str | Path):
        self.path = Path(path)

        # If only a filename is provided, parent is "."
        self.path.parent.mkdir(parents=True, exist_ok=True)

        self._init()

    # ========================================================
    # Connection
    # ========================================================

    def _connect(self) -> sqlite3.Connection:
        """
        Create a configured SQLite connection.
        """

        connection = sqlite3.connect(
            self.path,
            timeout=30,
            isolation_level=None,
        )

        connection.row_factory = sqlite3.Row

        # Foreign keys
        connection.execute("PRAGMA foreign_keys = ON")

        # Better concurrent read/write behavior.
        connection.execute("PRAGMA journal_mode = WAL")

        # Wait for locked database instead of failing immediately.
        connection.execute("PRAGMA busy_timeout = 30000")

        # Reasonable durability.
        connection.execute("PRAGMA synchronous = NORMAL")

        return connection

    # ========================================================
    # Initialization / Migration
    # ========================================================

    def _init(self) -> None:
        """
        Create tables and indexes and run safe migrations.
        """

        with self._connect() as c:
            # ------------------------------------------------
            # Posts
            # ------------------------------------------------

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

                    published_at TEXT,

                    CHECK (
                        status IN (
                            'draft',
                            'scheduled',
                            'published',
                            'failed'
                        )
                    )
                )
                """
            )

            # ------------------------------------------------
            # Topics
            # ------------------------------------------------

            c.execute(
                """
                CREATE TABLE IF NOT EXISTS topic_nodes(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    topic TEXT NOT NULL,

                    normalized_topic TEXT,

                    parent_id INTEGER,

                    depth INTEGER NOT NULL DEFAULT 0,

                    status TEXT NOT NULL DEFAULT 'pending',

                    source_post_id INTEGER,

                    created_at TEXT NOT NULL,

                    used_at TEXT,

                    processing_at TEXT,

                    CHECK (
                        status IN (
                            'pending',
                            'processing',
                            'used'
                        )
                    ),

                    CHECK (depth >= 0),

                    FOREIGN KEY(parent_id)
                        REFERENCES topic_nodes(id)
                        ON DELETE SET NULL,

                    FOREIGN KEY(source_post_id)
                        REFERENCES posts(id)
                        ON DELETE SET NULL
                )
                """
            )

            # ------------------------------------------------
            # Automation
            # ------------------------------------------------

            c.execute(
                """
                CREATE TABLE IF NOT EXISTS automation(
                    id INTEGER PRIMARY KEY CHECK(id = 1),

                    active INTEGER NOT NULL DEFAULT 0,

                    root_topic TEXT,

                    last_post_id INTEGER,

                    next_run_at TEXT,

                    start_time TEXT,

                    interval_hours INTEGER NOT NULL DEFAULT 4,

                    CHECK(active IN (0, 1)),

                    CHECK(
                        interval_hours >= 1
                        AND interval_hours <= 24
                    ),

                    FOREIGN KEY(last_post_id)
                        REFERENCES posts(id)
                        ON DELETE SET NULL
                )
                """
            )

            # ------------------------------------------------
            # Ensure singleton automation row.
            # ------------------------------------------------

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

            # ------------------------------------------------
            # Migrations
            # ------------------------------------------------

            self._migrate_posts(c)
            self._migrate_topics(c)
            self._migrate_automation(c)

            # ------------------------------------------------
            # Indexes
            # ------------------------------------------------

            c.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_posts_status
                ON posts(status)
                """
            )

            c.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_posts_scheduled_at
                ON posts(scheduled_at)
                """
            )

            c.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_topics_status_depth_id
                ON topic_nodes(status, depth, id)
                """
            )

            c.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_topics_parent
                ON topic_nodes(parent_id)
                """
            )

            c.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_topics_normalized
                ON topic_nodes(normalized_topic)
                """
            )

            c.commit()

    # ========================================================
    # Migrations
    # ========================================================

    @staticmethod
    def _table_columns(
        c: sqlite3.Connection,
        table: str,
    ) -> set[str]:
        rows = c.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()

        return {row["name"] for row in rows}

    def _migrate_posts(
        self,
        c: sqlite3.Connection,
    ) -> None:
        """
        Add missing columns to older posts tables.
        """

        columns = self._table_columns(c, "posts")

        if "image_path" not in columns:
            c.execute(
                """
                ALTER TABLE posts
                ADD COLUMN image_path TEXT
                """
            )

        if "status" not in columns:
            c.execute(
                """
                ALTER TABLE posts
                ADD COLUMN status TEXT NOT NULL DEFAULT 'draft'
                """
            )

        if "scheduled_at" not in columns:
            c.execute(
                """
                ALTER TABLE posts
                ADD COLUMN scheduled_at TEXT
                """
            )

        if "created_at" not in columns:
            c.execute(
                """
                ALTER TABLE posts
                ADD COLUMN created_at TEXT
                """
            )

            c.execute(
                """
                UPDATE posts
                SET created_at=?
                WHERE created_at IS NULL
                """,
                (now_iso(),),
            )

        if "published_at" not in columns:
            c.execute(
                """
                ALTER TABLE posts
                ADD COLUMN published_at TEXT
                """
            )

    def _migrate_topics(
        self,
        c: sqlite3.Connection,
    ) -> None:
        """
        Add missing topic columns to older databases.
        """

        columns = self._table_columns(c, "topic_nodes")

        if "normalized_topic" not in columns:
            c.execute(
                """
                ALTER TABLE topic_nodes
                ADD COLUMN normalized_topic TEXT
                """
            )

            rows = c.execute(
                """
                SELECT id, topic
                FROM topic_nodes
                """
            ).fetchall()

            for row in rows:
                normalized = self._normalize_topic(
                    row["topic"]
                )

                c.execute(
                    """
                    UPDATE topic_nodes
                    SET normalized_topic=?
                    WHERE id=?
                    """,
                    (
                        normalized,
                        row["id"],
                    ),
                )

        if "processing_at" not in columns:
            c.execute(
                """
                ALTER TABLE topic_nodes
                ADD COLUMN processing_at TEXT
                """
            )

        if "parent_id" not in columns:
            c.execute(
                """
                ALTER TABLE topic_nodes
                ADD COLUMN parent_id INTEGER
                """
            )

        if "depth" not in columns:
            c.execute(
                """
                ALTER TABLE topic_nodes
                ADD COLUMN depth INTEGER NOT NULL DEFAULT 0
                """
            )

        if "source_post_id" not in columns:
            c.execute(
                """
                ALTER TABLE topic_nodes
                ADD COLUMN source_post_id INTEGER
                """
            )

        if "created_at" not in columns:
            c.execute(
                """
                ALTER TABLE topic_nodes
                ADD COLUMN created_at TEXT
                """
            )

            c.execute(
                """
                UPDATE topic_nodes
                SET created_at=?
                WHERE created_at IS NULL
                """,
                (now_iso(),),
            )

        if "used_at" not in columns:
            c.execute(
                """
                ALTER TABLE topic_nodes
                ADD COLUMN used_at TEXT
                """
            )

    def _migrate_automation(
        self,
        c: sqlite3.Connection,
    ) -> None:
        """
        Add missing automation columns to older databases.
        """

        columns = self._table_columns(
            c,
            "automation",
        )

        if "active" not in columns:
            c.execute(
                """
                ALTER TABLE automation
                ADD COLUMN active INTEGER
                NOT NULL DEFAULT 0
                """
            )

        if "root_topic" not in columns:
            c.execute(
                """
                ALTER TABLE automation
                ADD COLUMN root_topic TEXT
                """
            )

        if "last_post_id" not in columns:
            c.execute(
                """
                ALTER TABLE automation
                ADD COLUMN last_post_id INTEGER
                """
            )

        if "next_run_at" not in columns:
            c.execute(
                """
                ALTER TABLE automation
                ADD COLUMN next_run_at TEXT
                """
            )

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

        # Protect old/invalid values.
        c.execute(
            """
            UPDATE automation
            SET interval_hours=4
            WHERE interval_hours IS NULL
               OR interval_hours < 1
               OR interval_hours > 24
            """
        )

    # ========================================================
    # Validation
    # ========================================================

    @staticmethod
    def _normalize_topic(topic: str) -> str:
        return " ".join(
            topic.casefold().split()
        )

    @classmethod
    def _validate_interval(
        cls,
        interval_hours: int,
    ) -> int:
        try:
            value = int(interval_hours)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "interval_hours must be an integer."
            ) from exc

        if not (
            cls.MIN_INTERVAL_HOURS
            <= value
            <= cls.MAX_INTERVAL_HOURS
        ):
            raise ValueError(
                "interval_hours must be between "
                "1 and 24."
            )

        return value

    @classmethod
    def _validate_post_status(
        cls,
        status: str,
    ) -> None:
        if status not in cls.VALID_POST_STATUSES:
            raise ValueError(
                f"Invalid post status: {status}"
            )

    # ========================================================
    # Posts
    # ========================================================

    def create_post(
        self,
        prompt: str,
        text: str,
        image_path: Optional[str] = None,
        scheduled_at: Optional[str] = None,
    ) -> int:
        """
        Create a new post.

        Returns:
            Newly created post ID.
        """

        prompt = str(prompt).strip()
        text = str(text).strip()

        if not prompt:
            raise ValueError(
                "prompt cannot be empty."
            )

        if not text:
            raise ValueError(
                "text cannot be empty."
            )

        status = (
            "scheduled"
            if scheduled_at
            else "draft"
        )

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
                    status,
                    scheduled_at,
                    now_iso(),
                ),
            )

            c.commit()

            return int(cur.lastrowid)

    def get_post(
        self,
        post_id: int,
    ) -> Optional[sqlite3.Row]:
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

    def update_post(
        self,
        post_id: int,
        status: str,
    ) -> None:
        self._validate_post_status(status)

        with self._connect() as c:
            current = c.execute(
                """
                SELECT
                    status,
                    published_at
                FROM posts
                WHERE id=?
                """,
                (post_id,),
            ).fetchone()

            if current is None:
                raise ValueError(
                    f"Post {post_id} does not exist."
                )

            published_at = current["published_at"]

            # Only set publication timestamp once.
            if (
                status == "published"
                and published_at is None
            ):
                published_at = now_iso()

            if status != "published":
                published_at = None

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

    def get_last_post_text(
        self,
    ) -> Optional[str]:
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

            return (
                row["text"]
                if row
                else None
            )

    # ========================================================
    # Topics
    # ========================================================

    def add_topic(
        self,
        topic: str,
        parent_id: Optional[int] = None,
        depth: int = 0,
        source_post_id: Optional[int] = None,
    ) -> Optional[int]:
        """
        Add a topic if an unused/active duplicate does not exist.

        Returns:
            Topic ID or None for empty topic.
        """

        topic = str(topic).strip()

        if not topic:
            return None

        try:
            depth = int(depth)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "depth must be an integer."
            ) from exc

        if depth < 0:
            raise ValueError(
                "depth cannot be negative."
            )

        normalized = self._normalize_topic(topic)

        with self._connect() as c:
            existing = c.execute(
                """
                SELECT id
                FROM topic_nodes
                WHERE normalized_topic=?
                  AND status != 'used'
                ORDER BY id ASC
                LIMIT 1
                """,
                (normalized,),
            ).fetchone()

            if existing:
              
