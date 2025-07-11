import os
import json
from datetime import datetime, date

from telegram import Update, Bot, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from utils_db import get_pool, ensure_tables, fetch_license, upsert_license, licenses_expiring

BOT_TOKEN = os.getenv("BOT_TOKEN")
ALLOWED_USER_IDS = [5826122049, 6887361815]

with open("store_ids_shops.json", "r", encoding="utf-8") as f:
    STORE_SHOPS = json.load(f)
with open("store_ids_kiosks.json", "r", encoding="utf-8") as f:
    STORE_KIOSKS = json.load(f)

user_states = {}

main_keyboard = ReplyKeyboardMarkup([["🍷 Алкоголь", "🚬 Тютюн"]], resize_keyboard=True, one_time_keyboard=True)
group_keyboard = ReplyKeyboardMarkup([["🏪 Магазини", "🚬 Кіоски"]], resize_keyboard=True, one_time_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in ALLOWED_USER_IDS:
        await update.message.reply_text("⛔️ У вас немає доступу до цього бота.")
        return
    user_states[chat_id] = {"step": "choose_type"}
    await update.message.reply_text("🍷 Оберіть тип ліцензії:", reply_markup=main_keyboard)

# (сюди вставляються handle_message і handle_callback з попередньої версії — без змін)

async def reminder_check():
    rows = await licenses_expiring(3)
    bot = Bot(BOT_TOKEN)

    for r in rows:
        stores = STORE_SHOPS if r["group_type"] == "shop" else STORE_KIOSKS
        name = stores.get(r["store_id"], f"ID {r['store_id']}")
        msg = (
            f"⏰ Через 3 дні завершується ліцензія на {'алкоголь' if r['license_type'] == 'alcohol' else 'тютюн'}!\n"
            f"🏪 {name}\n"
            f"Дата завершення: {r['end_date'].strftime('%d.%m.%Y')}"
        )
        for uid in ALLOWED_USER_IDS:
            await bot.send_message(uid, msg)

async def main():
    await ensure_tables()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(reminder_check, "interval", hours=12)
    scheduler.start()

    print("✅ Бот запущено")
    await app.run_polling()

# запуск без asyncio.run()
if __name__ == "__main__":
    import asyncio
    asyncio.get_event_loop().run_until_complete(main())
