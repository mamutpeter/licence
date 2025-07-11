import os
import json
import asyncio
from datetime import datetime, timedelta
import asyncpg
from telegram import Update, Bot, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# === Конфігурація ===
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
DB_URL = os.getenv("DATABASE_URL")
ALLOWED_USER_IDS = [5826122049, 6887361815]

STORE_KIOSKS_FILE = "store_ids_kiosks.json"
STORE_SHOPS_FILE = "store_ids_shops.json"

user_states = {}

main_keyboard = ReplyKeyboardMarkup([
    ["🍷 Алкоголь", "🚬 Тютюн"]
], resize_keyboard=True, one_time_keyboard=True)

group_keyboard = ReplyKeyboardMarkup([
    ["🏪 Магазини", "🚬 Кіоски"]
], resize_keyboard=True, one_time_keyboard=True)

# === Допоміжні функції ===

async def get_pool():
    return await asyncpg.create_pool(DB_URL)

async def load_store_group(file):
    with open(file, "r", encoding="utf-8") as f:
        return json.load(f)

async def get_license(pool, key):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT start_date, end_date FROM licenses WHERE key=$1", key)
        return dict(row) if row else None

async def save_license(pool, key, start, end):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO licenses(key, start_date, end_date)
            VALUES ($1, $2, $3)
            ON CONFLICT (key) DO UPDATE SET start_date=$2, end_date=$3
        """, key, start, end)

# === Telegram Handlers ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in ALLOWED_USER_IDS:
        await update.message.reply_text("⛔️ У вас немає доступу до цього бота.")
        return
    user_states[chat_id] = {"step": "choose_type"}
    await update.message.reply_text("🍷 Оберіть тип ліцензії:", reply_markup=main_keyboard)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text.strip()
    state = user_states.get(chat_id)
    if chat_id not in ALLOWED_USER_IDS:
        return
    if not state:
        return await start(update, context)

    pool = context.bot_data["pool"]

    if state["step"] == "choose_type":
        if text not in ["🍷 Алкоголь", "🚬 Тютюн"]:
            return await update.message.reply_text("❌ Виберіть одну з кнопок.", reply_markup=main_keyboard)
        state["license_type"] = "alcohol" if text == "🍷 Алкоголь" else "tobacco"
        state["step"] = "choose_group"
        return await update.message.reply_text("🏪 Оберіть тип торгової точки:", reply_markup=group_keyboard)

    if state["step"] == "choose_group":
        if text not in ["🏪 Магазини", "🚬 Кіоски"]:
            return await update.message.reply_text("❌ Виберіть одну з кнопок.", reply_markup=group_keyboard)
        state["group"] = "shop" if text == "🏪 Магазини" else "kiosk"
        group_file = STORE_SHOPS_FILE if state["group"] == "shop" else STORE_KIOSKS_FILE
        stores = await load_store_group(group_file)
        state["stores"] = stores
        state["step"] = "choose_store"
        msg = "Список точок:\n" + "\n".join([f"{k}. {v}" for k, v in stores.items()])
        await update.message.reply_text(msg)
        return await update.message.reply_text("🔢 Введіть ідентифікатор торгової точки:")

    if state["step"] == "choose_store":
        store_id = text.strip()
        if store_id not in state["stores"]:
            return await update.message.reply_text("❌ Невірний ідентифікатор. Спробуйте ще раз.")
        state["store_id"] = store_id

        key = f"{state['group']}_{store_id}_{state['license_type']}"
        license_data = await get_license(pool, key)

        if license_data:
            date_start = license_data['start_date']
            date_end = license_data['end_date']
            days_left = (date_end - datetime.now().date()).days
            msg = (f"📄 Ліцензія:\n"
                   f"Початок: {date_start.strftime('%d.%m.%Y')}\n"
                   f"Завершення: {date_end.strftime('%d.%m.%Y')}\n"
                   f"⏳ Залишилось: {days_left} днів")
            buttons = [[InlineKeyboardButton("🔄 Оновити дати", callback_data="update_dates")]]
            reply_markup = InlineKeyboardMarkup(buttons)
            await update.message.reply_text(msg, reply_markup=reply_markup)
            user_states.pop(chat_id, None)
        else:
            state["step"] = "enter_date_start"
            await update.message.reply_text("📅 Введіть дату початку ліцензії (ДД.ММ.РРРР):")

    elif state["step"] == "enter_date_start":
        try:
            datetime.strptime(text, "%d.%m.%Y")
            state["date_start"] = text
            state["step"] = "enter_date_end"
            await update.message.reply_text("📅 Введіть дату закінчення ліцензії (ДД.ММ.РРРР):")
        except:
            await update.message.reply_text("❌ Невірний формат дати. Використовуйте ДД.ММ.РРРР")

    elif state["step"] == "enter_date_end":
        try:
            start = datetime.strptime(state["date_start"], "%d.%m.%Y").date()
            end = datetime.strptime(text, "%d.%m.%Y").date()
            key = f"{state['group']}_{state['store_id']}_{state['license_type']}"
            await save_license(pool, key, start, end)
            await update.message.reply_text("✅ Дати збережено!", reply_markup=ReplyKeyboardRemove())
            user_states.pop(chat_id, None)
        except:
            await update.message.reply_text("❌ Невірний формат дати. Використовуйте ДД.ММ.РРРР")

# === Callback Handler ===

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    user_states[chat_id] = {"step": "enter_date_start"}
    await query.message.reply_text("📅 Введіть нову дату початку ліцензії (ДД.ММ.РРРР):")

# === Старт бота ===

async def main():
    app = Application.builder().token(BOT_TOKEN).build()
    pool = await get_pool()
    app.bot_data["pool"] = pool

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))

    scheduler = AsyncIOScheduler()
    scheduler.start()

    print("✅ Бот запущено")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
