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

def generate_docx(payments):
    doc = Document(TEMPLATE_FILE)
    target_table = None
    for table in doc.tables:
        if "7. код класифікації доходів бюджету:" in table.cell(0, 0).text:
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in ALLOWED_USER_IDS:
        await update.message.reply_text("⛔️ У вас немає доступу до цього бота.")
        return
    await update.message.reply_text("👋 Оберіть з чим хочете працювати:", reply_markup=main_keyboard)

async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in ALLOWED_USER_IDS:
        await update.message.reply_text("⛔️ У вас немає доступу до цього бота.")
        return

    text = update.message.text.strip()
    state = user_states.get(chat_id)

    if text == "🏪 Магазини":
        user_states[chat_id] = {"step": 100, "type": "shop"}
        return await update.message.reply_text("🍷 Оберіть тип ліцензії:", reply_markup=type_keyboard)
    if text == "🚬 Кіоски":
        user_states[chat_id] = {"step": 100, "type": "kiosk"}
        return await update.message.reply_text("🍷 Оберіть тип ліцензії:", reply_markup=type_keyboard)

    if state and state.get("step") == 100:
        if text == "🍷 Алкоголь":
            state["license"] = "alcohol"
        elif text == "🚬 Тютюн":
            state["license"] = "tobacco"
        else:
            return await update.message.reply_text("⚠️ Будь ласка, оберіть з клавіатури тип ліцензії.", reply_markup=type_keyboard)
        state["step"] = 1
        state["data"] = {"payments": []}
        return await update.message.reply_text("📥 Введіть код класифікації доходів бюджету:")

    await update.message.reply_text("⚠️ Почніть з /start або оберіть ліцензію.")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = ReplyKeyboardMarkup([
        ["🍷 Алкоголь", "🚬 Тютюн"]
    ], resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text("📂 Статус яких ліцензій вас цікавить?", reply_markup=keyboard)
    user_states[update.effective_chat.id] = {"step": "status_select"}

async def handle_status_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text.strip()
    if text not in ["🍷 Алкоголь", "🚬 Тютюн"]:
        return await update.message.reply_text("⚠️ Оберіть одну з опцій: 🍷 Алкоголь або 🚬 Тютюн")

    license_type = "alcohol" if text == "🍷 Алкоголь" else "tobacco"
    data = load_license_date()
    shops = load_store_group(STORE_SHOPS_FILE)
    kiosks = load_store_group(STORE_KIOSKS_FILE)
    msg = f"📅 Статус ліцензій ({text}):\n"
    today = datetime.now().date()

    for store_id, value in data.items():
        if value.get("license") != license_type:
            continue
        date_str = value["date"]
        store_type = value.get("type", "shop")
        store_group = shops if store_type == "shop" else kiosks
        address = store_group.get(str(store_id), f"ID {store_id}")
        try:
            lic_date = datetime.strptime(date_str, "%d.%m.%Y").date()
            days_left = (lic_date - today).days
            msg += f"🧾 {address}: {date_str} (залишилось {days_left} днів)\n"
        except:
            continue
    await update.message.reply_text(msg)
    user_states.pop(chat_id, None)

# Telegram + Flask init etc. залишаються без змін, лише додати handler
# tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_input))
# -> замінити на ланцюжок умов для status_select:
# ...
# if state.get("step") == "status_select": return await handle_status_selection(update, context)
