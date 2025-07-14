import os
import json
import gspread
import time
import logging
from datetime import datetime, timedelta
from telegram.error import Conflict, NetworkError
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    CallbackQueryHandler,
    CallbackContext
)

# ===== KONFIGURASI =====
BOT_TOKEN = "7895835591:AAF8LfMEDGP03YaoLlEhsGqwNVcOdSssny0"

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Google Sheets Config
def initialize_google_sheets():
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
        return client, sheet_members, sheet_films
    except Exception as e:
        logger.error(f"❌ Gagal menginisialisasi Google Sheets: {e}")
        raise

try:
    client, sheet_members, sheet_films = initialize_google_sheets()
except Exception as e:
    logger.error("Bot tidak bisa berjalan tanpa koneksi Google Sheets")
    exit()

# Daftar paket VIP
VIP_PACKAGES = [
    {"label": "⚡ 1 Hari - Rp2.000", "days": 1, "price": 2000, "url": "https://trakteer.id/vip1hari"},
    {"label": "🔥 3 Hari - Rp5.000", "days": 3, "price": 5000, "url": "https://trakteer.id/vip3hari"},
    {"label": "💎 7 Hari - Rp10.000", "days": 7, "price": 10000, "url": "https://trakteer.id/vip7hari"},
    {"label": "🌟 30 Hari - Rp30.000", "days": 30, "price": 30000, "url": "https://trakteer.id/vip30hari"},
    {"label": "👑 5 Bulan (FREE 1 BULAN) - Rp150.000", "days": 150, "price": 150000, "url": "https://trakteer.id/vip5bulan"}
]

# ===== FUNGSI BANTUAN =====
def refresh_connection():
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
        return False

def safe_sheets_operation(func, max_retries=3):
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
    
    try:
        return safe_sheets_operation(operation)
    except Exception as e:
        logger.error(f"Error get_user_row: {e}")
        return None

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
    
    try:
        return safe_sheets_operation(operation)
    except Exception as e:
        logger.error(f"Error add_new_user: {e}")
        return False

def reset_daily_quota_if_needed(row):
    """Reset kuota harian jika sudah lewat hari"""
    def operation():
        last_updated = sheet_members.cell(row, 5).value
        if last_updated:
            last_date = datetime.strptime(last_updated, "%Y-%m-%d %H:%M:%S").date()
            if last_date < datetime.now().date():
                sheet_members.update_cell(row, 6, 5)
                sheet_members.update_cell(row, 5, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    
    try:
        safe_sheets_operation(operation)
    except Exception as e:
        logger.warning(f"Gagal reset quota: {e}")

def get_today_quota(row):
    """Mendapatkan kuota harian user"""
    def operation():
        return int(sheet_members.cell(row, 6).value)
    
    try:
        return safe_sheets_operation(operation)
    except Exception as e:
        logger.error(f"Error get_today_quota: {e}")
        return 0

def reduce_quota(row):
    """Mengurangi kuota user"""
    def operation():
        current = get_today_quota(row)
        if current > 0:
            sheet_members.update_cell(row, 6, current - 1)
    
    try:
        safe_sheets_operation(operation)
    except Exception as e:
        logger.error(f"Error reduce_quota: {e}")

def get_film_link(film_code, is_vip=False):
    """Mendapatkan link film berdasarkan kode"""
    def operation():
        records = sheet_films.get_all_records()
        for record in records:
            if record.get('code') == film_code:
                return record.get('vip_link' if is_vip else 'free_link')
        return None
    
    try:
        return safe_sheets_operation(operation)
    except Exception as e:
        logger.error(f"Error get_film_link: {e}")
        return None

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
    
    try:
        return safe_sheets_operation(operation)
    except Exception as e:
        logger.error(f"Error check_vip_status: {e}")
        return False

# ===== HANDLER COMMAND =====
async def start(update: Update, context: CallbackContext):
    """Handler untuk command /start"""
    try:
        user = update.effective_user
        row = get_user_row(user.id)
        if row is None:
            if not add_new_user(user):
                raise Exception("Gagal mendaftarkan user baru")

        keyboard = [
            [InlineKeyboardButton("🎬 List Film Drama", url="https://t.me/DramaCinaPlus")],
            [InlineKeyboardButton("💎 Langganan VIP", callback_data="vip")],
            [InlineKeyboardButton("📊 Status Akun", callback_data="status")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        welcome_msg = (
            f"🎉 Selamat datang di VIP Drama Cina, {user.username or 'Sobat'}! 🎉\n\n"
            "Nikmati koleksi drama Cina terbaik dengan kualitas HD:\n"
            "✨ 5 tontonan gratis setiap hari\n"
            "💎 Akses tak terbatas untuk member VIP\n\n"
            "Silakan pilih menu di bawah:"
        )
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=welcome_msg,
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Error in start: {e}")
        await send_error_message(update, context)

async def status(update: Update, context: CallbackContext):
    """Handler untuk command /status"""
    try:
        user = update.effective_user
        
        # Daftarkan user jika belum ada
        row = get_user_row(user.id)
        if row is None:
            if not add_new_user(user):
                raise Exception("Gagal mendaftarkan user baru")
            row = get_user_row(user.id)
            if row is None:
                raise Exception("User masih tidak terdaftar setelah pendaftaran")

        # Refresh koneksi Google Sheets jika perlu
        try:
            reset_daily_quota_if_needed(row)
        except Exception as e:
            logger.warning(f"Gagal reset quota: {e}")

        # Ambil data dengan penanganan error
        try:
            vip_status = sheet_members.cell(row, 3).value or "non-vip"
            vip_expiry = sheet_members.cell(row, 4).value or "-"
            quota = sheet_members.cell(row, 6).value or "0"
        except Exception as e:
            logger.error(f"Gagal membaca data: {e}")
            raise Exception("Gagal membaca data pengguna")

        # Format tampilan
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
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        logger.error(f"Error in status: {e}")
        await send_error_message(update, context)

async def send_error_message(update: Update, context: CallbackContext):
    """Mengirim pesan error standar"""
    error_msg = (
        "⚠️ Maaf, terjadi gangguan teknis\n\n"
        "Tim kami sudah menerima laporan ini. "
        "Silakan coba beberapa saat lagi atau hubungi admin jika masalah berlanjut."
    )
    
    try:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=error_msg
        )
    except Exception as e:
        logger.error(f"Gagal mengirim pesan error: {e}")

# [Fungsi lainnya seperti vip, gratis, vip_episode, button_handler tetap sama seperti sebelumnya]

def main():
    """Fungsi utama untuk menjalankan bot"""
    try:
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Register handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("vip", vip))
        application.add_handler(CommandHandler("status", status))
        application.add_handler(CommandHandler("gratis", gratis))
        application.add_handler(CommandHandler("vip_episode", vip_episode))
        application.add_handler(CallbackQueryHandler(button_handler))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        logger.info("🤖 Bot starting...")
        application.run_polling(drop_pending_updates=True)
        
    except Conflict as e:
        logger.error(f"⚠️ Bot conflict: {e}")
        time.sleep(5)
        main()
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        raise

if __name__ == "__main__":
    main()
