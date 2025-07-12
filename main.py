import os
import json
import psycopg2
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, CallbackQueryHandler, Filters, CallbackContext
)
from apscheduler.schedulers.background import BackgroundScheduler
import pytz  # <-- ДОДАЙ ЦЕЙ ІМПОРТ

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

def get_conn():
    return psycopg2.connect(DB_URL)

def load_store_group(file):
    with open(file, "r", encoding="utf-8") as f:
        return json.load(f)

def get_license(key):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT start_date, end_date FROM licenses WHERE license_key=%s", (key,))
            row = cur.fetchone()
            if row:
                return {'start_date': datetime.strptime(row[0], "%Y-%m-%d").date(),
                        'end_date': datetime.strptime(row[1], "%Y-%m-%d").date()}
    return None

def save_license(key, start, end):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO licenses(license_key, start_date, end_date)
                VALUES (%s, %s, %s)
                ON CONFLICT (license_key) DO UPDATE SET start_date=%s, end_date=%s
            """, (key, start, end, start, end))
            conn.commit()

def start(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    if chat_id not in ALLOWED_USER_IDS:
        update.message.reply_text("⛔️ У вас немає доступу до цього бота.")
        return
    user_states[chat_id] = {"step": "choose_type"}
    update.message.reply_text("🍷 Оберіть тип ліцензії:", reply_markup=main_keyboard)

def handle_message(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    text = update.message.text.strip()
    state = user_states.get(chat_id)
    if chat_id not in ALLOWED_USER_IDS:
        return
    if not state:
        start(update, context)
        return

    if state["step"] == "choose_type":
        if text not in ["🍷 Алкоголь", "🚬 Тютюн"]:
            update.message.reply_text("❌ Виберіть одну з кнопок.", reply_markup=main_keyboard)
            return
        state["license_type"] = "alcohol" if text == "🍷 Алкоголь" else "tobacco"
        state["step"] = "choose_group"
        update.message.reply_text("🏪 Оберіть тип торгової точки:", reply_markup=group_keyboard)
        return

    if state["step"] == "choose_group":
        if text not in ["🏪 Магазини", "🚬 Кіоски"]:
            update.message.reply_text("❌ Виберіть одну з кнопок.", reply_markup=group_keyboard)
            return
        state["group"] = "shop" if text == "🏪 Магазини" else "kiosk"
        group_file = STORE_SHOPS_FILE if state["group"] == "shop" else STORE_KIOSKS_FILE
        stores = load_store_group(group_file)
        state["stores"] = stores
        state["step"] = "choose_store"
        msg = "Список точок:\n" + "\n".join([f"{k}. {v}" for k, v in stores.items()])
        update.message.reply_text(msg)
        update.message.reply_text("🔢 Введіть ідентифікатор торгової точки:")
        return

    if state["step"] == "choose_store":
        store_id = text.strip()
        if store_id not in state["stores"]:
            update.message.reply_text("❌ Невірний ідентифікатор. Спробуйте ще раз.")
            return
        state["store_id"] = store_id
        key = f"{state['group']}_{store_id}_{state['license_type']}"
        license_data = get_license(key)
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
            update.message.reply_text(msg, reply_markup=reply_markup)
            user_states.pop(chat_id, None)
            return
        else:
            state["step"] = "enter_date_start"
            update.message.reply_text("📅 Введіть дату початку ліцензії (ДД.ММ.РРРР):")
            return

    if state["step"] == "enter_date_start":
        try:
            date_start = datetime.strptime(text, "%d.%m.%Y").date()
            state["date_start"] = date_start
            state["step"] = "enter_date_end"
            update.message.reply_text("📅 Введіть дату закінчення ліцензії (ДД.ММ.РРРР):")
        except:
            update.message.reply_text("❌ Невірний формат дати. Використовуйте ДД.ММ.РРРР")
        return

    if state["step"] == "enter_date_end":
        try:
            date_end = datetime.strptime(text, "%d.%m.%Y").date()
            key = f"{state['group']}_{state['store_id']}_{state['license_type']}"
            save_license(key, state["date_start"], date_end)
            update.message.reply_text("✅ Дати збережено!", reply_markup=ReplyKeyboardRemove())
            user_states.pop(chat_id, None)
        except:
            update.message.reply_text("❌ Невірний формат дати. Використовуйте ДД.ММ.РРРР")
        return

def handle_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    chat_id = query.message.chat.id
    user_states[chat_id] = {"step": "enter_date_start"}
    query.message.reply_text("📅 Введіть нову дату початку ліцензії (ДД.ММ.РРРР):")

# ========== JOB ДЛЯ НАГАДУВАННЯ ==========
def check_licenses_job():
    now = datetime.now().date()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT license_key, start_date, end_date FROM licenses")
            for license_key, start_date, end_date in cur.fetchall():
                try:
                    end = datetime.strptime(end_date, "%Y-%m-%d").date()
                except:
                    continue  # Якщо дата зіпсована — ігнор
                days_left = (end - now).days
                if 0 < days_left <= 3:
                    for user_id in ALLOWED_USER_IDS:
                        msg = (
                            f"⏰ УВАГА! Ліцензія {license_key}\n"
                            f"Завершується через {days_left} дні!\n"
                            f"Дата завершення: {end.strftime('%d.%m.%Y')}\n"
                            f"Терміново поновіть ліцензію!"
                        )
                        try:
                            updater.bot.send_message(chat_id=user_id, text=msg)
                        except Exception as e:
                            print(f"Не вдалося надіслати повідомлення {user_id}: {e}")

def main():
    global updater  # updater має бути глобальним для job
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    dp.add_handler(CallbackQueryHandler(handle_callback))

    # Запускаємо JOB на фоні
    scheduler = BackgroundScheduler(timezone=pytz.timezone('Europe/Kiev'))  # <--- Виправлено!
    scheduler.add_job(check_licenses_job, "interval", hours=1)
    scheduler.start()

    print("✅ Бот запущено")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
