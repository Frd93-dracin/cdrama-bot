import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackContext
import datetime
import os

# Konfigurasi Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scope)
client = gspread.authorize(creds)

# Buka Spreadsheet dan worksheet
spreadsheet = client.open("cdrama_database")
sheet_members = spreadsheet.worksheet("members")
sheet_films = spreadsheet.worksheet("film_links")

def get_user_row(user_id):
    data = sheet_members.get_all_records()
    for i, row in enumerate(data):
        if str(row['telegram_id']) == str(user_id):
            return i + 2
    return None

def add_new_user(user):
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    sheet_members.append_row([
        str(user.id),
        user.username or "anonymous",
        "None",
        "",
        today,
        5
    ])

def reset_daily_quota_if_needed(row):
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    last_reset = sheet_members.cell(row, 5).value
    if last_reset != today:
        sheet_members.update_cell(row, 5, today)
        sheet_members.update_cell(row, 6, 5)

def get_today_quota(row):
    return int(sheet_members.cell(row, 6).value)

def reduce_quota(row):
    current = get_today_quota(row)
    sheet_members.update_cell(row, 6, current - 1)

def get_film_link(code):
    data = sheet_films.get_all_records()
    for row in data:
        if row['code'] == code:
            return row['telegram_link']
    return None

def start(update: Update, context: CallbackContext):
    user = update.effective_user
    row = get_user_row(user.id)
    if row is None:
        add_new_user(user)

    message = f"""
👋 Selamat datang <b>@{user.username}</b> di <b>VIP Drama Cina</b>!

1️⃣ List Film: <a href='https://t.me/DramaCinaPlus'>DramaCina+</a>
2️⃣ Bioskop Membership: <a href='https://t.me/VIPDramaCinaBot'>VIPDramaCina+</a>

Segera upgrade status-Mu untuk akses tak terbatas 🎬
"""
    update.message.reply_text(message, parse_mode='HTML')

def akses_gratis(update: Update, context: CallbackContext):
    user = update.effective_user
    row = get_user_row(user.id)
    if row is None:
        add_new_user(user)
        row = get_user_row(user.id)
    reset_daily_quota_if_needed(row)
    if get_today_quota(row) <= 0:
        update.message.reply_text("🚫 Kuota tontonan gratis kamu hari ini sudah habis.\nSilakan coba lagi besok atau daftar VIP dengan perintah /vip.")
        return
    if context.args:
        kode = context.args[0]
        link = get_film_link(kode)
        if link:
            reduce_quota(row)
            update.message.reply_text(f"🎬 Ini link part gratismu hari ini:\n{link}")
        else:
            update.message.reply_text("❌ Kode film tidak ditemukan. Pastikan kamu mengetik dengan benar.")
    else:
        update.message.reply_text("ℹ️ Gunakan format: /gratis <kode_film>\nContoh: /gratis ep01g")

def vip(update: Update, context: CallbackContext):
    keyboard = [
        [InlineKeyboardButton("VIP 1 Hari - Rp2.000", url="https://trakteer.id/namakamu/membership/vip-1-hari")],
        [InlineKeyboardButton("VIP 3 Hari - Rp5.000", url="https://trakteer.id/namakamu/membership/vip-3-hari")],
        [InlineKeyboardButton("VIP 7 Hari - Rp10.000", url="https://trakteer.id/namakamu/membership/vip-7-hari")],
        [InlineKeyboardButton("VIP 30 Hari - Rp30.000", url="https://trakteer.id/namakamu/membership/vip-30-hari")],
        [InlineKeyboardButton("VIP 5 Bulan - Rp150.000", url="https://trakteer.id/namakamu/membership/vip-5-bulan")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("💎 Pilih paket VIP kamu:", reply_markup=reply_markup)

def status(update: Update, context: CallbackContext):
    user = update.effective_user
    row = get_user_row(user.id)
    if row is None:
        add_new_user(user)
        row = get_user_row(user.id)

    reset_daily_quota_if_needed(row)
    membership = sheet_members.cell(row, 3).value or "Belum Member VIP"
    quota = get_today_quota(row)
    expired = sheet_members.cell(row, 4).value

    message = f"""
👤 <b>Status Akun</b> @<b>{user.username}</b>

🆔 ID Telegram: <code>{user.id}</code>
💎 Status: <b>{membership}</b>
🎬 Sisa Kuota Hari Ini: <b>{quota}</b>
📅 Masa Aktif Hingga: <b>{expired}</b>

Terima kasih telah menggunakan VIP Drama Cina!
"""
    update.message.reply_text(message, parse_mode='HTML')

def menu(update: Update, context: CallbackContext):
    keyboard = [
        [KeyboardButton("Member VIP")],
        [KeyboardButton("Lihat Status")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    update.message.reply_text("≡ Menu dibuka.", reply_markup=reply_markup)

def main():
    TOKEN = "7895835591:AAF8LfMEDGP03YaoLlEhsGqwNVcOdSssny0"
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("gratis", akses_gratis))
    dp.add_handler(CommandHandler("vip", vip))
    dp.add_handler(CommandHandler("status", status))
    dp.add_handler(CommandHandler("menu", menu))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
