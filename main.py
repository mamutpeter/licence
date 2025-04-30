import os
import json
import asyncio
from datetime import datetime, timedelta
from flask import Flask, request
from telegram import Update, Bot, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters
)
from docx import Document
from apscheduler.schedulers.background import BackgroundScheduler

# === Конфігурація ===
BOT_TOKEN = "7685520910:AAH5Yx8uhW0Ry3ozQjsMjNPGlMBUadkfTno"
WEBHOOK_URL = "https://dochelp-ctqw.onrender.com"
PORT = int(os.environ.get("PORT", 10000))

LICENSE_DATE_FILE = "license_date.json"
TEMPLATE_FILE = "заява.docx"
OUTPUT_DOCX = "zayava_ready.docx"
ALLOWED_USER_IDS = [5826122049, 6887361815]

user_states = {}
app = Flask(__name__)
tg_app = Application.builder().token(BOT_TOKEN).build()

keyboard = ReplyKeyboardMarkup(
    [["➕ Додати оплату", "✅ Завершити"]],
    resize_keyboard=True,
    one_time_keyboard=True
)

# === Генерація документу ===
def generate_docx(payments):
    doc = Document(TEMPLATE_FILE)
    target_table = None
    for table in doc.tables:
        if "9.1. код класифікації доходів бюджету:" in table.cell(0, 0).text:
            target_table = table
            break
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

# === Збереження ліцензій ===
def save_license_dates(data):
    with open(LICENSE_DATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

def load_license_dates():
    if not os.path.exists(LICENSE_DATE_FILE):
        return {}
    with open(LICENSE_DATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

# === Обробники команд ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in ALLOWED_USER_IDS:
        await update.message.reply_text("⛔️ У вас немає доступу.")
        return

    user_states[chat_id] = {"step": 1, "data": {"payments": []}}
    await update.message.reply_text("🧾 Почнемо. Введіть код класифікації доходів бюджету:")

async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in ALLOWED_USER_IDS:
        await update.message.reply_text("⛔️ У вас немає доступу.")
        return

    text = update.message.text.strip()
    if chat_id not in user_states:
        return await update.message.reply_text("⚠️ Почніть з /start.")

    state = user_states[chat_id]

    if state["step"] == 6:
        if text == "➕ Додати оплату":
            state["step"] = 1
            return await update.message.reply_text("📥 Введіть код класифікації доходів бюджету:", reply_markup=ReplyKeyboardRemove())
        elif text == "✅ Завершити":
            await update.message.reply_text("📅 Введіть дату завершення ліцензії (ДД.ММ.РРРР):")
            state["step"] = 7
            return
        else:
            return await update.message.reply_text("Оберіть кнопку:", reply_markup=keyboard)

    if state["step"] == 7:
        try:
            datetime.strptime(text, "%d.%m.%Y")
            all_dates = load_license_dates()
            for p in state["data"]["payments"]:
                key = f"{p['code']}_{p['amount']}_{p['instr_number']}"
                all_dates[key] = {
                    "date": text,
                    "chat_id": chat_id
                }
            save_license_dates(all_dates)

            path = generate_docx(state["data"]["payments"])
            if path:
                await update.message.reply_document(open(path, "rb"), reply_markup=ReplyKeyboardRemove())
                await update.message.reply_text("✅ Готово!")
            else:
                await update.message.reply_text("❌ Помилка створення документа.")
        except:
            await update.message.reply_text("❌ Невірна дата.")
        user_states.pop(chat_id)
        return

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
        return await update.message.reply_text("➕ Додати ще чи ✅ Завершити?", reply_markup=keyboard)

# === Нагадування ===
def reminder_check():
    all_data = load_license_dates()
    today = datetime.now().date()
    for key, val in all_data.items():
        try:
            end = datetime.strptime(val["date"], "%d.%m.%Y")
            if (end - timedelta(days=3)).date() == today:
                async def send():
                    await Bot(BOT_TOKEN).send_message(
                        val["chat_id"],
                        f"⏰ Через 3 дні закінчується дія ліцензії ({val['date']}) для оплати {key}"
                    )
                asyncio.run(send())
        except: continue

# === Telegram + Webhook ===
tg_app.add_handler(CommandHandler("start", start))
tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_input))

scheduler = BackgroundScheduler()
scheduler.add_job(reminder_check, "interval", hours=12)
scheduler.start()

@app.route("/webhook", methods=["POST"])
async def webhook():
    data = await request.get_json(force=True)
    update = Update.de_json(data, tg_app.bot)
    await tg_app.process_update(update)
    return "ok"

if __name__ == "__main__":
    async def main():
        await tg_app.initialize()
        await tg_app.start()
        await Bot(BOT_TOKEN).set_webhook(f"{WEBHOOK_URL}/webhook")
        app.run(host="0.0.0.0", port=PORT)
    asyncio.run(main())
