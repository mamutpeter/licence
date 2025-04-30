import os
import json
import asyncio
from datetime import datetime, timedelta
from flask import Flask, request
from telegram import Update, Bot, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from docx import Document
from apscheduler.schedulers.background import BackgroundScheduler

BOT_TOKEN = "7685520910:AAH5Yx8uhW0Ry3ozQjsMjNPGlMBUadkfTno"
WEBHOOK_URL = "https://dochelp-ctqw.onrender.com"
PORT = int(os.environ.get("PORT", 10000))

LICENSE_DATE_FILE = "license_date.json"
TEMPLATE_FILE = "template_zayava.docx"
OUTPUT_DOCX = "zayava_ready.docx"
ALLOWED_USER_IDS = [5826122049, 6887361815]

user_states = {}

keyboard = ReplyKeyboardMarkup([["➕ Додати оплату", "✅ Завершити"]],
                               resize_keyboard=True, one_time_keyboard=True)

def load_license_data():
    if os.path.exists(LICENSE_DATE_FILE):
        with open(LICENSE_DATE_FILE, "r") as f:
            return json.load(f)
    return {}

def save_license_data(data):
    with open(LICENSE_DATE_FILE, "w") as f:
        json.dump(data, f, indent=2)

def generate_docx(payments):
    doc = Document(TEMPLATE_FILE)
    target_table = next((t for t in doc.tables if "9.1." in t.cell(0, 0).text), None)
    if target_table:
        for row in target_table.rows[1:]:
            row._element.getparent().remove(row._element)
        for p in payments:
            row = target_table.add_row()
            row.cells[0].text = p["code"]
            row.cells[1].text = p["amount"]
            row.cells[2].text = p["instr_number"]
            row.cells[3].text = p["instr_date"]
        os.makedirs("pdfs", exist_ok=True)
        path = os.path.join("pdfs", OUTPUT_DOCX)
        doc.save(path)
        return path
    return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in ALLOWED_USER_IDS:
        return await update.message.reply_text("⛔️ Немає доступу.")

    user_states[chat_id] = {"step": 1, "data": {"payments": []}}
    await update.message.reply_text("📥 Введіть код класифікації доходів бюджету:", reply_markup=ReplyKeyboardRemove())

async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in user_states:
        return await update.message.reply_text("⚠️ Почніть з /start")

    text = update.message.text.strip()
    state = user_states[chat_id]

    if state["step"] == 1:
        state["current"] = {"code": text}
        state["step"] = 2
        await update.message.reply_text("📥 Введіть суму:")
    elif state["step"] == 2:
        state["current"]["amount"] = text
        state["step"] = 3
        await update.message.reply_text("📥 Введіть № інструкції:")
    elif state["step"] == 3:
        state["current"]["instr_number"] = text
        state["step"] = 4
        await update.message.reply_text("📥 Введіть дату інструкції:")
    elif state["step"] == 4:
        state["current"]["instr_date"] = text
        state["data"]["payments"].append(state["current"])
        state["step"] = 5
        await update.message.reply_text("➕ Додати ще одну оплату чи ✅ Завершити?", reply_markup=keyboard)
    elif state["step"] == 5:
        if text == "➕ Додати оплату":
            state["step"] = 1
            await update.message.reply_text("📥 Введіть код класифікації доходів бюджету:", reply_markup=ReplyKeyboardRemove())
        elif text == "✅ Завершити":
            state["step"] = 6
            await update.message.reply_text("🏪 Введіть ID магазину:")
    elif state["step"] == 6:
        state["store_id"] = text
        state["step"] = 7
        await update.message.reply_text("📅 Введіть дату завершення ліцензії (ДД.ММ.РРРР):")
    elif state["step"] == 7:
        try:
            datetime.strptime(text, "%d.%m.%Y")
            data = load_license_data()
            data[state["store_id"]] = text
            save_license_data(data)
            path = generate_docx(state["data"]["payments"])
            if path:
                await update.message.reply_document(open(path, "rb"))
                await update.message.reply_text("✅ Заяву сформовано!")
            else:
                await update.message.reply_text("❌ Помилка при створенні документа.")
        except:
            await update.message.reply_text("❌ Неправильна дата. Введіть у форматі ДД.ММ.РРРР.")
        user_states.pop(chat_id, None)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_license_data()
    if not data:
        return await update.message.reply_text("ℹ️ Дані про ліцензії не знайдено.")

    today = datetime.today()
    msg = "📋 Стан ліцензій:\n"
    for store_id, date_str in data.items():
        try:
            end_date = datetime.strptime(date_str, "%d.%m.%Y")
            days = (end_date - today).days
            msg += f"🏪 Магазин {store_id}: {date_str} ({days} дн.)\n"
        except:
            continue
    await update.message.reply_text(msg)

def reminder_check():
    data = load_license_data()
    today = datetime.today().date()
    for store_id, date_str in data.items():
        try:
            end = datetime.strptime(date_str, "%d.%m.%Y").date()
            if end - timedelta(days=3) == today:
                async def send_notification():
                    bot = Bot(BOT_TOKEN)
                    for uid in ALLOWED_USER_IDS:
                        await bot.send_message(uid, f"⏰ Через 3 дні закінчується ліцензія магазину {store_id} ({date_str})!")
                asyncio.run(send_notification())
        except:
            continue

# === Flask + Telegram app
app = Flask(__name__)
tg_app = Application.builder().token(BOT_TOKEN).build()
tg_app.add_handler(CommandHandler("start", start))
tg_app.add_handler(CommandHandler("status", status))
tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_input))

scheduler = BackgroundScheduler()
scheduler.add_job(reminder_check, "interval", hours=12)
scheduler.start()

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    update = Update.de_json(data, tg_app.bot)
    asyncio.get_event_loop().run_until_complete(tg_app.process_update(update))
    return "ok"

if __name__ == "__main__":
    print("🔄 Старт сервера...")
    asyncio.get_event_loop().run_until_complete(Bot(BOT_TOKEN).set_webhook(f"{WEBHOOK_URL}/webhook"))
    asyncio.get_event_loop().run_until_complete(tg_app.initialize())
    asyncio.get_event_loop().create_task(tg_app.start())
    app.run(host="0.0.0.0", port=PORT)
