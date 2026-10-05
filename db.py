# ============================================================
# db.py
# مدیریت دیتابیس ربات تلگرام
#
# این فایل مسئول:
# 1. ساخت و مدیریت دیتابیس SQLite
# 2. ذخیره پست‌ها
# 3. مدیریت موضوعات اصلی و فرعی
# 4. مدیریت صف انتشار موضوعات
# 5. تنظیم اتوماسیون انتشار
# 6. ذخیره ساعت شروع و فاصله انتشار
# 7. ارائه آمار دیتابیس
# ============================================================


# ============================================================
# بخش 1 — کتابخانه‌های مورد نیاز
# ============================================================

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


# ============================================================
# بخش 2 — زمان فعلی به فرمت ISO
# ============================================================

def now_iso():
    return datetime.now(timezone.utc).isoformat()


# ============================================================
# بخش 3 — کلاس اصلی Database
# ============================================================

class Database:

    # --------------------------------------------------------
    # ساخت اتصال اولیه به دیتابیس
    # --------------------------------------------------------

    def __init__(self, path):
        self.path = Path(path)

        # اگر پوشه data وجود نداشته باشد، ساخته می‌شود
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        # ساخت جدول‌ها
        self._init()

    # --------------------------------------------------------
    # ایجاد اتصال به SQLite
    # --------------------------------------------------------

    def _connect(self):
        return sqlite3.connect(self.path)

    # ========================================================
    # بخش 4 — ساخت جدول‌های دیتابیس
    # ========================================================

    def _init(self):

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
            # جدول تنظیمات اتوماسیون
            #
            # active:
            #     0 = خاموش
            #     1 = روشن
            #
            # start_time:
            #     ساعت شروع انتشار
            #
            # interval_hours:
            #     فاصله انتشار بر اساس ساعت
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
            # ایجاد تنظیمات پیش‌فرض اتوماسیون
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
            # بررسی دیتابیس‌های قدیمی
            #
            # اگر قبلاً automation ساخته شده باشد و ستون‌های
            # جدید را نداشته باشد، اینجا اضافه می‌شوند.
            # ------------------------------------------------

            columns = {
                row[1]
                for row in c.execute(
                    "PRAGMA table_info(automation)"
                ).fetchall()
            }

            # اضافه کردن ساعت شروع در دیتابیس قدیمی
            if "start_time" not in columns:

                c.execute(
                    """
                    ALTER TABLE automation
                    ADD COLUMN start_time TEXT
                    """
                )

            # اضافه کردن فاصله انتشار در دیتابیس قدیمی
            if "interval_hours" not in columns:

                c.execute(
                    """
                    ALTER TABLE automation
                    ADD COLUMN interval_hours INTEGER NOT NULL DEFAULT 4
                    """
                )

            # اگر مقدار فاصله خراب یا خالی بود،
            # مقدار پیش‌فرض 4 ساعت قرار می‌گیرد.
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
    # بخش 5 — مدیریت پست‌ها
    # ========================================================

    # --------------------------------------------------------
    # ایجاد پست جدید
    # --------------------------------------------------------

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
    # دریافت یک پست با ID
    # --------------------------------------------------------

    def get_post(self, i):

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
                (i,),
            ).fetchone()

    # --------------------------------------------------------
    # تغییر وضعیت پست
    #
    # مثال:
    # draft
    # published
    # failed
    # --------------------------------------------------------

    def update_post(self, i, status):

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
                    i,
                ),
            )

            c.commit()

    # --------------------------------------------------------
    # دریافت متن آخرین پست منتشرشده
    #
    # برای جلوگیری از تولید محتوای تکراری توسط Gemini
    # استفاده می‌شود.
    # --------------------------------------------------------

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

    # ========================================================
    # بخش 6 — مدیریت موضوعات
    # ========================================================

    # --------------------------------------------------------
    # اضافه کردن یک موضوع
    # --------------------------------------------------------

    def add_topic(
        self,
        topic,
        parent_id=None,
        depth=0,
        source_post_id=None,
    ):

        topic = topic.strip()

        if not topic:
            return None

        # یکسان‌سازی فاصله‌ها و حروف برای جلوگیری از
        # ثبت موضوع تکراری
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

            # بررسی تکراری نبودن موضوع
            for row_id, existing in rows:

                existing_normalized = " ".join(
                    existing.casefold().split()
                )

                if existing_normalized == normalized:
                    return row_id

            # ثبت موضوع جدید
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
    # اضافه کردن چند موضوع به صورت همزمان
    # --------------------------------------------------------

    def add_topics(
        self,
        topics,
        parent_id=None,
        depth=0,
        source_post_id=None,
    ):

        ids = []

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
    # دریافت اولین موضوع آماده انتشار
    #
    # موضوع از pending به processing تغییر می‌کند.
    # --------------------------------------------------------

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

            # اگر موضوع قبلاً توسط پردازش دیگری گرفته شده باشد
            if updated.rowcount != 1:
                return None

            c.commit()

            return row

    # --------------------------------------------------------
    # علامت‌گذاری موضوع به عنوان استفاده‌شده
    # --------------------------------------------------------

    def mark_topic_used(self, topic_id):

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
    # برگرداندن موضوعات processing به pending
    #
    # اگر Render یا ربات وسط کار Restart شود، موضوعات گیر
    # کرده دوباره قابل پردازش می‌شوند.
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # دریافت اطلاعات یک موضوع
    # --------------------------------------------------------

    def get_topic(self, topic_id):

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
    # بخش 7 — مدیریت اتوماسیون
    # ========================================================

    # --------------------------------------------------------
    # شروع اتوماسیون
    #
    # root_topic:
    #     موضوع اصلی
    #
    # next_run_at:
    #     زمان اجرای بعدی
    #
    # start_time:
    #     ساعت شروع
    #
    # interval_hours:
    #     فاصله انتشار
    # --------------------------------------------------------

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

            # اگر مقدار جدید داده نشده باشد،
            # مقدار قبلی حفظ می‌شود.
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
    # متوقف کردن اتوماسیون
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # تغییر زمان اجرای بعدی
    # --------------------------------------------------------

    def set_next_run(self, next_run_at):

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
    # تغییر ساعت شروع اتوماسیون
    # مثال:
    # 09:00
    # 14:30
    # --------------------------------------------------------

    def set_start_time(self, start_time):

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
    # تغییر فاصله انتشار
    #
    # مقدار مجاز:
    # 1 تا 24 ساعت
    # --------------------------------------------------------

    def set_interval_hours(self, interval_hours):

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
    # تنظیم کامل زمان‌بندی اتوماسیون
    #
    # این تابع برای پنل مدیریت طراحی شده است.
    #
    # مثال:
    #
    # start_time = "09:00"
    # interval_hours = 4
    #
    # نتیجه:
    #
    # 09:00
    # 13:00
    # 17:00
    # 21:00
    # 01:00
    # --------------------------------------------------------

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

            # اگر مقدار جدید داده نشده،
            # مقدار فعلی حفظ شود.
            if active is None:
                active = current_active

            if root_topic is None:
                root_topic = current_root

            c.execute(
                """
                UPDATE automation
                SET start_time=?,
        
