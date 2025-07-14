import os
import json
import gspread
import time
import logging
from datetime import datetime, timedelta
from telegram.error import Conflict
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

# Google Sheets Config
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
except Exception as e:
    print(f"❌ Gagal menginisialisasi Google Sheets: {e}")
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
def get_user_row(user_id):
    """Mendapatkan baris user di spreadsheet berdasarkan ID Telegram"""
    try:
        records = sheet_members.get_all_records()
        for idx, record in enumerate(records, start=2):
            if record.get('telegram_id') == str(user_id):
                return idx
        return None
    except Exception as e:
        logging.error(f"Error getting user row: {e}")
        return None

def add_new_user(user):
    """Menambahkan user baru ke spreadsheet"""
    try:
        sheet_members.append_row([
            str(user.id),
            user.username or "",
            "non-vip",
            "",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            5  # Kuota awal
        ])
        logging.info(f"User added: {user.id}")
    except Exception as e:
        logging.error(f"Error adding new user: {e}")

def reset_daily_quota_if_needed(row):
    """Reset kuota harian jika sudah lewat hari"""
    try:
        last_updated = sheet_members.cell(row, 5).value
        if last_updated:
            last_date = datetime.strptime(last_updated, "%Y-%m-%d %H:%M:%S").date()
            if last_date < datetime.now().date():
                sheet_members.update_cell(row, 6, 5)  # Reset kuota
                sheet_members.update_cell(row, 5, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                logging.info(f"Reset quota for row {row}")
    except Exception as e:
        logging.error(f"Error resetting quota: {e}")

def get_today_quota(row):
    """Mendapatkan kuota harian user"""
    try:
        return int(sheet_members.cell(row, 6).value)
    except Exception as e:
        logging.error(f"Error getting quota: {e}")
        return 0

def reduce_quota(row):
    """Mengurangi kuota user"""
    try:
        current = get_today_quota(row)
        if current > 0:
            sheet_members.update_cell(row, 6, current - 1)
            logging.info(f"Reduced quota for row {row}")
    except Exception as e:
        logging.error(f"Error reducing quota: {e}")

def get_film_link(film_code, is_vip=False):
    """Mendapatkan link film berdasarkan kode"""
    try:
        records = sheet_films.get_all_records()
        for record in records:
            if record.get('code') == film_code:
                return record.get('vip_link' if is_vip else 'free_link')
        return None
    except Exception as e:
        logging.error(f"Error getting film link: {e}")
        return None

def check_vip_status(user_id):
    """Memeriksa status VIP user"""
    try:
        row = get_user_row(user_id)
        if not row:
            return False
            
        vip_status = sheet_members.cell(row, 3).value
        vip_expiry = sheet_members.cell(row, 4).value
        
        if vip_status == "vip" and vip_expiry:
            expiry_date = datetime.strptime(vip_expiry, "%Y-%m-%d")
            return expiry_date >= datetime.now()
        return False
    except Exception as e:
        logging.error(f"Error checking VIP status: {e}")
        return False

# ===== HANDLER COMMAND =====
async def start(update: Update, context: CallbackContext):
    """Handler untuk command /start"""
    user = update.effective_user
    row = get_user_row(user.id)
    if row is None:
        add_new_user(user)

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

async def vip(update: Update, context: CallbackContext):
    """Handler untuk command /vip"""
    keyboard = []
    for package in VIP_PACKAGES:
        keyboard.append([InlineKeyboardButton(package["label"], url=package["url"])])
    keyboard.append([InlineKeyboardButton("🔙 Kembali ke Menu", callback_data="menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    vip_msg = (
        "💎 **PAKET LANGGANAN VIP** 💎\n\n"
        "Dapatkan akses unlimited ke semua drama:\n"
        "✅ Nonton sepuasnya tanpa batas\n"
        "✅ Kualitas HD terbaik\n"
        "✅ Update episode terbaru setiap harinya\n\n"
        "⬇️ Pilih paket favoritmu:"
    )
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=vip_msg,
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def status(update: Update, context: CallbackContext):
    """Handler untuk command /status"""
    user = update.effective_user
    row = get_user_row(user.id)
    
    if row is None:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="🔍 Akun Anda belum terdaftar"
        )
        return
    
    reset_daily_quota_if_needed(row)
    
    vip_status = sheet_members.cell(row, 3).value
    vip_expiry = sheet_members.cell(row, 4).value or "-"
    quota = sheet_members.cell(row, 6).value
    
    # Format tanggal jika VIP
    if vip_expiry != "-":
        expiry_date = datetime.strptime(vip_expiry, "%Y-%m-%d")
        formatted_expiry = expiry_date.strftime("%d-%m-%Y")
    else:
        formatted_expiry = "-"
    
    status_msg = (
        f"📌 Status akun @{user.username or user.id}\n\n"
        f"🆔 ID Telegram: {user.id}\n"
        f"💎 Status: {'VIP Member' if check_vip_status(user.id) else 'Free Member'}\n"
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

async def gratis(update: Update, context: CallbackContext):
    """Handler untuk command /gratis"""
    user = update.effective_user
    row = get_user_row(user.id)
    if row is None:
        add_new_user(user)
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

async def vip_episode(update: Update, context: CallbackContext):
    """Handler untuk command /vip_episode"""
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

async def button_handler(update: Update, context: CallbackContext):
    """Handler untuk callback query dari inline keyboard"""
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

async def handle_message(update: Update, context: CallbackContext):
    """Handler untuk pesan teks biasa"""
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="ℹ️ Gunakan command yang tersedia. Ketik /start untuk melihat menu."
    )

def main():
    """Fungsi utama untuk menjalankan bot"""
    try:
        # Setup logging
        logging.basicConfig(
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            level=logging.INFO
        )
        logger = logging.getLogger(__name__)
        
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
        logger.error(f"⚠️ Bot conflict detected: {e}")
        time.sleep(5)
        main()
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        raise

if __name__ == "__main__":
    main()
