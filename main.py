import asyncio
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes

# === Konfigurasi Google Sheets ===
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scope)
client = gspread.authorize(creds)
spreadsheet = client.open("cdrama_database")
sheet_members = spreadsheet.worksheet("members")
sheet_films = spreadsheet.worksheet("film_links")


# === Fungsi bantu ===
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
        "",  # akhir masa VIP
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


# === Command Handler ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    row = get_user_row(user.id)
    if row is None:
        add_new_user(user)

    username = user.username or "teman"
    message = (
        f"👋 Selamat datang @{username} di VIP Drama Cina!\n\n"
        f"1️⃣ List Film: [DramaCina+](https://t.me/DramaCinaPlus)\n"
        f"2️⃣ Bioskop Membership: [VIPDramaCina+](https://t.me/VIPDramaCinaBot)\n\n"
        "Segera upgrade status-Mu untuk akses tak terbatas 🎬"
    )
    await update.message.reply_markdown(message)


async def gratis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    row = get_user_row(user.id)
    if row is None:
        add_new_user(user)
        row = get_user_row(user.id)

    reset_daily_quota_if_needed(row)

    if get_today_quota(row) <= 0:
        await update.message.reply_text("🚫 Kuota tontonan gratis kamu hari ini sudah habis. Silakan coba lagi besok atau daftar VIP dengan /vip.")
        return

    if context.args:
        kode = context.args[0]
        link = get_film_link(kode)
        if link:
            reduce_quota(row)
            await update.message.reply_text(f"🎬 Ini link part gratismu hari ini:\n{link}")
        else:
            await update.message.reply_text("❌ Kode film tidak ditemukan.")
    else:
        await update.message.reply_text("ℹ️ Gunakan format: /gratis <kode_film>\nContoh: /gratis ep01g")


async def vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or "teman"
    message = f"Halo @{username}! Pilih jenis VIP yang kamu inginkan:"

    keyboard = [
        [InlineKeyboardButton("VIP 1 Hari - Rp 2.000", url="https://trakteer.id/link1")],
        [InlineKeyboardButton("VIP 3 Hari - Rp 5.000", url="https://trakteer.id/link2")],
        [InlineKeyboardButton("VIP 7 Hari - Rp 10.000", url="https://trakteer.id/link3")],
        [InlineKeyboardButton("VIP 30 Hari - Rp 30.000", url="https://trakteer.id/link4")],
        [InlineKeyboardButton("VIP 5 Bulan - Rp 150.000", url="https://trakteer.id/link5")],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(message, reply_markup=reply_markup)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    username = user.username or "teman"
    row = get_user_row(user.id)

    if row is None:
        await update.message.reply_text("Kamu belum terdaftar.")
        return

    vip_status = sheet_members.cell(row, 2).value
    vip_expiry = sheet_members.cell(row, 4).value
    quota = sheet_members.cell(row, 6).value

    message = (
        f"👤 @{username}, berikut status kamu:\n\n"
        f"💎 Status VIP: {vip_status or 'Belum VIP'}\n"
        f"🆔 Telegram ID: {user.id}\n"
        f"🎟️ Kuota Gratis Hari Ini: {quota}\n"
        f"📆 VIP Berakhir: {vip_expiry or '-'}\n\n"
        f"Terima kasih telah menonton di VIP Drama Cina!"
    )

    await update.message.reply_text(message)


# === MAIN ===
def main():
    app = Application.builder().token("7895835591:AAF8LfMEDGP03YaoLlEhsGqwNVcOdSssny0").build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("gratis", gratis))
    app.add_handler(CommandHandler("vip", vip))
    app.add_handler(CommandHandler("status", status))

    print("Bot berjalan...")
    app.run_polling()


if __name__ == "__main__":
    main()
