import os
import json
import gspread
from datetime import datetime, timedelta
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    CallbackQueryHandler
)

# === Konfigurasi Google Sheets ===
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
service_account_info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT"])
creds = ServiceAccountCredentials.from_json_keyfile_dict(service_account_info, scope)
client = gspread.authorize(creds)
spreadsheet = client.open("cdrama_database")
sheet_members = spreadsheet.worksheet("members")
sheet_films = spreadsheet.worksheet("film_links")

# Daftar paket VIP
VIP_PACKAGES = [
    {"label": "⚡ 1 Hari - Rp2.000", "days": 1, "price": 2000, "url": "https://trakteer.id/vip1hari"},
    {"label": "🔥 3 Hari - Rp5.000", "days": 3, "price": 5000, "url": "https://trakteer.id/vip3hari"},
    {"label": "💎 7 Hari - Rp10.000", "days": 7, "price": 10000, "url": "https://trakteer.id/vip7hari"},
    {"label": "🌟 30 Hari - Rp30.000", "days": 30, "price": 30000, "url": "https://trakteer.id/vip30hari"},
    {"label": "👑 5 Bulan - Rp150.000", "days": 150, "price": 150000, "url": "https://trakteer.id/vip5bulan"}
]

def get_user_row(user_id):
    data = sheet_members.get_all_records()
    for i, row in enumerate(data):
        if str(row['telegram_id']) == str(user_id):
            return i + 2
    return None

def add_new_user(user):
    today = datetime.now().strftime("%Y-%m-%d")
    sheet_members.append_row([
        str(user.id),
        user.username or "anonymous",
        "None",
        "",
        today,
        5
    ])

def reset_daily_quota_if_needed(row):
    today = datetime.now().strftime("%Y-%m-%d")
    last_reset = sheet_members.cell(row, 5).value
    if last_reset != today:
        sheet_members.update_cell(row, 5, today)
        sheet_members.update_cell(row, 6, 5)

def get_today_quota(row):
    return int(sheet_members.cell(row, 6).value)

def reduce_quota(row):
    current = get_today_quota(row)
    sheet_members.update_cell(row, 6, current - 1)

def get_film_link(code, is_vip=False):
    data = sheet_films.get_all_records()
    for row in data:
        if row['code'] == code:
            return row['vip_link'] if is_vip else row['free_link']
    return None

def check_vip_status(user_id):
    user_row = get_user_row(user_id)
    if user_row:
        vip_expiry = sheet_members.cell(user_row, 4).value
        if vip_expiry:
            return datetime.now() <= datetime.strptime(vip_expiry, "%Y-%m-%d")
    return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    
    await update.message.reply_text(welcome_msg, reply_markup=reply_markup)

async def vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        "✅ Update episode terbaru\n\n"
        "⬇️ Pilih paket favoritmu:"
    )
    
    await update.message.reply_text(vip_msg, reply_markup=reply_markup, parse_mode="Markdown")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    row = get_user_row(user.id)
    
    if row is None:
        await update.message.reply_text("🔍 Akun Anda belum terdaftar")
        return
    
    reset_daily_quota_if_needed(row)
    
    vip_status = sheet_members.cell(row, 3).value
    vip_expiry = sheet_members.cell(row, 4).value or "-"
    quota = sheet_members.cell(row, 6).value
    
    status_msg = (
        f"📌 **PROFIL PENGGUNA** @{user.username or user.id}\n\n"
        f"🆔 ID Telegram: `{user.id}`\n"
        f"💎 Status: {'✅ VIP' if check_vip_status(user.id) else '❌ Non-VIP'}\n"
        f"📅 Masa Aktif: {vip_expiry}\n"
        f"🎬 Kuota Gratis: {quota}/5\n\n"
        "💡 Upgrade ke VIP untuk akses tak terbatas!"
    )
    
    keyboard = [
        [InlineKeyboardButton("💎 Upgrade VIP", callback_data="vip")],
        [InlineKeyboardButton("🏠 Menu Utama", callback_data="menu")]
    ]
    
    await update.message.reply_text(
        status_msg,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def gratis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    row = get_user_row(user.id)
    if row is None:
        add_new_user(user)
        row = get_user_row(user.id)

    reset_daily_quota_if_needed(row)

    if get_today_quota(row) <= 0:
        await update.message.reply_text(
            "😢 Kuota gratis hari ini sudah habis!\n\n"
            "Anda bisa menonton lagi besok atau upgrade ke VIP untuk akses tak terbatas.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💎 Upgrade VIP", callback_data="vip")]
            ])
        )
        return

    if not context.args:
        await update.message.reply_text("ℹ️ Cara pakai: /gratis <kode_film>")
        return

    film_link = get_film_link(context.args[0])
    if film_link:
        reduce_quota(row)
        await update.message.reply_text(
            f"🎬 Berikut tontonan gratis Anda:\n{film_link}\n\n"
            f"Sisa kuota hari ini: {get_today_quota(row)}/5"
        )
    else:
        await update.message.reply_text("❌ Kode film tidak ditemukan")

async def vip_episode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not context.args:
        await update.message.reply_text("ℹ️ Cara pakai: /vip_episode <kode_film>")
        return

    film_link = get_film_link(context.args[0], is_vip=True)
    if not film_link:
        await update.message.reply_text("❌ Kode film tidak ditemukan")
        return

    if check_vip_status(user.id):
        await update.message.reply_text(f"💎 VIP Access:\n{film_link}")
    else:
        await update.message.reply_text(
            "🔒 Akses terbatas untuk member VIP!\n\n"
            "Yuk upgrade ke VIP untuk nonton sepuasnya. Cuma Rp2.000 untuk 1 hari!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💎 Upgrade Sekarang", callback_data="vip")],
                [InlineKeyboardButton("🎬 Coba Versi Gratis", callback_data=f"free_{context.args[0]}")]
            ])
        )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

def main():
    application = Application.builder().token(os.environ["TELEGRAM_BOT_TOKEN"]).build()
    
    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("vip", vip))
    application.add_handler(CommandHandler("vip_episode", vip_episode))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("gratis", gratis))
    
    # Callback query handler
    application.add_handler(CallbackQueryHandler(button_handler))
    
    print("🤖 Bot VIP Drama Cina siap melayani 24/7...")
    application.run_polling()

if __name__ == "__main__":
    main()
