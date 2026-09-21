import logging,os
from pathlib import Path
from telegram import InlineKeyboardButton,InlineKeyboardMarkup,Update
from telegram.ext import Application,CallbackQueryHandler,CommandHandler,ContextTypes
from ai import AIService
from config import load_settings
from db import Database

logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO"),format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log=logging.getLogger(__name__)
settings=load_settings(); db=Database(settings.database_path)
ai=AIService(settings.openai_api_key,settings.openai_text_model,settings.openai_image_model)
IMG=Path("data/images"); IMG.mkdir(parents=True,exist_ok=True)

def ok(uid): return not settings.admin_user_ids or uid in settings.admin_user_ids
def kb(i): return InlineKeyboardMarkup([[InlineKeyboardButton("✅ انتشار",callback_data=f"publish:{i}"),InlineKeyboardButton("🗑 رد",callback_data=f"reject:{i}")]])

async def start(u,c):
    if u.effective_user and ok(u.effective_user.id): await u.message.reply_text("سلام! 🤖\n/newpost موضوع")
async def help_command(u,c):
    if u.effective_user and ok(u.effective_user.id): await u.message.reply_text("/start\n/newpost موضوع برای تولید متن و تصویر")
async def new_post(u,c):
    if not u.effective_user or not ok(u.effective_user.id): return
    topic=" ".join(c.args).strip()
    if not topic: await u.message.reply_text("مثال: /newpost درباره هوش مصنوعی"); return
    s=await u.message.reply_text("⏳ در حال ساخت متن و تصویر...")
    try:
        text=ai.generate_text(topic)
        await s.edit_text("🎨 متن آماده شد؛ تصویر اختصاصی در حال ساخت است...")
        data=ai.generate_image(topic,text)
        path=IMG/f"post_{os.urandom(8).hex()}.png"; path.write_bytes(data)
        i=db.create_post(topic,text,str(path)); await s.delete()
        with path.open("rb") as f: await u.message.reply_photo(f,caption=f"🎨 تصویر پیشنهادی پست #{i}")
        await u.message.reply_text(f"📝 پیش‌نمایش پست #{i}\n\n{text}",reply_markup=kb(i))
    except Exception:
        log.exception("generation failed"); await s.edit_text("❌ ساخت پست/تصویر ناموفق بود. Logs را بررسی کنید.")
async def callback(u,c):
    q=u.callback_query; await q.answer()
    if not q.from_user or not ok(q.from_user.id): return
    try: action,i=q.data.split(":"); i=int(i)
    except: await q.edit_message_text("❌ درخواست نامعتبر است."); return
    post=db.get_post(i)
    if not post: await q.edit_message_text("پست پیدا نشد."); return
    if action=="reject": db.update_post(i,"rejected"); await q.edit_message_text(f"🗑 پست #{i} رد شد."); return
    if action=="publish":
        try:
            if post[3] and Path(post[3]).exists():
                with Path(post[3]).open("rb") as f: await c.bot.send_photo(chat_id=settings.telegram_channel_id,photo=f)
            await c.bot.send_message(chat_id=settings.telegram_channel_id,text=post[2])
            db.update_post(i,"published"); await q.edit_message_text(f"✅ پست #{i} همراه تصویر منتشر شد.")
        except Exception:
            log.exception("publish failed"); await q.edit_message_text("❌ انتشار ناموفق بود. دسترسی ربات به کانال را بررسی کنید.")
def main():
    url=os.getenv("RENDER_EXTERNAL_URL","").rstrip("/")
    if not url: raise RuntimeError("RENDER_EXTERNAL_URL is required")
    app=Application.builder().token(settings.telegram_bot_token).build()
    app.add_handler(CommandHandler("start",start)); app.add_handler(CommandHandler("help",help_command))
    app.add_handler(CommandHandler("newpost",new_post)); app.add_handler(CallbackQueryHandler(callback))
    app.run_webhook(listen="0.0.0.0",port=int(os.getenv("PORT","10000")),url_path="telegram",
                    webhook_url=f"{url}/telegram",allowed_updates=Update.ALL_TYPES,drop_pending_updates=False)
if __name__=="__main__": main()
