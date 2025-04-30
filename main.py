import os
import json
import asyncio
from datetime import datetime, timedelta
from flask import Flask, request
from telegram import Update, Bot, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters
)
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

def load_all_licenses():
    if not os.path.exists(LICENSE_DATE_FILE):
        return {}
    with open(LICENSE_DATE_FILE, "r") as f:
        return json.load(f)

def save_all_licenses(data):
    with open(LICENSE_DATE_FILE, "w") as f:
        json.dump(data, f)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in ALLOWED_USER_IDS:
        await update.message.reply_text("⛔️ Немає доступу.")
        return
    user_states[chat_id] = {"step": 1, "data": {"payments": []}}
    await update.message.reply_text("📥 Введіть код класифікації доходів бюджету:")

async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text.strip()
    if chat_id not in user_states:
        return await update.message.reply_text("⚠️ Почніть з /start.")

    state = user_states[chat_id]
    step = state["step"]

    if step == 6:
        if text == "➕ Додати оплату":
            state["step"] = 1
            return await update.message.reply_text("📥 Введіть код класифікації доходів бюджету:", reply_markup=ReplyKeyboardRemove())
        elif text == "✅ Завершити":
            state["step"] = 7
            return await update.message.reply_text("📅 Введіть назву магазину та дату завершення ліцензії (Магазин, ДД.ММ.РРРР):")
        else:
            return await update.message.reply_text("Оберіть дію:", reply_markup=keyboard)

    if step == 7:
        try:
            parts = text.split(",")
            store = parts[0].strip()
            date_str = parts[1].strip()
            datetime.strptime(date_str, "%d.%m.%Y")
            data = load_all_licenses()
            data[store] = {"date": date_str, "chat_id": chat_id}
            save_all_licenses(data)

            path = generate_docx(state["data"]["payments"])
            if path:
                await update.message.reply_document(open(path, "rb"), reply_markup=ReplyKeyboardRemove())
                await update.message.reply_text("✅ Заяву сформовано та ліцензію збережено.")
            else:
                await update.message.reply_text("❌ Не вдалося створити заяву.")
        except:
            await update.message.reply_text("❌ Формат має бути: Магазин, 30.05.2025")
        user_states.pop(chat_id)
        return

    if step == 1:
        state["current"] = {"code": text}
        state["step"] = 2
        return await update.message.reply_text("📥 Введіть суму:")
    if step == 2:
        state["current"]["amount"] = text
        state["step"] = 3
        return await update.message.reply_text("📥 Введіть № інструкції:")
    if step == 3:
        state["current"]["instr_number"] = text
        state["step"] = 4
        return await update.message.reply_text("📥 Введіть дату інструкції:")
    if step == 4:
        state["current"]["instr_date"] = text
        state["data"]["payments"].append(state["current"])
        state["step"] = 6
        return await update.message.reply_text("➕ Додати ще одну чи ✅ Завершити?", reply_markup=keyboard)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in ALLOWED_USER_IDS:
        return await update.message.reply_text("⛔️ Немає доступу.")

    data = load_all_licenses()
    if not data:
        return await update.message.reply_text("📭 Даних немає.")
    
    today = datetime.now().date()
    rows = []
    for store, info in sorted(data.items()):
        try:
            date = datetime.strptime(info["date"], "%d.%m.%Y").date()
            days = (date - today).days
            rows.append(f"🏪 <b>{store}</b> — до {info['date']} ({days} днів)")
        except:
            rows.append(f"🏪 <b>{store}</b> — ❌ Невірна дата")

    await update.message.reply_text("\n".join(rows), parse_mode=ParseMode.HTML)

def reminder_check():
    data = load_all_licenses()
    today = datetime.now().date()
    for store, info in data.items():
        try:
            end = datetime.strptime(info["date"], "%d.%m.%Y").date()
            if (end - today).days == 3:
                async def send():
                    await Bot(BOT_TOKEN).send_message(info["chat_id"], f"⏰ Магазин {store}: через 3 дні завершується ліцензія ({info['date']})")
                asyncio.run(send())
        except:
            continue

# Flask + Telegram Webhook
app = Flask(__name__)
tg_app = Application.builder().token(BOT_TOKEN).build()
tg_app.add_handler(CommandHandler("start", start))
tg_app.add_handler(CommandHandler("status", status))
tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_input))

scheduler = BackgroundScheduler()
scheduler.add_job(reminder_check, "interval", hours=12)
scheduler.start()

@app.route('/webhook', methods=['POST'])
async def webhook():
    data = await request.get_json(force=True)
    update = Update.de_json(data, tg_app.bot)
    await tg_app.process_update(update)
    return "ok"

if __name__ == "__main__":
    print("🔄 Старт сервера...")
    bot = Bot(BOT_TOKEN)
    asyncio.run(bot.set_webhook(f"{WEBHOOK_URL}/webhook"))
    app.run(host="0.0.0.0", port=PORT)
