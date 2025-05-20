import os
import json
import asyncio
import threading
from datetime import datetime, timedelta
from flask import Flask, request
from telegram import Update, Bot, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters
)
from docx import Document
from apscheduler.schedulers.background import BackgroundScheduler

# === Конфігурація ===
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://yourdomain.com")
PORT = int(os.environ.get("PORT", 10000))
LICENSE_DATE_FILE = "license_date.json"
STORE_KIOSKS_FILE = "store_ids_kiosks.json"
STORE_SHOPS_FILE = "store_ids_shops.json"
TEMPLATE_FILE = "template_zayava.docx"
OUTPUT_DOCX = "zayava_ready.docx"
ALLOWED_USER_IDS = [5826122049, 6887361815]

user_states = {}

keyboard = ReplyKeyboardMarkup([[
    "➕ Додати оплату", "✅ Завершити"
]], resize_keyboard=True, one_time_keyboard=True)

main_keyboard = ReplyKeyboardMarkup([
    ["🏪 Магазини", "🚬 Кіоски"]
], resize_keyboard=True, one_time_keyboard=True)

type_keyboard = ReplyKeyboardMarkup([
    ["🍷 Алкоголь", "🚬 Тютюн"]
], resize_keyboard=True, one_time_keyboard=True)

# === Telegram handlers ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in ALLOWED_USER_IDS:
        await update.message.reply_text("⛔️ У вас немає доступу до цього бота.")
        return
    await update.message.reply_text("👋 Оберіть з чим хочете працювати:", reply_markup=main_keyboard)

async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    shops = load_store_group(STORE_SHOPS_FILE)
    msg = "🏪 Магазини (алкоголь + тютюн):\n"
    for sid, addr in shops.items():
        msg += f"{sid}. {addr}\n"
    await update.message.reply_text(msg)
    user_states[update.effective_chat.id] = {"step": "license_type", "data": {}, "group": "shop"}
    await update.message.reply_text("🍷 Оберіть тип ліцензії:", reply_markup=type_keyboard)

async def kiosk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kiosks = load_store_group(STORE_KIOSKS_FILE)
    msg = "🚬 Кіоски (тільки тютюн):\n"
    for sid, addr in kiosks.items():
        msg += f"{sid}. {addr}\n"
    await update.message.reply_text(msg)
    user_states[update.effective_chat.id] = {"step": "license_type", "data": {}, "group": "kiosk"}
    await update.message.reply_text("🍷 Оберіть тип ліцензії:", reply_markup=type_keyboard)

async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in ALLOWED_USER_IDS:
        await update.message.reply_text("⛔️ У вас немає доступу до цього бота.")
        return

    text = update.message.text.strip()
    state = user_states.get(chat_id)

    if text == "🏪 Магазини":
        return await shop(update, context)
    if text == "🚬 Кіоски":
        return await kiosk(update, context)

    if not state:
        return await update.message.reply_text("⚠️ Почніть з /start.")

    if state["step"] == "license_type":
        if text not in ["🍷 Алкоголь", "🚬 Тютюн"]:
            return await update.message.reply_text("❌ Виберіть одну з кнопок.", reply_markup=type_keyboard)
        state["license_type"] = "alcohol" if text == "🍷 Алкоголь" else "tobacco"
        state["step"] = 1
        state["data"]["payments"] = []
        return await update.message.reply_text("📥 Введіть код класифікації доходів бюджету:", reply_markup=ReplyKeyboardRemove())

    if state["step"] == 1:
        state["current"] = {"code": text}
        state["step"] = 2
        return await update.message.reply_text("📥 Введіть суму:")
    if state["step"] == 2:
        state["current"]["amount"] = text
        state["step"] = 3
        return await update.message.reply_text("📥 Введіть № інструкції:")
    if state["step"] == 3:
        state["current"]["instr_number"] = text
        state["step"] = 4
        return await update.message.reply_text("📥 Введіть дату інструкції:")
    if state["step"] == 4:
        state["current"]["instr_date"] = text
        state["data"]["payments"].append(state["current"])
        state["step"] = 6
        return await update.message.reply_text("➕ Додати ще одну оплату чи ✅ Завершити?", reply_markup=keyboard)
    if state["step"] == 6:
        if text == "➕ Додати оплату":
            state["step"] = 1
            return await update.message.reply_text("📥 Введіть код класифікації доходів бюджету:", reply_markup=ReplyKeyboardRemove())
        elif text == "✅ Завершити":
            state["step"] = 7
            return await update.message.reply_text("📅 Введіть ІДЕНТИФІКАТОР магазину:")
        else:
            return await update.message.reply_text("Оберіть кнопку:", reply_markup=keyboard)
    if state["step"] == 7:
        try:
            store_id = int(text)
            state["store_id"] = store_id
            state["step"] = 8
            return await update.message.reply_text("📅 Введіть дату завершення ліцензії у форматі ДД.ММ.РРРР:")
        except ValueError:
            return await update.message.reply_text("❌ Невірний формат ІД магазину. Спробуйте ще раз.")
    if state["step"] == 8:
        try:
            datetime.strptime(text, "%d.%m.%Y")
            save_license_date(text, state["store_id"], state["group"])
            path = generate_docx(state["data"]["payments"])
            if path:
                await update.message.reply_document(open(path, "rb"), reply_markup=ReplyKeyboardRemove())
                await update.message.reply_text("✅ Заяву сформовано та збережено дату ліцензії!", reply_markup=main_keyboard)
            else:
                await update.message.reply_text("❌ Помилка генерації документа.", reply_markup=main_keyboard)
        except ValueError:
            await update.message.reply_text("❌ Невірний формат дати. Спробуйте ще раз.")
        user_states.pop(chat_id, None)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📋 Оберіть тип ліцензії для перевірки:", reply_markup=type_keyboard)
    user_states[update.effective_chat.id] = {"step": "status_type"}


def reminder_check():
    data = load_license_date()
    shops = load_store_group(STORE_SHOPS_FILE)
    kiosks = load_store_group(STORE_KIOSKS_FILE)
    today = datetime.now().date()

    def send_async(store_id, date_str, address):
        async def notify():
            bot = Bot(BOT_TOKEN)
            await bot.send_message(
                chat_id=ALLOWED_USER_IDS[0],
                text=f"⏰ Через 3 дні завершується дія ліцензії ({date_str})!\n🏪 {address}\nВиконай /start"
            )
        asyncio.run(notify())

    for store_id, value in data.items():
        try:
            date_str = value["date"]
            store_type = value.get("type", "shop")
            lic_date = datetime.strptime(date_str, "%d.%m.%Y").date()
            if (lic_date - today).days == 3:
                group = shops if store_type == "shop" else kiosks
                address = group.get(str(store_id), f"ID {store_id}")
                threading.Thread(target=send_async, args=(store_id, date_str, address)).start()
        except:
            continue

# === Telegram + Flask ===
app = Flask(__name__)
tg_app = Application.builder().token(BOT_TOKEN).build()
main_loop = asyncio.new_event_loop()
asyncio.set_event_loop(main_loop)
main_loop.run_until_complete(tg_app.initialize())
tg_app.add_handler(CommandHandler("start", start))
tg_app.add_handler(CommandHandler("status", status))
tg_app.add_handler(CommandHandler("shop", shop))
tg_app.add_handler(CommandHandler("kiosk", kiosk))
tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_input))

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
