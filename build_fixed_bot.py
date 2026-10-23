"""Build a replacement project ZIP from the reviewed original ZIP.
Usage: python build_fixed_bot.py telegram-content-bot-main.zip
Python 3.10+. No API calls; existing databases are not packaged or deleted.
Fetches the previously supplied stage-1 patch from its public download URL.
"""
import argparse
import ast
import runpy
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

STAGE1_URL = 'https://d2lm3begjhzc49.cloudfront.net/file-interaction/e4bf7ecc-apply_stage1.txt'


def function_replace(text, name, replacement):
    tree = ast.parse(text)
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    if len(nodes) != 1:
        raise RuntimeError('Source mismatch: ' + name)
    node = nodes[0]
    lines = text.splitlines(keepends=True)
    return ''.join(lines[:node.lineno-1]) + replacement.strip() + '\n\n' + ''.join(lines[node.end_lineno:])


DB_METHODS = '''
    def claim_topic(self, topic_id):
        with self._connect() as c:
            updated = c.execute("UPDATE topic_nodes SET status='processing' WHERE id=? AND status='pending'", (topic_id,))
            if updated.rowcount != 1:
                return None
            row = c.execute("SELECT id,topic,parent_id,depth FROM topic_nodes WHERE id=?", (topic_id,)).fetchone()
            return row

    def create_topic_post(self, topic_id, topic, text):
        with self._connect() as c:
            cur = c.execute("INSERT INTO posts(prompt,text,status,created_at,topic_id,topics_extracted) VALUES(?,?,'draft',?,?,0)", (topic,text,now_iso(),topic_id))
            return cur.lastrowid

    def ready_topic_post(self):
        with self._connect() as c:
            row = c.execute("SELECT id FROM posts WHERE status='draft' AND topic_id IS NOT NULL ORDER BY id LIMIT 1").fetchone()
            return self.get_post(row[0]) if row else None

    def post_topic_id(self, post_id):
        with self._connect() as c:
            row = c.execute("SELECT topic_id FROM posts WHERE id=?", (post_id,)).fetchone()
            return row[0] if row else None

    def topics_are_extracted(self, post_id):
        with self._connect() as c:
            row = c.execute("SELECT topics_extracted FROM posts WHERE id=?", (post_id,)).fetchone()
            return bool(row and row[0])

    def save_child_topics(self, post_id, topics):
        parent = self.post_topic_id(post_id)
        row = self.get_topic(parent) if parent else None
        depth = row[3] + 1 if row else 0
        # Idempotent retries reuse the existing topic-deduplication behavior.
        ids = self.add_topics(topics, parent_id=parent, depth=depth, source_post_id=post_id)
        with self._connect() as c:
            c.execute("UPDATE posts SET topics_extracted=1 WHERE id=?", (post_id,))
        return ids

    def release_topic(self, topic_id):
        with self._connect() as c:
            c.execute("UPDATE topic_nodes SET status='pending' WHERE id=? AND status='processing' AND NOT EXISTS(SELECT 1 FROM posts WHERE topic_id=? AND status='draft')", (topic_id,topic_id))

    def recover_orphan_topics(self):
        with self._connect() as c:
            c.execute("UPDATE topic_nodes SET status='pending' WHERE status='processing' AND NOT EXISTS(SELECT 1 FROM posts WHERE posts.topic_id=topic_nodes.id AND posts.status='draft')")

    def finish_topic_post(self, post_id, status):
        with self._connect() as c:
            c.execute("UPDATE posts SET status=?,published_at=? WHERE id=?", (status,now_iso() if status=='published' else None,post_id))
            c.execute("UPDATE topic_nodes SET status='used',used_at=? WHERE id=(SELECT topic_id FROM posts WHERE id=?)", (now_iso(),post_id))
            if status == 'published':
                c.execute("UPDATE automation SET last_post_id=? WHERE id=1", (post_id,))
'''

TREE_HELPERS = '''
# At most one prepared topic draft is maintained; no unbounded API loop.
_pipeline_lock = asyncio.Lock()
_publication_lock = asyncio.Lock()


async def extract_children(post_id):
    if db.topics_are_extracted(post_id):
        return
    post = db.get_post(post_id)
    if not post:
        return
    try:
        topics = await asyncio.to_thread(ai.extract_topics, post[1], post[2], count=6)
        if topics:
            db.save_child_topics(post_id, topics)
    except Exception:
        logger.error("Child-topic extraction failed for post %s; retry on next scheduler tick", post_id)


async def prepare_topic(context, topic_row):
    topic_id, topic = topic_row[:2]
    try:
        text = await asyncio.to_thread(ai.generate_text,
            topic=topic, previous_text=db.get_last_post_text(),
            style_instruction=content_instruction())
        post_id = db.create_topic_post(topic_id, topic, text)
    except Exception:
        db.release_topic(topic_id)
        raise
    await extract_children(post_id)
    if settings.approval_required:
        try:
            await send_post_preview(context, post_id)
        except Exception:
            logger.error("Preview delivery failed for draft %s; draft remains stored", post_id)
    return post_id


async def ensure_ready(context):
    post = db.ready_topic_post()
    if post:
        await extract_children(post[0])
        return post[0]
    topic = db.claim_next_topic()
    if not topic:
        return None
    return await prepare_topic(context, topic)
'''

PUBLISH = '''async def publish_post(context, post_id):
    async with _publication_lock:
        post = db.get_post(post_id)
        if not post:
            raise RuntimeError(f"Post {post_id} not found")
        if post[4] == "published":
            return
        if post[4] != "draft":
            raise RuntimeError("Only a draft can be published")
        await context.bot.send_message(chat_id=settings.telegram_channel_id, text=post[2])
        db.finish_topic_post(post_id, "published")
    await extract_children(post_id)
'''

GENERATE_TOPIC = '''async def generate_topic_job(context, force_topic_id=None):
    async with _pipeline_lock:
        if force_topic_id:
            topic = db.claim_topic(force_topic_id)
            if not topic:
                return
            post_id = await prepare_topic(context, topic)
        else:
            post_id = await ensure_ready(context)
        if post_id and not settings.approval_required:
            await publish_post(context, post_id)
        # Prepare the next draft, without publishing it before its scheduled time.
        if not settings.approval_required:
            await ensure_ready(context)
'''

AUTOMATION = '''async def automation_job(context):
    try:
        async with _pipeline_lock:
            state = db.get_automation()
            if not state or not state[0]:
                return
            # Fill the buffer even when publication is not due yet.
            post_id = await ensure_ready(context)
            state = db.get_automation()
            if not state or not state[0]:
                return
            now = datetime.now(timezone.utc)
            if state[3]:
                due = datetime.fromisoformat(state[3])
                if due.tzinfo is None:
                    due = due.replace(tzinfo=timezone.utc)
                if now < due:
                    return
            if settings.approval_required:
                # A scheduled run never bypasses manual approval.
                return
            if post_id:
                await publish_post(context, post_id)
                db.set_next_run((datetime.now(timezone.utc) + timedelta(hours=int(state[5] or 4))).isoformat())
                await ensure_ready(context)
    except Exception:
        logger.error("Automation failed; stored drafts are retained and retried on the next tick")
'''

START_TOPIC = '''async def starttopic_command(update, context):
    if not is_admin(update.effective_user.id):
        await deny(update)
        return
    topic = " ".join(context.args or []).strip()
    if not topic:
        await update.message.reply_text("ظ…ط«ط§ظ„: /starttopic ظ‡ظˆط´ ظ…طµظ†ظˆط¹غŒ")
        return
    try:
        topic_id = db.add_topic(topic, parent_id=None, depth=0)
        state = db.get_automation()
        interval = int(state[5] or 4)
        next_run = _next_run(state[4], interval)
        db.start_automation(topic, next_run, state[4], interval)
        await update.message.reply_text("ًںŒ³ ظ…ظˆط¶ظˆط¹ ط±غŒط´ظ‡ ط«ط¨طھ ظˆ ط§طھظˆظ…ط§ط³غŒظˆظ† ظپط¹ط§ظ„ ط´ط¯ط› ط¢ظ…ط§ط¯ظ‡â€Œط³ط§ط²غŒ ظ¾ط³طھ ظˆ ط´ط§ط®ظ‡â€Œظ‡ط§ ط´ط±ظˆط¹ ط´ط¯.")
        await generate_topic_job(context, force_topic_id=topic_id)
        await update.message.reply_text("âœ… ط¹ظ…ظ„غŒط§طھ ط¢ظ…ط§ط¯ظ‡â€Œط³ط§ط²غŒ ظ¾ط§غŒط§ظ† غŒط§ظپطھ. /autostatus ظˆط¶ط¹غŒطھ ط§ظ†طھط´ط§ط± ط¨ط¹ط¯غŒ ط±ط§ ظ†ط´ط§ظ† ظ…غŒâ€Œط¯ظ‡ط¯.")
    except Exception:
        logger.error("Start-topic preparation failed; persisted queue retained")
        await update.message.reply_text("â‌Œ ط¢ظ…ط§ط¯ظ‡â€Œط³ط§ط²غŒ ع©ط§ظ…ظ„ ظ†ط´ط¯ط› طµظپ ط°ط®غŒط±ظ‡ ط´ط¯ظ‡ ط§ط³طھ. ط§طھطµط§ظ„ APIطŒ ظ…ظˆط¬ظˆط¯غŒ ظˆ ظ„ط§ع¯ ط²ظ…ط§ظ†â€Œط¨ظ†ط¯ ط±ط§ ط¨ط±ط±ط³غŒ ع©ظ†غŒط¯.")
'''

TREE_TESTS = r'''import asyncio
from datetime import datetime, timedelta, timezone

# Reuse offline fixtures from the stage-1 test module.
from test_stage1 import core, context_for
from db import Database


def install_ai(monkeypatch, core):
    monkeypatch.setattr(core.ai, "generate_text", lambda **kw: "ظ…طھظ† " + kw["topic"])
    monkeypatch.setattr(core.ai, "extract_topics", lambda topic, text, count=6: [topic + " / ط§ظ„ظپ", topic + " / ط¨"])


def test_additive_migration_and_legacy_post(tmp_path):
    import sqlite3
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as c:
        c.execute("CREATE TABLE posts(id INTEGER PRIMARY KEY AUTOINCREMENT,prompt TEXT NOT NULL,text TEXT NOT NULL,image_path TEXT,status TEXT NOT NULL DEFAULT 'draft',scheduled_at TEXT,created_at TEXT NOT NULL,published_at TEXT)")
        c.execute("INSERT INTO posts(prompt,text,created_at) VALUES('old','kept','2026-01-01')")
    db = Database(path)
    assert db.get_post(1)[2] == "kept"
    assert db.post_topic_id(1) is None
    assert db.topics_are_extracted(1) is False


def test_tree_prepares_and_persists_children(core, monkeypatch):
    install_ai(monkeypatch, core)
    ctx = context_for(core)
    root = core.db.add_topic("ط±غŒط´ظ‡")
    core.db.start_automation("ط±غŒط´ظ‡", (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat())
    asyncio.run(core.generate_topic_job(ctx, force_topic_id=root))
    draft = core.db.ready_topic_post()
    assert draft is not None
    assert core.db.post_topic_id(draft[0]) == root
    assert core.db.get_topic(root)[4] == "processing"
    with core.db._connect() as c:
        children = c.execute("SELECT parent_id,depth FROM topic_nodes WHERE parent_id=?", (root,)).fetchall()
    assert children == [(root, 1), (root, 1)]
    reopened = Database(core.db.path)
    assert reopened.ready_topic_post()[0] == draft[0]
    asyncio.run(core.publish_post(ctx, draft[0]))
    assert core.db.get_topic(root)[4] == "used"
    # Future scheduler tick prepares a successor without publishing it.
    asyncio.run(core.automation_job(ctx))
    successor = core.db.ready_topic_post()
    assert successor is not None and successor[0] != draft[0]
    assert core.db.get_post(successor[0])[4] == "draft"


def test_scheduler_never_bypasses_approval(core, monkeypatch):
    install_ai(monkeypatch, core)
    core.db.add_topic("ط±غŒط´ظ‡")
    core.db.start_automation("ط±غŒط´ظ‡", (datetime.now(timezone.utc)-timedelta(hours=1)).isoformat())
    ctx = context_for(core)
    asyncio.run(core.automation_job(ctx))
    assert core.db.ready_topic_post() is not None
    assert core.db.stats()[0] == 0
    for call in ctx.bot.send_message.call_args_list:
        assert call.kwargs["chat_id"] == 7


def test_generation_failure_releases_only_its_topic(core, monkeypatch):
    def fail(**kwargs):
        raise RuntimeError("offline failure")
    monkeypatch.setattr(core.ai, "generate_text", fail)
    root = core.db.add_topic("ط±غŒط´ظ‡")
    ctx = context_for(core)
    import pytest
    with pytest.raises(RuntimeError):
        asyncio.run(core.generate_topic_job(ctx, force_topic_id=root))
    assert core.db.get_topic(root)[4] == "pending"
    assert core.db.ready_topic_post() is None


def test_repeat_publish_is_noop(core, monkeypatch):
    install_ai(monkeypatch, core)
    ctx = context_for(core)
    post = core.db.create_post("ظ…ظˆط¶ظˆط¹", "ظ…طھظ†")
    asyncio.run(core.publish_post(ctx, post))
    before = ctx.bot.send_message.call_count
    asyncio.run(core.publish_post(ctx, post))
    assert ctx.bot.send_message.call_count == before
'''


def patch_tree(bot, database, replace_exact):
    migration = '''            # Additive migration: old posts keep a NULL topic reference.
            post_columns = {r[1] for r in c.execute("PRAGMA table_info(posts)").fetchall()}
            if "topic_id" not in post_columns:
                c.execute("ALTER TABLE posts ADD COLUMN topic_id INTEGER")
            if "topics_extracted" not in post_columns:
                c.execute("ALTER TABLE posts ADD COLUMN topics_extracted INTEGER NOT NULL DEFAULT 0")
            c.execute("CREATE INDEX IF NOT EXISTS idx_posts_topic ON posts(topic_id)")
'''
    database = replace_exact(database, '            c.commit()\n\n    def create_post(', migration + '            c.commit()\n\n    def create_post(')
    database += '\n' + DB_METHODS
    bot = replace_exact(bot,
        'from admin_panel import register_admin_handlers, admin_text_message',
        'from admin_panel import register_admin_handlers, admin_text_message, _next_run')
    bot = replace_exact(bot, 'def is_admin(user_id):', TREE_HELPERS + '\n\ndef is_admin(user_id):')
    bot = function_replace(bot, 'publish_post', PUBLISH)
    bot = function_replace(bot, 'generate_topic_job', GENERATE_TOPIC)
    bot = function_replace(bot, 'automation_job', AUTOMATION)
    bot = function_replace(bot, 'starttopic_command', START_TOPIC)
    bot = replace_exact(bot, '    register_admin_handlers(application)\n', '    db.recover_orphan_topics()\n    register_admin_handlers(application)\n')
    marker = '    if action == "approve":'
    guard = '''    if action in {"approve", "reject", "regenerate", "edit"} and post[4] != "draft":
        await query.message.reply_text("ط§غŒظ† ظ¾ط³طھ ط¯غŒع¯ط± ظ¾غŒط´â€Œظ†ظˆغŒط³ ظ‚ط§ط¨ظ„ طھط؛غŒغŒط± ظ†غŒط³طھ.")
        return

'''
    bot = replace_exact(bot, marker, guard + marker)
    bot = replace_exact(bot,
        '        db.update_post(\n            post_id,\n            "rejected",\n        )',
        '        db.finish_topic_post(post_id, "rejected")')
    return bot, database

README = '''# Telegram Content Bot â€” panel and topic-chain repair

Python 3.10+.
Install: `python -m pip install -r requirements.txt`
Test: `python -m pytest -q`
Start: `python bot.py`

Use the existing DEEPSEEK_API_KEY environment variable. No secret is packaged.
Required: TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, DEEPSEEK_API_KEY.
Defaults: DEEPSEEK_BASE_URL=https://cleanapis.com/v1,
DEEPSEEK_MODEL=deepseek-v4-flash-0731.
ADMIN_USER_IDS must contain the Telegram numeric IDs allowed to administer.

## Render
For a Git repository whose root contains bot.py:
Build command: pip install -r requirements.txt
Start command: python bot.py
For a ZIP deployment, extract it and run those commands INSIDE its project folder.
RENDER_EXTERNAL_URL selects webhook mode; otherwise polling is used.
Use a persistent disk and point DATABASE_PATH to its mounted location.
Do not replace an existing database with a fresh packaged database.

## Topic pipeline
/starttopic creates the root, enables automation, and prepares its first post.
Children are extracted when a draft is generated, rather than only after publication.
The database records parent IDs, depth, source post, and post-to-topic association.
With approval disabled, the first post is published immediately and one successor
is prepared and stored for the scheduled publication. Scheduler ticks maintain
one prepared topic draft; they do not generate an unbounded batch of posts.
With approval enabled, topic drafts are sent to admins with approval buttons;
the scheduler NEVER publishes them without manual approval. After approval or
rejection the next tick can prepare the successor. Approval buttons remain
immediate-publication controls, not scheduled approval flags.
Changing the root does not erase the previous queue; pending topics remain FIFO
within depth. A topic extracted from a later-rejected draft may remain in the queue.

Start time uses UTC, matching the previous scheduler. First scheduled run uses
the next occurrence of HH:MM; subsequent runs use interval_hours. TIMEZONE is not
used to interpret this field in this repair.

## Database migration â€” back up before first launch
First launch adds nullable posts.topic_id, posts.topics_extracted (default 0),
and an index. No table or old post is dropped. Old drafts cannot be reliably
linked to old topics, so no inferred linkage is created. Orphan processing topics
without a linked draft return to pending; check legacy drafts for duplicates.
Make a consistent SQLite backup before deploying; stop the old bot or use the
SQLite backup API. Do not copy only the .db file while WAL writes are active.
Only one bot instance should use this SQLite deployment.

## Remaining limitations
Image settings are stored only; no new image service is added.
Research flag remains unconnected. Existing raw error reporting still requires
security hardening. Telegram delivery and SQLite cannot form one transaction:
a crash after send but before commit can still cause a duplicate on retry.
Child-topic extraction retries reuse deduplication, but are not one atomic batch.
An API 402 insufficient_quota requires usable provider balance; no code repair
can produce real posts when the API rejects generation.
Tests are offline tests and have NOT been executed by the authoring assistant.
Real API, Telegram, Render and persistence acceptance tests must be run separately.
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('zip_path', type=Path)
    parser.add_argument('--output', type=Path, default=Path('telegram-content-bot-fixed.zip'))
    args = parser.parse_args()
    output = args.output.resolve()
    if not args.zip_path.is_file():
        raise RuntimeError('Original ZIP not found')
    if output.exists():
        raise RuntimeError('Output exists; choose another --output')
    with tempfile.TemporaryDirectory(prefix='bot-repair-') as temporary:
        temp = Path(temporary)
        source = temp / 'original'
        source.mkdir()
        expected = {'bot.py','ai.py','config.py','db.py','admin_panel.py','requirements.txt','test_smoke.py','.gitignore'}
        # Read only the reviewed project's expected source files, not arbitrary paths.
        with zipfile.ZipFile(args.zip_path) as z:
            for name in expected:
                entry = 'telegram-content-bot-main/' + name
                content = z.read(entry).decode('utf-8')
                (source / name).write_text(content, encoding='utf-8')
        patch_path = temp / 'stage1.py'
        with urllib.request.urlopen(STAGE1_URL, timeout=60) as response:
            patch_path.write_bytes(response.read())
        stage1 = runpy.run_path(str(patch_path))
        replace_exact = stage1['replace_exact']
        bot = stage1['patch_bot']((source/'bot.py').read_text(encoding='utf-8'))
        panel = stage1['patch_panel']((source/'admin_panel.py').read_text(encoding='utf-8'))
        database = (source/'db.py').read_text(encoding='utf-8')
        bot, database = patch_tree(bot, database, replace_exact)
        requirements = replace_exact((source/'requirements.txt').read_text(encoding='utf-8'),
            'python-telegram-bot[webhooks,jobs]>=22,<23',
            'python-telegram-bot[webhooks,job-q
