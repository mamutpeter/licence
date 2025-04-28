import os
import json
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from docx import Document
from apscheduler.schedulers.background import BackgroundScheduler
import asyncio
from http.server import SimpleHTTPRequestHandler, HTTPServer
import threading

# 🛜 Стартуємо dummy HTTP сервер на порт 8080 (або той, що Render задасть)
def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("", port), SimpleHTTPRequestHandler)
    print(f"🛜 Dummy HTTP Server running on port {port}")
    server.serve_forever()

threading.Thread(target=run_dummy_server, daemon=True).start()

BOT_TOKEN = "7685520910:AAH5Yx8uhW0Ry3ozQjsMjNPGlMBUadkfTno"
ALLOWED_USER_IDS = [5826122049, 6887361815, 581331192]
TEMPLATE_FILE = "template_zayava.docx"
OUTPUT_DOCX = "zayava_ready.docx"
LICENSE_DATE_FILE = "license_date.json"

user_states = {}
store_context = {}

keyboard = ReplyKeyboardMarkup(
    [["➕ Додати оплату", "✅ Завершити"]],
    resize_keyboard=True,
    one_time_keyboard=True
)

start_keyboard = ReplyKeyboardMarkup(
    [["📘 Як користуватись", "📄 Завантажити список магазинів"]],
    resize_keyboard=True,
    one_time_keyboard=True
)

instruction_text = """
📘 Інструкція користування ботом:

👋 Вітаю у сервісі створення заяв для продовження ліцензії!

1. Натисніть кнопку '📘 Як користуватись' або введіть команду: /start <ID магазину> (наприклад: /start 1)

2. Після старту бот попросить:
   – Код класифікації доходів бюджету
   – Суму оплати
   – Номер інструкції (платіжки)
   – Дату інструкції

3. Після введення даних:
   – Натисніть ➕ Додати оплату (якщо потрібно додати ще один платіж)
   – Або ✅ Завершити, щоб перейти до завершення

4. Після завершення:
   – Введіть дату закінчення ліцензії у форматі ДД.ММ.РРРР (наприклад: 01.06.2025)

5. Бот:
   – Згенерує заяву у форматі .docx
   – Надішле її вам у чат
   – Збереже дату закінчення ліцензії

6. За 3 дні до закінчення ліцензії бот автоматично надішле нагадування.

⚡ Якщо натиснути '📄 Завантажити список магазинів' — бот відправить актуальний список магазинів у PDF.

📅 Дати обов'язково вводьте у форматі ДД.ММ.РРРР.

Бажаємо успішної роботи! 🚀

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
    with open(LICENSE_DATE_FILE, "w") as f:
        json.dump({"license_end": date_str, "chat_id": chat_id}, f)

def load_license_date():
    if not os.path.exists(LICENSE_DATE_FILE):
        return None
    with open(LICENSE_DATE_FILE, "r") as f:
        return json.load(f)

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = ctx.args

    if not args:
        await update.message.reply_text(
            """👋 Вітаю! Щоб розпочати роботу введи :
            /start <ID_магазину>

Наприклад: /start 1""",
            reply_markup=start_keyboard
        )
        return

    store_id = args[0]
    store_context[chat_id] = store_id
    user_states[chat_id] = {"step": 1, "data": {"payments": []}}
    await update.message.reply_text(f"🧾 Магазин {store_id} активовано. Введіть код класифікації доходів бюджету:")

async def handle_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    if text == "📘 Як користуватись":
        return await update.message.reply_text(instruction_text)
    elif text == "📄 Завантажити список магазинів":
        return await update.message.reply_document(document=open("список_магазинів.pdf", "rb"))

    if chat_id not in user_states:
        return await update.message.reply_text("⚠️ Почніть з /start.")

    state = user_states[chat_id]

    if state["step"] == 6:
        if text == "➕ Додати оплату":
            state["step"] = 1
            return await update.message.reply_text("📥 Введіть код класифікації доходів бюджету:", reply_markup=ReplyKeyboardRemove())
        elif text == "✅ Завершити":
            await update.message.reply_text("📅 Введіть дату завершення ліцензії у форматі ДД.ММ.РРРР:")
            state["step"] = 7
            return
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
            await update.message.reply_text("❌ Невірний формат дати. Спробуйте ще раз у форматі ДД.ММ.РРРР")
            return
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
        return await update.message.reply_text("➕ Додати ще одну оплату чи ✅ Завершити?", reply_markup=keyboard)

def reminder_check():
    data = load_license_date()
    if not data:
        return
    try:
        license_end = datetime.strptime(data["license_end"], "%d.%m.%Y")
        notify_date = license_end - timedelta(days=3)
        today = datetime.now().date()
        if today == notify_date.date():
            from telegram import Bot
            async def send_notification():
                bot = Bot(BOT_TOKEN)
                await bot.send_message(
                    chat_id=data["chat_id"],
                    text=f"⏰ Через 3 дні завершується дія ліцензії ({data['license_end']})! Виконай /start"
                )
            asyncio.run(send_notification())
    except Exception as e:
        print("❌ Нагадування: помилка:", e)

if __name__ == "__main__":
    print("🔄 Ініціалізація Telegram-бота...")
    try:
        app = ApplicationBuilder().token(BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_input))

        scheduler = BackgroundScheduler()
        scheduler.add_job(reminder_check, "interval", hours=12)
        scheduler.start()

        print("✅ Бот запущено. Очікую команди...")
        app.run_polling()
    except Exception as e:
        print(f"❌ Помилка запуску бота: {e}")
