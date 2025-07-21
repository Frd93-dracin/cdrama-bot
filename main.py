import os
import json
import gspread
import logging
import time
import base64
from datetime import datetime, timedelta
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
from oauth2client.service_account import ServiceAccountCredentials

# ===== CONFIGURATION =====
BOT_TOKEN = os.getenv('BOT_TOKEN', "7895835591:AAF8LfMEDGP03YaoLlEhsGqwNVcOdSssny0")
BOT_USERNAME = "VIPDramaCinaBot"  # Pastikan sama dengan username bot
CHANNEL_PRIVATE = "@DramaCinaArchive"  # Channel private untuk video
PORT = int(os.getenv('PORT', 8443))
WEBHOOK_URL = os.getenv('WEBHOOK_URL', "https://cdrama-bot.onrender.com") + '/' + BOT_TOKEN

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize Google Sheets connection
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
    logger.info("✅ Successfully connected to Google Sheets")
except Exception as e:
    logger.error(f"❌ Failed to initialize Google Sheets: {e}")
    raise

# VIP Packages
VIP_PACKAGES = [
    {"label": "⚡ 1 Hari - Rp2.000", "days": 1, "price": 2000, "url": "https://trakteer.id/vip1hari"},
    {"label": "🔥 3 Hari - Rp5.000", "days": 3, "price": 5000, "url": "https://trakteer.id/vip3hari"},
    {"label": "💎 7 Hari - Rp10.000", "days": 7, "price": 10000, "url": "https://trakteer.id/vip7hari"},
    {"label": "🌟 30 Hari - Rp30.000", "days": 30, "price": 30000, "url": "https://trakteer.id/vip30hari"},
    {"label": "👑 5 Bulan (FREE 1 BULAN) - Rp150.000", "days": 150, "price": 150000, "url": "https://trakteer.id/vip5bulan"}
]

# ===== HELPER FUNCTIONS =====
def refresh_connection():
    try:
        global client, sheet_members, sheet_films
        client = gspread.authorize(creds)
        spreadsheet = client.open("cdrama_database")
        sheet_members = spreadsheet.worksheet("members")
        sheet_films = spreadsheet.worksheet("film_links")
        logger.info("Google Sheets connection refreshed")
        return True
    except Exception as e:
        logger.error(f"Failed to refresh connection: {e}")
        return False

def safe_sheets_operation(func, max_retries=3):
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            logger.warning(f"Attempt {attempt+1} failed: {e}")
            if attempt == max_retries - 1:
                raise
            time.sleep(2)
            refresh_connection()

def get_user_row(user_id):
    def operation():
        records = sheet_members.get_all_records()
        for idx, record in enumerate(records, start=2):
            if str(record.get('telegram_id', '')) == str(user_id):
                return idx
        return None
    return safe_sheets_operation(operation)

def add_new_user(user):
    def operation():
        sheet_members.append_row([
            str(user.id),
            user.username or "",
            "non-vip",
            "",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            5  # Initial quota
        ])
        return True
    return safe_sheets_operation(operation)

def reset_daily_quota_if_needed(row):
    def operation():
        last_updated = sheet_members.cell(row, 5).value
        if last_updated:
            last_date = datetime.strptime(last_updated, "%Y-%m-%d %H:%M:%S").date()
            if last_date < datetime.now().date():
                sheet_members.update_cell(row, 6, 5)
                sheet_members.update_cell(row, 5, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    safe_sheets_operation(operation)

def get_today_quota(row):
    def operation():
        return int(sheet_members.cell(row, 6).value)
    return safe_sheets_operation(operation)

def reduce_quota(row):
    def operation():
        current = get_today_quota(row)
        if current > 0:
            sheet_members.update_cell(row, 6, current - 1)
    safe_sheets_operation(operation)

def get_film_link(film_code, is_vip=False):
    def operation():
        records = sheet_films.get_all_records()
        for record in records:
            if record.get('code') == film_code:
                return record.get('vip_link' if is_vip else 'free_link')
        return None
    return safe_sheets_operation(operation)

def check_vip_status(user_id):
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

# ===== NEW FILM PART FUNCTIONS =====
def get_film_info(film_code):
    """Get complete film data including message IDs"""
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
    """Encode film code for URLs"""
    return base64.urlsafe_b64encode(f"{film_code}_{part}".encode()).decode()

def decode_film_code(encoded_str):
    """Decode film code from URLs"""
    return base64.urlsafe_b64decode(encoded_str.encode()).decode().split("_")

# ===== COMMAND HANDLERS =====
async def start(update: Update, context: CallbackContext):
    try:
        user = update.effective_user
        row = get_user_row(user.id)
        if row is None:
            if not add_new_user(user):
                raise Exception("Failed to register new user")

        # Handle film links if provided
        if context.args:
            try:
                encoded_str = context.args[0]
                film_code, part = decode_film_code(encoded_str)
                film_data = get_film_info(film_code)
                
                if not film_data:
                    await update.message.reply_text("❌ Film tidak ditemukan")
                    return

                if part == "P1":
                    # Forward Part 1 to user
                    try:
                        await context.bot.forward_message(
                            chat_id=update.effective_chat.id,
                            from_chat_id=CHANNEL_PRIVATE,
                            message_id=film_data['free_msg_id']
                        )
                    except Exception as e:
                        logger.error(f"Error forwarding P1: {e}")
                        await update.message.reply_text("❌ Gagal memuat video Part 1")
                        return
                    
                    # Show continue button for Part 2
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
                
                elif part == "P2":
                    if check_vip_status(user.id) or not film_data['is_part2_vip']:
                        try:
                            await context.bot.forward_message(
                                chat_id=update.effective_chat.id,
                                from_chat_id=CHANNEL_PRIVATE,
                                message_id=film_data['vip_msg_id']
                            )
                            return
                        except Exception as e:
                            logger.error(f"Error forwarding P2: {e}")
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
                logger.error(f"Error processing film link: {e}")
                # Fall through to normal start if there's an error

        # Original start message (only shown if no valid film code provided)
        keyboard = [
            [InlineKeyboardButton("🎬 Drama List", url="https://t.me/DramaCinaPlus")],
            [InlineKeyboardButton("💎 VIP Subscription", callback_data="vip")],
            [InlineKeyboardButton("📊 Account Status", callback_data="status")]
        ]
        
        await update.message.reply_text(
            f"🎉 Welcome to VIP Drama Cina, {user.username or 'Friend'}! 🎉\n\n"
            "Enjoy the best Chinese dramas in HD quality:\n"
            "✨ 5 free views per day\n"
            "💎 Unlimited access for VIP members\n\n"
            "Please choose from the menu below:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"Error in start: {e}")
        await send_error_message(update, context)

async def vip(update: Update, context: CallbackContext):
    try:
        keyboard = []
        for package in VIP_PACKAGES:
            keyboard.append([InlineKeyboardButton(package["label"], url=package["url"])])
        keyboard.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="menu")])
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="💎 **VIP SUBSCRIPTION PACKAGES** 💎\n\n"
                 "Get unlimited access to all dramas:\n"
                 "✅ Watch as much as you want\n"
                 "✅ Best HD quality\n"
                 "✅ Daily episode updates\n\n"
                 "⬇️ Choose your favorite package:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in vip: {e}")
        await send_error_message(update, context)

async def status(update: Update, context: CallbackContext):
    try:
        user = update.effective_user
        row = get_user_row(user.id)
        if row is None:
            if not add_new_user(user):
                raise Exception("Failed to register new user")
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
            f"📌 Account status @{user.username or user.id}\n\n"
            f"🆔 Telegram ID: {user.id}\n"
            f"💎 Status: {'VIP Member' if is_vip else 'Free Member'}\n"
            f"🎬 Today's remaining quota: {quota}/5\n"
            f"📅 Active until: {formatted_expiry}\n\n"
            "Thank you for using VIP Drama Cina"
        )

        keyboard = [
            [InlineKeyboardButton("💎 Upgrade VIP", callback_data="vip")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="menu")]
        ]
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=status_msg,
            reply_markup=InlineKeyboardMarkup(keyboard)
    except Exception as e:
        logger.error(f"Error in status: {e}")
        await send_error_message(update, context)

async def gratis(update: Update, context: CallbackContext):
    try:
        user = update.effective_user
        row = get_user_row(user.id)
        if row is None:
            if not add_new_user(user):
                raise Exception("Failed to register new user")
            row = get_user_row(user.id)

        reset_daily_quota_if_needed(row)

        if get_today_quota(row) <= 0:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="😢 Today's free quota has run out!\n\n"
                     "You can watch again tomorrow or upgrade to VIP for unlimited access.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💎 Upgrade VIP", callback_data="vip")]
                ])
            )
            return

        if not context.args:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="ℹ️ Usage: /free <drama_code>"
            )
            return

        film_link = get_film_link(context.args[0])
        if film_link:
            reduce_quota(row)
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"🎬 Here's your free content:\n{film_link}\n\n"
                     f"Remaining quota today: {get_today_quota(row)}/5"
            )
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Drama code not found"
            )
    except Exception as e:
        logger.error(f"Error in free: {e}")
        await send_error_message(update, context)

async def vip_episode(update: Update, context: CallbackContext):
    try:
        user = update.effective_user
        if not context.args:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="ℹ️ Usage: /vip_episode <drama_code>"
            )
            return

        film_link = get_film_link(context.args[0], is_vip=True)
        if not film_link:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Drama code not found"
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
                text="🔒 VIP members only content!\n\n"
                     "Upgrade to VIP to watch unlimited content. Only Rp2,000 for 1 day!",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💎 Upgrade Now", callback_data="vip")],
                    [InlineKeyboardButton("🎬 Try Free Version", callback_data=f"free_{context.args[0]}")]
                ])
            )
    except Exception as e:
        logger.error(f"Error in vip_episode: {e}")
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
        logger.error(f"Error in button_handler: {e}")
        await send_error_message(update, context)

async def handle_message(update: Update, context: CallbackContext):
    try:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="ℹ️ Please use available commands. Type /start to see the menu."
        )
    except Exception as e:
        logger.error(f"Error in handle_message: {e}")

async def send_error_message(update: Update, context: CallbackContext):
    try:
        error_msg = (
            "⚠️ Sorry, we're experiencing technical issues\n\n"
            "Our team has been notified. "
            "Please try again later or contact admin if the problem persists."
        )
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=error_msg
        )
    except Exception as e:
        logger.error(f"Failed to send error message: {e}")

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

async def post_init(application: Application) -> None:
    """Initialize webhook after startup"""
    try:
        await application.bot.delete_webhook()
        await application.bot.set_webhook(
            url=WEBHOOK_URL,
            max_connections=40
        )
        logger.info(f"✅ Webhook successfully set to: {WEBHOOK_URL}")
    except Exception as e:
        logger.error(f"❌ Failed to set webhook: {e}")
        raise

def main() -> None:
    """Run the bot with webhook"""
    try:
        # Create Application
        application = Application.builder() \
            .token(BOT_TOKEN) \
            .post_init(post_init) \
            .build()

        # Register handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("vip", vip))
        application.add_handler(CommandHandler("status", status))
        application.add_handler(CommandHandler("free", gratis))
        application.add_handler(CommandHandler("vip_episode", vip_episode))
        application.add_handler(CommandHandler("generate_link", generate_film_links))
        application.add_handler(CallbackQueryHandler(button_handler))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        logger.info("🤖 Bot starting in webhook mode...")
        
        # Run webhook server
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=WEBHOOK_URL,
            url_path=BOT_TOKEN,
            cert=None,
            drop_pending_updates=True
        )

    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        raise

if __name__ == "__main__":
    main()
