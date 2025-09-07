import os
import json
import gspread
import logging
import time
import base64
import sys
import requests
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi import status as fastapi_status

print("Python version:", sys.version)

import asyncio
from threading import Thread
from flask import Flask, request, jsonify
from werkzeug import __version__ as werkzeug_version
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    CallbackQueryHandler,
    CallbackContext,
    JobQueue
)
from oauth2client.service_account import ServiceAccountCredentials

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI()

session = requests.Session()
retry = requests.adapters.Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[500, 502, 503, 504]
)
adapter = requests.adapters.HTTPAdapter(max_retries=retry)
session.mount('http://', adapter)
session.mount('https://', adapter)

start_time = datetime.now()
# ===== KONFIGURASI =====
BOT_TOKEN = os.getenv('BOT_TOKEN')
BOT_USERNAME = "VIPDramaCinaBot"  # Pastikan sama dengan username bot
CHANNEL_PRIVATE = "-1002683110383"  # Gunakan ID channel numerik
PORT = int(os.getenv('PORT', 8443))
WEBHOOK_URL = os.getenv('WEBHOOK_URL', "https://cdrama-bot.onrender.com")
TRAKTEER_WEBHOOK_SECRET = os.getenv('TRAKTEER_WEBHOOK_SECRET', "trhook-9WUnIQtx4Sz0lsmKtpb6CP0v")
TRAKTEER_PACKAGE_MAPPING = {
    "vip1hari": {"days": 1, "price": 2000},
    "vip3hari": {"days": 3, "price": 5000},
    "vip7hari": {"days": 7, "price": 10000},
    "vip30hari": {"days": 30, "price": 30000},
    "vip5bulan": {"days": 180, "price": 150000}
}

# Inisialisasi Google Sheets
try:
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(
        json.loads(os.getenv('GOOGLE_SERVICE_ACCOUNT')), 
        scope
    )
    client = gspread.authorize(creds)
    spreadsheet = client.open("cdrama_database")
    sheet_members = spreadsheet.worksheet("members")
    sheet_films = spreadsheet.worksheet("film_links")
    logger.info("✅ Berhasil terhubung ke Google Sheets")
except Exception as e:
    logger.error(f"❌ Gagal menginisialisasi Google Sheets: {e}")
    raise

# Daftar paket VIP
VIP_PACKAGES = [
    {"label": "⚡ 1 Hari - Rp2.000", "days": 1, "price": 2000, "url": "https://trakteer.id/vipdramacina/tip?quantity=2&step=2&display_name=Nama+Kamu&supporter_message=Saya+beli+VIP+1+hari"},
    {"label": "🔥 3 Hari - Rp5.000", "days": 3, "price": 5000, "url": "https://trakteer.id/vipdramacina/tip?quantity=5&step=2&display_name=Nama+Kamu&supporter_message=Saya+beli+VIP+3+hari"},
    {"label": "💎 7 Hari - Rp10.000", "days": 7, "price": 10000, "url": "https://trakteer.id/vipdramacina/tip?quantity=10&step=2&display_name=Nama+Kamu&supporter_message=Saya+beli+VIP+7+hari"},
    {"label": "🌟 30 Hari - Rp30.000", "days": 30, "price": 30000, "url": "https://trakteer.id/vipdramacina/tip?quantity=30&step=2&display_name=Nama+Kamu&supporter_message=Saya+beli+VIP+1+bulan"},
    {"label": "👑 5 Bulan (FREE 1 BULAN) - Rp150.000", "days": 180, "price": 150000, "url": "https://trakteer.id/vipdramacina/tip?quantity=150&step=2&display_name=Nama+Kamu&supporter_message=Saya+beli+VIP+6+bulan"}
]

# ===== FUNGSI BANTUAN =====
def refresh_connection():
    """Refresh koneksi Google Sheets dengan timeout"""
    try:
        global client, sheet_members, sheet_films
        client = gspread.authorize(creds)
        spreadsheet = client.open("cdrama_database")
        sheet_members = spreadsheet.worksheet("members")
        sheet_films = spreadsheet.worksheet("film_links")
        logger.info("Koneksi Google Sheets diperbarui")
        return True
    except Exception as e:
        logger.error(f"Gagal refresh koneksi: {e}")
        time.sleep(5)  # Tunggu sebelum retry
        return False

def safe_sheets_operation(func, max_retries=3):
    """Eksekusi operasi Google Sheets dengan retry"""
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            logger.warning(f"Percobaan {attempt+1} gagal: {e}")
            if attempt == max_retries - 1:
                raise
            time.sleep(2)
            refresh_connection()

def get_user_row(user_id):
    """Mendapatkan baris user di spreadsheet"""
    def operation():
        records = sheet_members.get_all_records()
        for idx, record in enumerate(records, start=2):
            if str(record.get('telegram_id', '')) == str(user_id):
                return idx
        return None
    return safe_sheets_operation(operation)

def add_new_user(user):
    """Menambahkan user baru ke spreadsheet"""
    def operation():
        sheet_members.append_row([
            str(user.id),
            user.username or "",
            "non-vip",
            "",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            5  # Kuota awal
        ])
        return True
    return safe_sheets_operation(operation)

def reset_daily_quota_if_needed(row):
    """Reset kuota harian jika sudah lewat hari"""
    def operation():
        last_updated = sheet_members.cell(row, 5).value
        if last_updated:
            last_date = datetime.strptime(last_updated, "%Y-%m-%d %H:%M:%S").date()
            if last_date < datetime.now().date():
                sheet_members.update_cell(row, 6, 5)
                sheet_members.update_cell(row, 5, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    safe_sheets_operation(operation)

def get_today_quota(row):
    """Mendapatkan kuota harian user"""
    def operation():
        return int(sheet_members.cell(row, 6).value)
    return safe_sheets_operation(operation)

def reduce_quota(row):
    """Mengurangi kuota user"""
    def operation():
        current = get_today_quota(row)
        if current > 0:
            sheet_members.update_cell(row, 6, current - 1)
    safe_sheets_operation(operation)

def get_film_link(film_code, is_vip=False):
    """Mendapatkan link film berdasarkan kode"""
    def operation():
        records = sheet_films.get_all_records()
        for record in records:
            if record.get('code') == film_code:
                return record.get('vip_link' if is_vip else 'free_link')
        return None
    return safe_sheets_operation(operation)

def check_vip_status(user_id):
    """Memeriksa status VIP user"""
    def operation():
        row = get_user_row(user_id)
        if not row:
            return False
            
        vip_status = sheet_members.cell(row, 3).value
        vip_expiry = sheet_members.cell(row, 4).value
        
        if vip_status == "vip" and vip_expiry:
            expiry_date = datetime.strptime(vip_expiry, "%Y-%m-%d")
            return expiry_date >= datetime.now()
        return False
    return safe_sheets_operation(operation)

def update_vip_status(user_id, package_id):
    """Update status VIP user di Google Sheets"""
    def operation():
        try:
            # Dapatkan package info
            package = TRAKTEER_PACKAGE_MAPPING.get(package_id)
            if not package:
                logger.error(f"Package {package_id} not found!")
                return False

            # Cari user
            records = sheet_members.get_all_records()
            for idx, record in enumerate(records, start=2):
                if str(record.get('telegram_id', '')) == str(user_id):
                    # Hitung expiry date
                    expiry_date = (datetime.now() + timedelta(days=package['days'])).strftime("%Y-%m-%d")
                    
                    # Update sheet
                    sheet_members.update_cell(idx, 3, "vip")  # Kolom status
                    sheet_members.update_cell(idx, 4, expiry_date)  # Kolom expiry
                    
                    logger.info(f"Updated user {user_id} to VIP until {expiry_date}")
                    return True

            logger.error(f"User {user_id} not found in sheet")
            return False

        except Exception as e:
            logger.error(f"Sheet update error: {str(e)}")
            return False

    return safe_sheets_operation(operation)

# ===== HANDLER COMMAND =====
async def start(update: Update, context: CallbackContext):
    """Handler untuk command /start"""
    try:
        user = update.effective_user
        row = get_user_row(user.id)
        if row is None:
            if not add_new_user(user):
                raise Exception("Gagal mendaftarkan user baru")

        if context.args:
            try:
                encoded_str = context.args[0]
                film_code, part = decode_film_code(encoded_str)
                film_data = get_film_info(film_code)
                
                if not film_data:
                    await update.message.reply_text("❌ Film tidak ditemukan")
                    return

                if part == "P1":
                    try:
                        await context.bot.copy_message(
                            chat_id=update.effective_chat.id,
                            from_chat_id=int(CHANNEL_PRIVATE),
                            message_id=int(film_data['free_msg_id'])
                        )
                        
                        keyboard = [
                            [InlineKeyboardButton(
                                "⏩ Lanjut Part 2" + (" (VIP)" if film_data['is_part2_vip'] else ""), 
                                url=f"https://t.me/{BOT_USERNAME}?start={encode_film_code(film_code, 'P2')}"
                            )]
                        ]
                        await update.message.reply_text(
                            "Akhir dari Part 1...",
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
                        return
                    except Exception as e:
                        logger.error(f"Error mengirim P1: {e}")
                        await update.message.reply_text(
                            "❌ Gagal memuat video Part 1\n"
                            f"Pastikan:\n"
                            f"1. Bot sudah admin di channel\n"
                            f"2. Message ID benar\n"
                            f"Error: {str(e)}"
                        )
                        return

                elif part == "P2":
                    if check_vip_status(user.id) or not film_data['is_part2_vip']:
                        try:
                            await context.bot.copy_message(
                                chat_id=update.effective_chat.id,
                                from_chat_id=int(CHANNEL_PRIVATE),
                                message_id=int(film_data['vip_msg_id'])
                            )
                            return
                        except Exception as e:
                            logger.error(f"Error mengirim P2: {e}")
                            await update.message.reply_text("❌ Gagal memuat video Part 2")
                            return
                    else:
                        await update.message.reply_text(
                            "🔒 Part 2 khusus member VIP!\n\n"
                            "Upgrade ke VIP untuk menonton kelanjutannya:",
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("💎 Upgrade VIP", callback_data="vip")]
                            ])
                        )
                        return
            except Exception as e:
                logger.error(f"Error memproses link film: {e}")
                await update.message.reply_text("❌ Terjadi kesalahan saat memproses link film")

        keyboard = [
            [InlineKeyboardButton("🎬 List Film Drama", url="https://t.me/DramaCinaPlus")],
            [InlineKeyboardButton("💎 Langganan VIP", callback_data="vip")],
            [InlineKeyboardButton("📊 Status Akun", callback_data="status")]
        ]
        
        await update.message.reply_text(
            f"🎉 Selamat datang di VIP Drama Cina, {user.username or 'Sobat'}! 🎉\n\n"
            "Nikmati koleksi drama Cina terbaik dengan kualitas HD:\n"
            "✨ 5 tontonan gratis setiap hari\n"
            "💎 Akses tak terbatas untuk member VIP\n\n"
            "Silakan pilih menu di bawah:",
            reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.error(f"Error di start: {e}")
        await send_error_message(update, context)

async def vip(update: Update, context: CallbackContext):
    try:
        user_id = update.effective_user.id
        keyboard = []
        for package in VIP_PACKAGES:
            package_url = f"{package['url']}?utm_source={user_id}"
            keyboard.append([InlineKeyboardButton(
                package["label"], 
                url=package_url
            )])
        keyboard.append([InlineKeyboardButton("🔙 Kembali ke Menu", callback_data="menu")])
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="💎 **PAKET LANGGANAN VIP** 💎\n\n"
                 "Cara jadi member VIP:\n"
                 f"1. Copy email ini : `{user_id}@vipbot.com`\n\n"
                 "2. Pilih paket VIP di bawah\n"
                 "3. Paste email pada kolom email\n"
                 "4. Pilih metode pembayaran yang anda mau\n"
                 "Status VIP akan aktif otomatis dalam 1 menit setelah pembayaran.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error di vip: {e}")
        await send_error_message(update, context)

async def status(update: Update, context: CallbackContext):
    try:
        user = update.effective_user
        row = get_user_row(user.id)
        if row is None:
            if not add_new_user(user):
                raise Exception("Gagal mendaftarkan user baru")
            row = get_user_row(user.id)

        reset_daily_quota_if_needed(row)

        vip_status = sheet_members.cell(row, 3).value or "non-vip"
        vip_expiry = sheet_members.cell(row, 4).value or "-"
        quota = sheet_members.cell(row, 6).value or "0"

        is_vip = vip_status.lower() == "vip" and (
            vip_expiry == "-" or 
            datetime.strptime(vip_expiry, "%Y-%m-%d") >= datetime.now()
        )

        if vip_expiry != "-":
            try:
                expiry_date = datetime.strptime(vip_expiry, "%Y-%m-%d")
                formatted_expiry = expiry_date.strftime("%d-%m-%Y")
            except:
                formatted_expiry = vip_expiry
        else:
            formatted_expiry = "-"

        status_msg = (
            f"📌 Status akun @{user.username or user.id}\n\n"
            f"🆔 ID Telegram: {user.id}\n"
            f"💎 Status: {'VIP Member' if is_vip else 'Free Member'}\n"
            f"🎬 Sisa kuota Hari Ini: {quota}/5\n"
            f"📅 Masa Aktif Hingga: {formatted_expiry}\n\n"
            "Terima kasih telah menggunakan VIP Drama Cina"
        )

        keyboard = [
            [InlineKeyboardButton("💎 Upgrade VIP", callback_data="vip")],
            [InlineKeyboardButton("🏠 Menu Utama", callback_data="menu")]
        ]
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=status_msg,
            reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.error(f"Error di status: {e}")
        await send_error_message(update, context)

async def gratis(update: Update, context: CallbackContext):
    try:
        user = update.effective_user
        row = get_user_row(user.id)
        if row is None:
            if not add_new_user(user):
                raise Exception("Gagal mendaftarkan user baru")
            row = get_user_row(user.id)

        reset_daily_quota_if_needed(row)

        if get_today_quota(row) <= 0:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="😢 Kuota gratis hari ini sudah habis!\n\n"
                     "Anda bisa menonton lagi besok atau upgrade ke VIP untuk akses tak terbatas.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💎 Upgrade VIP", callback_data="vip")]
                ])
            )
            return

        if not context.args:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="ℹ️ Cara pakai: /gratis <kode_film>"
            )
            return

        film_link = get_film_link(context.args[0])
        if film_link:
            reduce_quota(row)
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"🎬 Berikut tontonan gratis Anda:\n{film_link}\n\n"
                     f"Sisa kuota hari ini: {get_today_quota(row)}/5"
            )
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Kode film tidak ditemukan"
            )
    except Exception as e:
        logger.error(f"Error di gratis: {e}")
        await send_error_message(update, context)

async def vip_episode(update: Update, context: CallbackContext):
    try:
        user = update.effective_user
        if not context.args:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="ℹ️ Cara pakai: /vip_episode <kode_film>"
            )
            return

        film_link = get_film_link(context.args[0], is_vip=True)
        if not film_link:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Kode film tidak ditemukan"
            )
            return

        if check_vip_status(user.id):
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"💎 VIP Access:\n{film_link}"
            )
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="🔒 Akses terbatas untuk member VIP!\n\n"
                     "Yuk upgrade ke VIP untuk nonton sepuasnya. Cuma Rp2.000 untuk 1 hari!",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💎 Upgrade Sekarang", callback_data="vip")],
                    [InlineKeyboardButton("🎬 Coba Versi Gratis", callback_data=f"free_{context.args[0]}")]
                ])
            )
    except Exception as e:
        logger.error(f"Error di vip_episode: {e}")
        await send_error_message(update, context)

async def button_handler(update: Update, context: CallbackContext):
    try:
        query = update.callback_query
        await query.answer()
        
        if query.data == "menu":
            await start(update, context)
        elif query.data == "vip":
            await vip(update, context)
        elif query.data == "status":
            await status(update, context)
        elif query.data.startswith("free_"):
            context.args = [query.data.split("_")[1]]
            await gratis(update, context)
    except Exception as e:
        logger.error(f"Error di button_handler: {e}")
        await send_error_message(update, context)

async def handle_message(update: Update, context: CallbackContext):
    try:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="ℹ️ Gunakan command yang tersedia. Ketik /start untuk melihat menu."
        )
    except Exception as e:
        logger.error(f"Error di handle_message: {e}")

async def send_error_message(update: Update, context: CallbackContext):
    try:
        error_msg = (
            "⚠️ Maaf, terjadi gangguan teknis\n\n"
            "Tim kami sudah menerima laporan ini. "
            "Silakan coba beberapa saat lagi atau hubungi admin jika masalah berlanjut."
        )
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=error_msg
        )
    except Exception as e:
        logger.error(f"Gagal mengirim pesan error: {e}")

async def generate_film_links(update: Update, context: CallbackContext):
    """Generate film links (NEW)"""
    if str(update.effective_user.id) != "YOUR_ADMIN_ID":  # Ganti dengan ID Telegram admin
        return

    if not context.args:
        await update.message.reply_text("Usage: /generate_link <film_code>")
        return

    film_code = context.args[0]
    film_data = get_film_info(film_code)
    
    if not film_data:
        await update.message.reply_text("❌ Film not found")
        return

    part1_link = f"https://t.me/{BOT_USERNAME}?start={encode_film_code(film_code, 'P1')}"
    part2_link = f"https://t.me/{BOT_USERNAME}?start={encode_film_code(film_code, 'P2')}"

    await update.message.reply_text(
        f"🔗 Links for {film_data['title']}:\n\n"
        f"▫️ Part 1 (Free): {part1_link}\n"
        f"▫️ Part 2 ({'VIP Only' if film_data['is_part2_vip'] else 'Free'}): {part2_link}\n\n"
        "Post template for Channel 1:\n\n"
        f"🎬 {film_data['title']}\n\n"
        f"▫️ [Part 1 (Free)]({part1_link})\n"
        f"▫️ [Part 2 ({'VIP' if film_data['is_part2_vip'] else 'Free'})]({part2_link})"
    )

def get_film_info(film_code):
    """Mendapatkan data film lengkap termasuk ID pesan"""
    def operation():
        records = sheet_films.get_all_records()
        for record in records:
            if record['code'] == film_code:
                return {
                    'title': record['title'],
                    'free_msg_id': record['free_msg_id'],
                    'vip_msg_id': record['vip_msg_id'],
                    'is_part2_vip': record.get('is_part2_vip', 'TRUE') == 'TRUE'
                }
        return None
    return safe_sheets_operation(operation)

def encode_film_code(film_code, part):
    """Encode kode film untuk URL"""
    return base64.urlsafe_b64encode(f"{film_code}_{part}".encode()).decode()

def decode_film_code(encoded_str):
    """Decode kode film dari URL"""
    return base64.urlsafe_b64decode(encoded_str.encode()).decode().split("_")

async def keep_alive(context: CallbackContext):
    """Refresh koneksi secara berkala"""
    try:
        refresh_connection()
        logger.info("✅ Koneksi diperbarui")
    except Exception as e:
        logger.error(f"Gagal refresh koneksi: {e}")
    
async def ping_server(context: CallbackContext):
    try:
        # Gunakan session dengan timeout pendek
        response = requests.get(f"{WEBHOOK_URL}/healthz", timeout=3)
        logger.info(f"🏓 Ping successful - Status: {response.status_code}")
    except Exception as e:
        logger.warning(f"Ping failed: {str(e)}")
        # Tidak perlu refresh webhook otomatis

async def bot_health_check(update: Update, context: CallbackContext):
    """Handler for /health command"""
    try:
        await update.message.reply_text(
            "✅ Bot is running!\n"
            f"Python version: {sys.version.split()[0]}\n"
            f"Uptime: {datetime.now() - start_time}"
        )
    except Exception as e:
        logger.error(f"Health check error: {e}")
        await update.message.reply_text("⚠️ Bot is running but with some issues")
        
# ===== TELEGRAM BOT SETUP =====
def initialize_bot():
    """Initialize the Telegram bot application"""
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Initialize JobQueue
    job_queue = application.job_queue
    if job_queue is None:
        job_queue = JobQueue()
        application.job_queue = job_queue

    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("health", bot_health_check))
    application.add_handler(CommandHandler("vip", vip))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("gratis", gratis))
    application.add_handler(CommandHandler("vip_episode", vip_episode))
    application.add_handler(CommandHandler("generate_link", generate_film_links))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    return application  # This should be INSIDE the function

# Initialize the bot application
application = initialize_bot()

# ===== WEBHOOK ENDPOINTS =====
@app.post(f'/{BOT_TOKEN}')
async def telegram_webhook(request: Request):
    """Endpoint to receive updates from Telegram"""
    try:
        # Initialize the bot if not already initialized
        if not application.running:
            await application.initialize()
            await application.start()
        
        json_data = await request.json()
        update = Update.de_json(json_data, application.bot)
        await application.process_update(update)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error processing update: {e}")
        raise HTTPException(
            status_code=fastapi_status.HTTP_400_BAD_REQUEST,
            detail={"status": "error", "message": str(e)}
        )

@app.get("/healthz")
async def health_check():
    """Health check endpoint for Render"""
    return {"status": "ok", "uptime": str(datetime.now() - start_time)}

def setup_webhook():
    """Setup Telegram webhook (synchronous)"""
    try:
        webhook_url = f"{WEBHOOK_URL}/{BOT_TOKEN}"
        logger.info(f"🔧 Setting webhook to: {webhook_url}")

        # 1. Delete old webhook
        session.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook",
            timeout=5
        )

        # 2. Set new webhook
        response = session.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
            json={
                'url': webhook_url,
                'drop_pending_updates': True,
                'secret_token': os.getenv('WEBHOOK_SECRET', 'WEBHOOK_SECRET_TOKEN'),
                'allowed_updates': ['message', 'callback_query'],
                'max_connections': 40
            },
            timeout=10
        )
        
        result = response.json()
        logger.info(f"Webhook setup result: {result}")

        # 3. Verify
        verify = session.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo"
        ).json()
        logger.info(f"ℹ️ Current webhook info: {verify}")

        return True
    except Exception as e:
        logger.error(f"🔥 Failed to set webhook: {str(e)}")
        return False

# ===== TRAKTEER WEBHOOK HANDLER =====
@app.post("/trakteer_webhook")
async def trakteer_webhook(request: Request):
    try:
        # Verifikasi secret token
        incoming_secret = request.headers.get("X-Webhook-Token")
        if incoming_secret != os.getenv("TRAKTEER_WEBHOOK_SECRET"):
            logger.error("Invalid webhook secret")
            raise HTTPException(status_code=403)

        data = await request.json()
        logger.info(f"Raw webhook data: {json.dumps(data, indent=2)}")  # Log lengkap

        # Cari user_id dari supporter_message (fallback jika email tidak ada)
        supporter_message = data.get("supporter_message", "")
        user_id = None
        
        # Method 1: Cari dari "?utm_source=USER_ID" di supporter_message
        if "utm_source=" in supporter_message:
            user_id = supporter_message.split("utm_source=")[1].split("&")[0].split("?")[0]
        
        # Method 2: Cari pola email di supporter_message
        if not user_id and "@vipbot.com" in supporter_message:
            user_id = supporter_message.split("@vipbot.com")[0][-10:]  # Ambil 10 digit terakhir

        if not user_id or not user_id.isdigit():
            logger.error(f"Failed to extract user_id from: {supporter_message}")
            return JSONResponse({"status": "error", "message": "User ID not found"})

        # Proses package
        package_id = "vip1hari"  # Default, sesuaikan dengan quantity jika perlu
        quantity = int(data.get("quantity", 0))
        
        if quantity == 2:
            package_id = "vip1hari"
        elif quantity == 5:
            package_id = "vip3hari"
        elif quantity == 10:
            package_id = "vip7hari"
        elif quantity == 30:
            package_id = "vip30hari"
        elif quantity == 150:
            package_id = "vip6bulan"
        # ... tambahkan mapping lainnya sesuai kebutuhan

        # Update status VIP
        success = update_vip_status(user_id, package_id)
        if success:
            logger.info(f"Successfully updated VIP status for user {user_id}")
            return JSONResponse({"status": "success"})
        else:
            logger.error(f"Failed to update VIP status for user {user_id}")
            return JSONResponse({"status": "error", "message": "Google Sheets update failed"})

    except Exception as e:
        logger.error(f"Webhook processing failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500)

async def process_vip_payment(user_id: str, package_id: str):
    """Background task untuk update VIP status"""
    try:
        success = update_vip_status(user_id, package_id)
        if success:
            logger.info(f"VIP status updated for user {user_id}")
        else:
            logger.error(f"Failed to update VIP status for user {user_id}")
    except Exception as e:
        logger.error(f"Background task error: {str(e)}")

# ===== MAIN EXECUTION =====
if __name__ == "__main__":
    import uvicorn
    
    # Setup webhook
    if not setup_webhook():
        logger.error("Failed to setup webhook, exiting...")
        exit(1)
    
    # Run the server
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8443)),
        log_level="info"
    )
