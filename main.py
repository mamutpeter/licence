import os
import json
import asyncio
from datetime import datetime, date

from telegram import (
    Update, Bot, ReplyKeyboardMarkup, ReplyKeyboardRemove,
    InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from utils_db import (
    get_pool, ensure_tables, fetch_license,
    upsert_license, licenses_expiring
)

# === Конфігурація ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
ALLOWED_USER_IDS = [5826122049, 6887361815]

# === Дані магазинів і кіосків ===
with open("store_ids_shops.json", "r", encoding="utf-8") as f:
    STORE_SHOPS = json.load(f)
with open("store_ids_kiosks.json", "r", encoding="utf-8") as f:
    STORE_KIOSKS = json.load(f)

user_states = {}

main_keyboard = ReplyKeyboardMarkup([
    ["🍷 Алкоголь", "🚬 Тютюн"]
], resize_keyboard=True, one_time_keyboard=True)

group_keyboard = ReplyKeyboardMarkup([
    ["🏪 Магазини", "🚬 Кіоски"]
], resize_keyboard=True, one_time_keyboard=True)

# === Обробники Telegram ===

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
        await update.message.reply_text("⛔️ У вас немає доступу до цього бота.")
        return

    if not state:
        return await start(update, context)

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
        stores = STORE_SHOPS if state["group"] == "shop" else STORE_KIOSKS
        state["stores"] = stores
        state["step"] = "choose_store"

        msg = "Список точок:\n"
        for sid, addr in stores.items():
            msg += f"{sid}. {addr}\n"
        await update.message.reply_text(msg)
        return await update.message.reply_text("🔢 Введіть ідентифікатор торгової точки:")

    if state["step"] == "choose_store":
        store_id = text.strip()
        if store_id not in state["stores"]:
            return await update.message.reply_text("❌ Невірний ідентифікатор. Спробуйте ще раз.")
        state["store_id"] = store_id

        row = await fetch_license(state["group"], store_id, state["license_type"])
        if row:
            date_start = row["start_date"].strftime("%d.%m.%Y")
            date_end = row["end_date"].strftime("%d.%m.%Y")
            days_left = (row["end_date"] - date.today()).days

            msg = (f"📄 Ліцензія:\n"
                   f"Початок: {date_start}\n"
                   f"Завершення: {date_end}\n"
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
            date_start = datetime.strptime(state["date_start"], "%d.%m.%Y").date()
            date_end = datetime.strptime(text, "%d.%m.%Y").date()
            await upsert_license(state["group"], state["store_id"], state["license_type"], date_start, date_end)
            await update.message.reply_text("✅ Дати збережено!", reply_markup=ReplyKeyboardRemove())
            user_states.pop(chat_id, None)
        except:
            await update.message.reply_text("❌ Невірний формат дати. Використовуйте ДД.ММ.РРРР")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id

    if query.data == "update_dates":
        user_states[chat_id] = {
            "step": "enter_date_start",
            "group": None,
            "store_id": None,
            "license_type": None
        }
        await query.message.reply_text("📅 Введіть нову дату початку ліцензії (ДД.ММ.РРРР):")

# === Нагадування ===

async def reminder_check():
    rows = await licenses_expiring(3)
    bot = Bot(BOT_TOKEN)

    for r in rows:
        stores = STORE_SHOPS if r["group_type"] == "shop" else STORE_KIOSKS
        name = stores.get(r["store_id"], f"ID {r['store_id']}")
        msg = (f"⏰ Через 3 дні завершується ліцензія на {'алкоголь' if r['license_type'] == 'alcohol' else 'тютюн'}!\n"
               f"🏪 {name}\n"
               f"Дата завершення: {r['end_date'].strftime('%d.%m.%Y')}")
        for uid in ALLOWED_USER_IDS:
            await bot.send_message(uid, msg)

# === Старт системи ===

if __name__ == "__main__":
    async def run():
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

    asyncio.run(run())
