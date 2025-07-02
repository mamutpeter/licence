import os
import json
import asyncio
import threading
from datetime import datetime, timedelta
from flask import Flask, request
from telegram import Update, Bot, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
)
from apscheduler.schedulers.background import BackgroundScheduler

# === Конфігурація ===
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://yourdomain.com")
PORT = int(os.environ.get("PORT", 10000))
LICENSE_DATE_FILE = "license_date.json"
STORE_KIOSKS_FILE = "store_ids_kiosks.json"
STORE_SHOPS_FILE = "store_ids_shops.json"
ALLOWED_USER_IDS = [5826122049, 6887361815]

user_states = {}

main_keyboard = ReplyKeyboardMarkup([
    ["🍷 Алкоголь", "🚬 Тютюн"]
], resize_keyboard=True, one_time_keyboard=True)

group_keyboard = ReplyKeyboardMarkup([
    ["🏪 Магазини", "🚬 Кіоски"]
], resize_keyboard=True, one_time_keyboard=True)

# === Допоміжні функції ===

def load_store_group(file):
    with open(file, "r", encoding="utf-8") as f:
        return json.load(f)

def load_license_date():
    if os.path.exists(LICENSE_DATE_FILE):
        with open(LICENSE_DATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_license_date(data):
    with open(LICENSE_DATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

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
        group_file = STORE_SHOPS_FILE if state["group"] == "shop" else STORE_KIOSKS_FILE
        stores = load_store_group(group_file)
        msg = "Список точок:\n"
        for sid, addr in stores.items():
            msg += f"{sid}. {addr}\n"
        state["stores"] = stores
        state["step"] = "choose_store"
        await update.message.reply_text(msg)
        return await update.message.reply_text("🔢 Введіть ідентифікатор торгової точки:")

    if state["step"] == "choose_store":
        store_id = text.strip()
        if store_id not in state["stores"]:
            return await update.message.reply_text("❌ Невірний ідентифікатор. Спробуйте ще раз.")
        state["store_id"] = store_id

        key = f"{state['group']}_{store_id}_{state['license_type']}"
        licenses = load_license_date()

        if key in licenses:
            date_start = licenses[key]["start"]
            date_end = licenses[key]["end"]
            days_left = (datetime.strptime(date_end, "%d.%m.%Y") - datetime.now()).days

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
            datetime.strptime(text, "%d.%m.%Y")
            key = f"{state['group']}_{state['store_id']}_{state['license_type']}"
            licenses = load_license_date()
            licenses[key] = {
                "start": state["date_start"],
                "end": text
            }
            save_license_date(licenses)
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

        # Витягнемо з повідомлення ID магазину і тип ліцензії (можна покращити)
        await query.message.reply_text("📅 Введіть нову дату початку ліцензії (ДД.ММ.РРРР):")

# === Нагадування ===

def reminder_check():
    licenses = load_license_date()
    shops = load_store_group(STORE_SHOPS_FILE)
    kiosks = load_store_group(STORE_KIOSKS_FILE)
    today = datetime.now().date()

    def send_async(msg):
        async def notify():
            bot = Bot(BOT_TOKEN)
            for uid in ALLOWED_USER_IDS:
                await bot.send_message(chat_id=uid, text=msg)
        asyncio.run(notify())

    for key, data in licenses.items():
        group, store_id, license_type = key.split("_")
        lic_date = datetime.strptime(data["end"], "%d.%m.%Y").date()
        days_left = (lic_date - today).days
        if days_left == 3:
            store_name = (shops if group == "shop" else kiosks).get(store_id, f"ID {store_id}")
            msg = (f"⏰ Через 3 дні завершується ліцензія на {'алкоголь' if license_type == 'alcohol' else 'тютюн'}!\n"
                   f"🏪 {store_name}\n"
                   f"Дата завершення: {data['end']}")
            threading.Thread(target=send_async, args=(msg,)).start()

# === Flask + Telegram ===

app = Flask(__name__)
tg_app = Application.builder().token(BOT_TOKEN).build()
main_loop = asyncio.new_event_loop()
asyncio.set_event_loop(main_loop)
main_loop.run_until_complete(tg_app.initialize())
tg_app.add_handler(CommandHandler("start", start))
tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
tg_app.add_handler(CallbackQueryHandler(handle_callback))

scheduler = BackgroundScheduler()
scheduler.add_job(reminder_check, "interval", hours=12)
scheduler.start()

def run_loop_forever(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

def process_async_update(update):
    asyncio.run_coroutine_threadsafe(tg_app.process_update(update), main_loop)

@app.route('/webhook', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(force=True), tg_app.bot)
    threading.Thread(target=process_async_update, args=(update,)).start()
    return "ok"

if __name__ == "__main__":
    print("🔄 Старт сервера...")
    bot = Bot(BOT_TOKEN)
    main_loop.run_until_complete(bot.set_webhook(f"{WEBHOOK_URL}/webhook"))
    threading.Thread(target=run_loop_forever, args=(main_loop,), daemon=True).start()
    app.run(host="0.0.0.0", port=PORT)
