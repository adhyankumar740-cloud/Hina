# main.py - Hina Bot (Render Compatible)
import os
import logging
import asyncio
import uuid
import pytz
import random
from collections import defaultdict
from datetime import datetime
import psutil
import re
import aiohttp
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
from flask import Flask

# Load environment variables
load_dotenv()

# --- Environment Variables ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# --- Global Variables ---
start_time = datetime.now()
total_messages_processed = 0
chat_members = defaultdict(dict)
user_bots_storage = {}

# --- Logging Configuration ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Flask App for Render Health Checks ---
app = Flask(__name__)

@app.route('/')
def home():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>🤖 Hina Bot</title>
        <style>
            body { font-family: Arial, sans-serif; text-align: center; padding: 50px; }
            .status { color: green; font-size: 24px; }
        </style>
    </head>
    <body>
        <h1>🤖 Hina Bot is Running!</h1>
        <p class="status">✅ Bot Status: <strong>ACTIVE</strong></p>
        <p>Telegram Bot: @hina_master_bot</p>
        <p>Uptime: {}</p>
    </body>
    </html>
    """.format(str(datetime.now() - start_time).split('.')[0])

@app.route('/health')
def health():
    return {"status": "healthy", "bot": "running"}

# --- Hina AI Prompt ---
HINA_SYSTEM_PROMPT = """You are Hina, a super fun, playful, and slightly flirty AI girlfriend experience."""

# --- Chat History Management ---
chat_histories = defaultdict(list)
MAX_HISTORY_LENGTH = 10

def add_to_history(chat_id, role, text):
    chat_histories[chat_id].append({'role': role, 'content': text})
    if len(chat_histories[chat_id]) > MAX_HISTORY_LENGTH:
        chat_histories[chat_id].pop(0)

# --- Bot Commands ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    welcome_text = (
        f"Hey there {user.first_name}! 👋\n\n"
        "I'm **Hina** - Your AI Companion! 🤖✨\n\n"
        "🚀 **Features:**\n"
        "• Smart conversations\n"
        "• Fun commands\n"
        "• Always here for you! 💫\n\n"
        "Use `/help` to see all commands!"
    )
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "💖 **Hina Bot Commands** 💖\n\n"
        "💬 **Chat Commands:**\n"
        "• `/start` - Welcome message\n"
        "• `/help` - This help\n"
        "• `/couple` - Matchmake in groups\n\n"
        "🤖 **Bot Creation:**\n"
        "• `/clone <name> <personality> <token>` - Create bot\n"
        "• `/my_bots` - Your created bots\n"
        "• `/deploy_help` - Deployment guide\n\n"
        "💫 **Just chat with me naturally!**"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def couple_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if update.effective_chat.type == 'private':
        await update.message.reply_text("This command works in groups only! 😊")
        return

    current_chat_members = chat_members.get(chat_id, {})
    
    if len(current_chat_members) < 2:
        await update.message.reply_text("Need at least 2 people for a couple! 💑")
        return
        
    try:
        user_ids = list(current_chat_members.keys())
        couple_ids = random.sample(user_ids, 2)
        
        user1_id, user2_id = couple_ids[0], couple_ids[1]
        user1_name, user2_name = current_chat_members[user1_id], current_chat_members[user2_id]
        
        user1_mention = f"[{user1_name}](tg://user?id={user1_id})"
        user2_mention = f"[{user2_name}](tg://user?id={user2_id})"

        messages = [
            f"Love alert! 💘 {user1_mention} + {user2_mention} = PERFECT MATCH! 💖",
            f"Couple of the day: {user1_mention} ❤️ {user2_mention}! 🎉",
        ]
        
        couple_message = random.choice(messages)
        
        await context.bot.send_message(
            chat_id=chat_id,
            text=couple_message,
            parse_mode='Markdown'
        )

    except Exception as e:
        await update.message.reply_text("Oops! My matchmaker broke! 💔")

# --- Clone Feature ---
async def clone_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not context.args or len(context.args) < 3:
        help_text = (
            "🤖 **Bot Creation** 🤖\n\n"
            "Usage: `/clone <name> <personality> <token>`\n\n"
            "**Personality Types:**\n"
            "• `friendly` - Warm 🤗\n"
            "• `playful` - Fun 🎮\n"
            "• `flirty` - Charming 😘\n\n"
            "**Example:**\n"
            "`/clone Priya flirty 123456789:ABCdef...`"
        )
        await update.message.reply_text(help_text, parse_mode='Markdown')
        return
    
    bot_name = context.args[0]
    personality_type = context.args[1].lower()
    bot_token = context.args[2]
    
    # Validate
    valid_personalities = ["friendly", "playful", "flirty"]
    if personality_type not in valid_personalities:
        await update.message.reply_text(f"❌ Choose from: {', '.join(valid_personalities)}")
        return
    
    if not re.match(r'^\d+:[a-zA-Z0-9_-]+$', bot_token):
        await update.message.reply_text("❌ Invalid bot token format!")
        return
    
    # Save bot
    key = f"{user_id}_{bot_name}"
    user_bots_storage[key] = {
        'user_id': user_id,
        'bot_name': bot_name, 
        'bot_token': bot_token,
        'personality': personality_type
    }
    
    success_msg = (
        f"✅ **{bot_name} Bot Saved!** ✅\n\n"
        f"**Personality:** {personality_type.title()}\n"
        "**Next:** Deploy using the code I'll send!\n\n"
        "Use `/deploy_help` for guide!"
    )
    
    await update.message.reply_text(success_msg, parse_mode='Markdown')
    
    # Send simple code
    bot_code = f"""# {bot_name} Bot
import os
from telegram.ext import Application, CommandHandler, MessageHandler, filters
import aiohttp

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_KEY = os.getenv("DEEPSEEK_API_KEY")

async def start(update, context):
    await update.message.reply_text(f"Hey! I'm {bot_name}! 💫")

async def handle_message(update, context):
    await update.message.reply_text("I'm alive! 🎉")

app = Application.builder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT, handle_message))
app.run_polling()
"""
    
    await update.message.reply_document(
        document=bot_code.encode('utf-8'),
        filename=f"{bot_name}_bot.py",
        caption=f"Here's your {bot_name} bot code! 🚀"
    )

async def my_bots_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_bots = [bot for key, bot in user_bots_storage.items() if str(user_id) in key]
    
    if not user_bots:
        await update.message.reply_text("No bots created yet! Use `/clone` to create one! 🚀")
        return
    
    bots_list = ["🤖 **Your Bots:**\n"]
    for i, bot in enumerate(user_bots, 1):
        bots_list.append(f"{i}. {bot['bot_name']} ({bot['personality']})")
    
    await update.message.reply_text("\n".join(bots_list))

async def deploy_help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🚀 **Deployment Guide** 🚀\n\n"
        "1. Get bot token from @BotFather\n"
        "2. Get API key from openrouter.ai\n"
        "3. Deploy to render.com\n"
        "4. Add environment variables\n"
        "5. Your bot is live! 🎉"
    )
    await update.message.reply_text(help_text)

# --- Message Handler ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global total_messages_processed
    
    if not update.message or not update.message.text:
        return
        
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    user_message = update.message.text

    if update.effective_chat.type != 'private':
        chat_members[chat_id][user_id] = update.effective_user.full_name

    # Simple AI response
    if any(word in user_message.lower() for word in ['hi', 'hello', 'hey', 'hina']):
        responses = [
            "Hey there! 😊",
            "Hello! How can I help? 💫",
            "Hi! Ready to chat? 🎉",
            "Hey! What's up? 😄"
        ]
        await update.message.reply_text(random.choice(responses))
        total_messages_processed += 1

# --- Start Bot Function ---
def start_bot():
    """Start the Telegram bot"""
    if not TELEGRAM_BOT_TOKEN:
        print("❌ ERROR: TELEGRAM_BOT_TOKEN not set!")
        return

    print("🤖 Starting Hina Bot...")
    
    # Create application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("couple", couple_command))
    application.add_handler(CommandHandler("clone", clone_command))
    application.add_handler(CommandHandler("my_bots", my_bots_command))
    application.add_handler(CommandHandler("deploy_help", deploy_help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🚀 Bot is running with polling...")
    
    # Start polling
    application.run_polling()

# --- Main Function ---
if __name__ == "__main__":
    import threading
    
    # Start Flask server in a thread
    port = int(os.environ.get("PORT", 10000))
    print(f"🌐 Starting web server on port {port}")
    
    def run_flask():
        app.run(host='0.0.0.0', port=port, debug=False)
    
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Start Telegram bot
    start_bot()
