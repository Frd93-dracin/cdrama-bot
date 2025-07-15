import os
import json
import gspread
import logging
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
PORT = int(os.getenv('PORT', 8443))
WEBHOOK_URL = os.getenv('WEBHOOK_URL') + '/' + BOT_TOKEN  # Full webhook URL

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
    {"label": "⚡ 1 Day - Rp2.000", "days": 1, "price": 2000, "url": "https://trakteer.id/vip1hari"},
    {"label": "🔥 3 Days - Rp5.000", "days": 3, "price": 5000, "url": "https://trakteer.id/vip3hari"},
    {"label": "💎 7 Days - Rp10.000", "days": 7, "price": 10000, "url": "https://trakteer.id/vip7hari"},
    {"label": "🌟 30 Days - Rp30.000", "days": 30, "price": 30000, "url": "https://trakteer.id/vip30hari"},
    {"label": "👑 5 Months (FREE 1 MONTH) - Rp150.000", "days": 150, "price": 150000, "url": "https://trakteer.id/vip5bulan"}
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

# [Include all your other helper functions here...]

# ===== COMMAND HANDLERS =====
async def start(update: Update, context: CallbackContext):
    try:
        user = update.effective_user
        row = get_user_row(user.id)
        if row is None:
            if not add_new_user(user):
                raise Exception("Failed to register new user")

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

# [Include all your other command handlers here...]

async def post_init(application: Application) -> None:
    """Initialize webhook after startup"""
    await application.bot.set_webhook(WEBHOOK_URL)
    logger.info(f"Webhook set to: {WEBHOOK_URL}")

def main() -> None:
    """Run the bot with webhook"""
    try:
        # Create Application
        application = Application.builder() \
            .token(BOT_TOKEN) \
            .post_init(post_init) \
            .build()

        # Add handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("vip", vip))
        application.add_handler(CommandHandler("status", status))
        application.add_handler(CommandHandler("free", gratis))
        application.add_handler(CommandHandler("vip_episode", vip_episode))
        application.add_handler(CallbackQueryHandler(button_handler))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        logger.info("🤖 Bot starting in webhook mode...")
        
        # Run webhook server
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=WEBHOOK_URL,
            cert=None,
            drop_pending_updates=True
        )

    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        raise

if __name__ == "__main__":
    main()
