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
TEMPLATE_FILE = "template_zayava.docx"
OUTPUT_DOCX = "zayava_ready.docx"
ALLOWED_USER_IDS = [5826122049, 6887361815]

user_states = {}

keyboard = ReplyKeyboardMarkup([["➕ Додати оплату", "✅ Завершити"]],
                               resize_keyboard=True, one_time_keyboard=True)

instruction_text = """
📘 Інструкція користування ботом:

1. Введи /start
2. Введи по черзі:
   – Код класифікації доходу
   – Суму
   – Номер інструкції
   – Дату інструкції
3. Натисни '✅ Завершити'
4. Введи дату завершення ліцензії
5. Бот згенерує заяву і нагадає за 3 дні
"""

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

def save_license_date(date_str, chat_id):
    if os.path.exists(LICENSE_DATE_FILE):
        with open(LICENSE_DATE_FILE, "r") as f:
            data = json.load(f)
    else:
        data = {}
    data[str(chat_id)] = date_str
    with open(LICENSE_DATE_FILE, "w") as f:
        json.dump(data, f)

def load_license_date():
    if not os.path.exists(LICENSE_DATE_FILE):
        return {}
    with open(LICENSE_DATE_FILE, "r") as f:
        return json.load(f)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in ALLOWED_USER_IDS:
        await update.message.reply_text("⛔️ У вас немає доступу до цього бота.")
        return
    user_states[chat_id] = {"step": 1, "data": {"payments": []}}
    await update.message.reply_text("📥 Введіть код класифікації доходів бюджету:")

async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in ALLOWED_USER_IDS:
        await update.message.reply_text("⛔️ У вас немає доступу до цього бота.")
        return

    text = update.message.text.strip()
    state = user_states.get(chat_id)

    if not state:
        return await update.message.reply_text("⚠️ Почніть з /start.")

    if state["step"] == 6:
        if text == "➕ Додати оплату":
            state["step"] = 1
            return await update.message.reply_text("📥 Введіть код класифікації доходів бюджету:", reply_markup=ReplyKeyboardRemove())
        elif text == "✅ Завершити":
            state["step"] = 7
            return await update.message.reply_text("📅 Введіть дату завершення ліцензії у форматі ДД.ММ.РРРР:")
        else:
            return await update.message.reply_text("Оберіть кнопку:", reply_markup=keyboard)

    if state["step"] == 7:
        try:
            datetime.strptime(text, "%d.%m.%Y")
            save_license_date(text, chat_id)
            path = generate_docx(state["data"]["payments"])
            if path:
                await update.message.reply_document(open(path, "rb"), reply_markup=ReplyKeyboardRemove())
                await update.message.reply_text("✅ Заяву сформовано та збережено дату ліцензії!")
            else:
                await update.message.reply_text("❌ Помилка генерації документа.")
        except ValueError:
            await update.message.reply_text("❌ Невірний формат дати. Спробуйте ще раз.")
        user_states.pop(chat_id, None)
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
        return await update.message.reply_text("➕ Додати ще одну оплату чи ✅ Завершити?", reply_markup=keyboard)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_license_date()
    if not data:
        await update.message.reply_text("Немає жодної ліцензії.")
        return
    today = datetime.now().date()
    msg = "📅 Статус ліцензій:\n"

    for chat_id, date_str in data.items():
        try:
            lic_date = datetime.strptime(date_str, "%d.%m.%Y").date()
            days_left = (lic_date - today).days
            msg += f"🧾 Магазин {chat_id}: {date_str} (залишилось {days_left} днів)\n"
        except:
            continue
    await update.message.reply_text(msg)

def reminder_check():
    data = load_license_date()
    today = datetime.now().date()
    for chat_id, date_str in data.items():
        try:
            lic_date = datetime.strptime(date_str, "%d.%m.%Y").date()
            if (lic_date - today).days == 3:
                async def notify(chat_id=chat_id, date_str=date_str):
                    bot = Bot(BOT_TOKEN)
                    await bot.send_message(
                        chat_id=int(chat_id),
                        text=f"⏰ Через 3 дні завершується дія ліцензії ({date_str})! Виконай /start"
                    )
                threading.Thread(target=asyncio.run, args=(notify(),)).start()
        except:
            continue

# === Telegram + Flask ===
app = Flask(__name__)
tg_app = Application.builder().token(BOT_TOKEN).build()

# ✅ Необхідна ініціалізація для Webhook-сценарію
asyncio.run(tg_app.initialize())

tg_app.add_handler(CommandHandler("start", start))
tg_app.add_handler(CommandHandler("status", status))
tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_input))

scheduler = BackgroundScheduler()
scheduler.add_job(reminder_check, "interval", hours=12)
scheduler.start()

def process_async_update(update):
    asyncio.run(tg_app.process_update(update))

@app.route('/webhook', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(force=True), tg_app.bot)
    threading.Thread(target=process_async_update, args=(update,)).start()
    return "ok"

if __name__ == "__main__":
    print("🔄 Старт сервера...")
    bot = Bot(BOT_TOKEN)
    asyncio.run(bot.set_webhook(f"{WEBHOOK_URL}/webhook"))
    app.run(host="0.0.0.0", port=PORT)
