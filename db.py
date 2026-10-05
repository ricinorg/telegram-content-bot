

db.py

مدیریت دیتابیس ربات تلگرام

مسئولیت‌های این فایل:

1. ساخت و مدیریت دیتابیس SQLite

2. ذخیره پست‌ها

3. مدیریت موضوعات اصلی و فرعی

4. مدیریت صف موضوعات برای انتشار

5. مدیریت وضعیت اتوماسیون

6. ذخیره ساعت شروع اتوماسیون

7. ذخیره فاصله زمانی انتشار

8. ارائه آمار دیتابیس


import sqlite3
from datetime import datetime, timezone
from pathlib import Path



ابزارهای عمومی


def now_iso():
"""
زمان فعلی UTC را به صورت ISO ذخیره می‌کند.
"""
return datetime.now(timezone.utc).isoformat()

============================================================

کلاس اصلی دیتابیس

============================================================

class Database:

def __init__(self, path):
    """
    اتصال اولیه به دیتابیس و ساخت جداول در صورت نیاز.
    """

    self.path = Path(path)

    # ساخت پوشه دیتابیس در صورت نبودن
    self.path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # ساخت جداول
    self._init()

# ========================================================
# اتصال به SQLite
# ========================================================

def _connect(self):
    """
    یک اتصال جدید به SQLite ایجاد می‌کند.
    """

    return sqlite3.connect(self.path)

# ========================================================
# ساخت / به‌روزرسانی ساختار دیتابیس
# ========================================================

def _init(self):
    """
    جداول مورد نیاز ربات را ایجاد می‌کند.

    این تابع به شکلی نوشته شده که اگر دیتابیس از قبل
    وجود داشته باشد، اطلاعات قبلی حذف نشوند.
    """

    with self._connect() as c:

        # ------------------------------------------------
        # جدول پست‌ها
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
                published_at TEXT
            )
            """
        )

        # ------------------------------------------------
        # جدول موضوعات
        # ------------------------------------------------

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

        # ------------------------------------------------
        # جدول اتوماسیون
        # ------------------------------------------------

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

        # ------------------------------------------------
        # ایجاد رکورد اولیه اتوماسیون
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
        # بررسی ستون‌های جدول automation
        #
        # برای دیتابیس‌هایی که از نسخه قدیمی ربات باقی
        # مانده‌اند، ستون‌های جدید اضافه می‌شوند.
        # ------------------------------------------------

        columns = {
            row[1]
            for row in c.execute(
                "PRAGMA table_info(automation)"
            ).fetchall()
        }

        # اضافه کردن start_time در صورت نبودن
        if "start_time" not in columns:
            c.execute(
                """
                ALTER TABLE automation
                ADD COLUMN start_time TEXT
                """
            )

        # اضافه کردن interval_hours در صورت نبودن
        if "interval_hours" not in columns:
            c.execute(
                """
                ALTER TABLE automation
                ADD COLUMN interval_hours INTEGER NOT NULL DEFAULT 4
                """
            )

        # اطمینان از مقدار معتبر interval
        c.execute(
            """
            UPDATE automation
            SET interval_hours = 4
            WHERE interval_hours IS NULL
               OR interval_hours < 1
            """
        )

        c.commit()

# ========================================================
# POSTS
# ========================================================

def create_post(
    self,
    prompt,
    text,
    image_path=None,
    scheduled_at=None,
):
    """
    یک پست جدید در دیتابیس ایجاد می‌کند.

    خروجی:
        ID پست ایجادشده
    """

    with self._connect() as c:

        cur = c.execute(
            """
            INSERT INTO posts(
                prompt,
                text,
                image_path,
                scheduled_at,
                created_at
            )
            VALUES(?,?,?,?,?)
            """,
            (
                prompt,
                text,
                image_path,
                scheduled_at,
                now_iso(),
            ),
        )

        c.commit()

        return cur.lastrowid

# --------------------------------------------------------

def get_post(self, post_id):
    """
    اطلاعات کامل یک پست را برمی‌گرداند.
    """

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

# --------------------------------------------------------

def update_post(self, post_id, status):
    """
    وضعیت یک پست را تغییر می‌دهد.

    اگر وضعیت published باشد،
    زمان انتشار نیز ثبت می‌شود.
    """

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

# --------------------------------------------------------

def get_last_post_text(self):
    """
    متن آخرین پست منتشرشده را برمی‌گرداند.

    این متن برای جلوگیری از تولید محتوای تکراری
    توسط Gemini استفاده می‌شود.
    """

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

# ========================================================
# TOPICS
# ========================================================

def add_topic(
    self,
    topic,
    parent_id=None,
    depth=0,
    source_post_id=None,
):
    """
    یک موضوع جدید به صف موضوعات اضافه می‌کند.

    اگر موضوع مشابهی از قبل وجود داشته باشد،
    موضوع تکراری ایجاد نمی‌شود.
    """

    if topic is None:
        return None

    topic = str(topic).strip()

    if not topic:
        return None

    # نرمال‌سازی برای مقایسه
    normalized = " ".join(
        topic.casefold().split()
    )

    with self._connect() as c:

        # بررسی موضوعات استفاده‌نشده
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

        # ایجاد موضوع جدید
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

# --------------------------------------------------------

def add_topics(
    self,
    topics,
    parent_id=None,
    depth=0,
    source_post_id=None,
):
    """
    چند موضوع را به صورت گروهی اضافه می‌کند.

    خروجی:
        لیست ID موضوعات ایجادشده
    """

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

# --------------------------------------------------------

def claim_next_topic(self):
    """
    اولین موضوع pending را برای پردازش انتخاب می‌کند
    و وضعیت آن را به processing تغییر می‌دهد.

    این روش باعث می‌شود یک موضوع هم‌زمان دوبار
    انتخاب نشود.
    """

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

# --------------------------------------------------------

def mark_topic_used(self, topic_id):
    """
    یک موضوع را به عنوان استفاده‌شده علامت می‌زند.
    """

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

# --------------------------------------------------------

def reset_processing(self):
    """
    اگر ربات هنگام پردازش یک موضوع خاموش یا Restart شود،
    موضوع processing دوباره به pending برمی‌گردد.
    """

    with self._connect() as c:

        c.execute(
            """
            UPDATE topic_nodes
            SET status='pending'
            WHERE status='processing'
            """
        )

        c.commit()

# --------------------------------------------------------

def get_topic(self, topic_id):
    """
    اطلاعات کامل یک موضوع را برمی‌گرداند.
    """

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

# ========================================================
# AUTOMATION
# ========================================================

def start_automation(
    self,
    root_topic,
    next_run_at,
    start_time=None,
    interval_hours=None,
):
    """
    اتوماسیون را فعال می‌کند.

    اگر start_time یا interval_hours ارسال نشده باشد،
    مقدار قبلی دیتابیس حفظ می‌شود.
    """

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

# --------------------------------------------------------

def stop_automation(self):
    """
    اتوماسیون را متوقف می‌کند.
    """

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

# --------------------------------------------------------

def set_next_run(self, next_run_at):
    """
    زمان اجرای بعدی اتوماسیون را ذخیره می‌کند.
    """

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

# --------------------------------------------------------

def set_start_time(self, start_time):
    """
    ساعت شروع اتوماسیون را ذخیره می‌کند.

    نمونه:
        09:00
        14:30
    """

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

# --------------------------------------------------------

def set_interval_hours(self, interval_hours):
    """
    فاصله انتشار را بر حسب ساعت تنظیم می‌کند.

    محدوده مجاز:
        1 تا 24 ساعت
    """

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

# --------------------------------------------------------

def set_automation_schedule(
    self,
    start_time,
    interval_hours,
    next_run_at=None,
    active=None,
    root_topic=None,
):
    """
    تنظیم کامل برنامه اتوماسیون.

    این متد برای پنل ادمین مفید است.
    """

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

# --------------------------------------------------------

def get_automation(self):
    """
    وضعیت کامل اتوماسیون را برمی‌گرداند.

    ترتیب خروجی:

    0 = active
    1 = root_topic
    2 = last_post_id
    3 = next_run_at
    4 = start_time
    5 = interval_hours
    """

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

# --------------------------------------------------------

def set_last_post(self, post_id):
    """
    ID آخرین پست تولیدشده توسط اتوماسیون را ذخیره می‌کند.
    """

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

# ========================================================
# STATISTICS
# ========================================================

def stats(self):
    """
    آمار کلی دیتابیس را برمی‌گرداند.

    خروجی:

        (
            published_posts,
            pending_topics,
            used_topics
        )
    """

    with self._connect() as c:

        pending = c.execute(
            """
            SELECT COUNT(*)
            FROM topic_nodes
            WHERE status='pending'
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

        return (
            posts,
            pending,
            used,
        )
