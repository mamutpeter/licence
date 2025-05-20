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

# --- решта коду не змінено ---
