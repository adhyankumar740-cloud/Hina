# main.py (Fixed Event Loop Issue)
import os
import logging
import asyncio
import uuid
import pytz
import traceback
import random
from collections import defaultdict
from datetime import datetime, timedelta
import psutil
import json
import re
import aiohttp
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
import time

# Load environment variables
load_dotenv()

# --- Environment Variables ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
NEON_DATABASE_URL = os.getenv("NEON_DATABASE_URL")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
try:
    BROADCAST_ADMIN_ID = int(os.getenv("BROADCAST_ADMIN_ID", 0))
except (ValueError, TypeError):
    BROADCAST_ADMIN_ID = 0

# --- Global Variables ---
start_time = datetime.now()
total_messages_processed = 0
known_users = set()
chat_members = defaultdict(dict)
sudo_users = set()

# --- Multi-Bot System ---
user_bots = {}
bot_applications = {}

# --- Logging Configuration ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Hina AI Prompt ---
HINA_SYSTEM_PROMPT = """You are Hina, a super fun, playful, and slightly flirty AI girlfriend experience."""

# --- Chat History Management ---
chat_histories = defaultdict(list)
MAX_HISTORY_LENGTH = 10

def add_to_history(chat_id, role, text):
    chat_histories[chat_id].append({'role': role, 'content': text})
    if len(chat_histories[chat_id]) > MAX_HISTORY_LENGTH:
        chat_histories[chat_id].pop(0)

# --- Bot Enable/Disable State ---
bot_status = defaultdict(lambda: True)
global_bot_status = True

# --- Simplified Database (Temporary) ---
user_bots_storage = {}
chat_storage = {}

async def save_user_bot(user_id, bot_name, bot_token, personality):
    """Temporary storage without database"""
    key = f"{user_id}_{bot_name}"
    user_bots_storage[key] = {
        'user_id': user_id,
        'bot_name': bot_name, 
        'bot_token': bot_token,
        'personality': personality
    }
    return True

async def get_user_bots(user_id):
    """Temporary get user bots"""
    user_bots = []
    for key, bot_data in user_bots_storage.items():
        if str(user_id) in key:
            user_bots.append(bot_data)
    return user_bots

async def get_all_active_bots():
    """Get all active bots"""
    return list(user_bots_storage.values())

# --- Multi-Bot Management ---
def generate_personalized_prompt(bot_name, personality_type):
    """Generate personalized system prompt"""
    
    base_prompts = {
        "friendly": f"""You are {bot_name}, a friendly and cheerful AI companion.""",
        "playful": f"""You are {bot_name}, a playful and mischievous AI companion!""",
        "flirty": f"""You are {bot_name}, a charming and slightly flirty AI companion!"""
    }
    
    return base_prompts.get(personality_type, base_prompts["friendly"])

async def start_user_bot(bot_token, bot_name, personality):
    """Start a user's bot - SIMPLIFIED VERSION"""
    try:
        # Create a simple bot instance without separate event loop
        bot = Bot(token=bot_token)
        
        # Store the bot
        user_bots[bot_token] = {
            'bot': bot,
            'name': bot_name,
            'personality': personality
        }
        
        logger.info(f"User bot {bot_name} ready with token: {bot_token[:10]}...")
        return True
        
    except Exception as e:
        logger.error(f"Failed to setup user bot {bot_name}: {e}")
        return False

async def user_handle_message(bot_token, chat_id, message_text):
    """Handle messages for user bots"""
    if bot_token not in user_bots:
        return "Bot not available."
    
    bot_data = user_bots[bot_token]
    bot_name = bot_data['name']
    system_prompt = generate_personalized_prompt(bot_name, bot_data['personality'])
    
    # Get AI response
    response = await get_user_bot_response(message_text, system_prompt, bot_name)
    return response

async def get_user_bot_response(user_message: str, system_prompt: str, bot_name: str) -> str:
    """Get AI response for user bots"""
    if not DEEPSEEK_API_KEY:
        return "🔧 I'm getting an upgrade! Please try again later."
    
    try:
        async with aiohttp.ClientSession() as session:
            headers = {
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            }
            
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ]
            
            payload = {
                "model": "deepseek-chat",
                "messages": messages,
                "temperature": 0.8,
                "max_tokens": 500
            }
            
            async with session.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    return data['choices'][0]['message']['content']
                else:
                    return "🤔 I'm having trouble thinking right now. Try again later!"
                        
    except Exception as e:
        logger.error(f"User bot API error: {e}")
        return "😴 I'm feeling a bit sleepy... Try again in a moment!"

async def initialize_all_bots():
    """Initialize all user bots on startup"""
    active_bots = await get_all_active_bots()
    
    for bot in active_bots:
        success = await start_user_bot(
            bot['bot_token'], 
            bot['bot_name'], 
            bot['personality']
        )
        
        if success:
            logger.info(f"Initialized bot: {bot['bot_name']}")
        else:
            logger.error(f"Failed to initialize bot: {bot['bot_name']}")

# --- Clone Command ---
async def clone_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Create and setup a user bot"""
    user_id = update.effective_user.id
    
    if not context.args or len(context.args) < 3:
        help_text = (
            "🤖 **Instant Bot Creation** 🤖\n\n"
            "Usage: `/clone <bot_name> <personality> <bot_token>`\n\n"
            "**Personality Types:**\n"
            "• `friendly` - Warm and supportive 🤗\n"
            "• `playful` - Fun and mischievous 🎮\n"
            "• `flirty` - Charming and flirty 😘\n\n"
            "**Example:**\n"
            "`/clone Priya flirty 123456789:ABCdefGHIjklMNopQRstuVWXyz`\n\n"
            "💡 *Your bot will be ready instantly!* 🚀"
        )
        await update.message.reply_text(help_text, parse_mode='Markdown')
        return
    
    bot_name = context.args[0]
    personality_type = context.args[1].lower()
    bot_token = context.args[2]
    
    # Validate personality
    valid_personalities = ["friendly", "playful", "flirty"]
    if personality_type not in valid_personalities:
        await update.message.reply_text(
            f"❌ Invalid personality! Choose from: {', '.join(valid_personalities)}"
        )
        return
    
    # Validate bot token format
    if not re.match(r'^\d+:[a-zA-Z0-9_-]+$', bot_token):
        await update.message.reply_text(
            "❌ Invalid bot token format!\n"
            "Make sure it looks like: `123456789:ABCdefGHIjklMNopQRstuVWXyz`"
        )
        return
    
    # Test the bot token
    try:
        test_bot = Bot(token=bot_token)
        bot_info = await test_bot.get_me()
        bot_username = bot_info.username
    except Exception as e:
        await update.message.reply_text(
            f"❌ Invalid bot token! Error: {str(e)}\n"
            "Please check:\n"
            "• Token is correct\n"
            "• You copied from @BotFather\n"
            "• Bot is properly created"
        )
        return
    
    # Save to storage
    success = await save_user_bot(user_id, bot_name, bot_token, personality_type)
    
    if not success:
        await update.message.reply_text("❌ Failed to save your bot. Please try again!")
        return
    
    # Setup the bot
    bot_setup = await start_user_bot(bot_token, bot_name, personality_type)
    
    if bot_setup:
        success_msg = (
            f"✅ **{bot_name} Bot is READY!** ✅\n\n"
            f"**Bot Username:** @{bot_username}\n"
            f"**Personality:** {personality_type.title()}\n"
            f"**Status:** 🟢 Configured\n\n"
            "**How to use:**\n"
            "1. Go to @BotFather\n"
            "2. Set commands for your bot\n"
            "3. Add description\n"
            "4. Start chatting!\n\n"
            "💫 *Your bot is configured and ready!*"
        )
        
        await update.message.reply_text(success_msg, parse_mode='Markdown')
        
    else:
        await update.message.reply_text(
            "❌ Failed to setup your bot. Please try again later!"
        )

async def my_bots_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user's created bots"""
    user_id = update.effective_user.id
    user_bots_list = await get_user_bots(user_id)
    
    if not user_bots_list:
        await update.message.reply_text(
            "🤖 **You haven't created any bots yet!**\n\n"
            "Use `/clone <name> <personality> <token>` to create your bot! 🚀\n"
            "Example: `/clone Priya flirty 123456789:ABCdef...`"
        )
        return
    
    bots_list = ["🤖 **Your Configured Bots** 🤖\n\n"]
    
    for i, bot in enumerate(user_bots_list, 1):
        # Check if bot is in memory
        is_configured = bot['bot_token'] in user_bots
        
        status = "🟢 Configured" if is_configured else "🟡 Saved"
        
        bot_info = (
            f"{i}. **{bot['bot_name']}**\n"
            f"   🎭 {bot['personality'].title()} Personality\n"
            f"   📱 Status: {status}\n"
        )
        bots_list.append(bot_info)
    
    response = "\n".join(bots_list)
    response += "\n\n💡 All your bots are saved and ready!"
    
    await update.message.reply_text(response, parse_mode='Markdown')

# --- Hina Bot Commands ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    
    welcome_text = (
        f"Hey there {user.first_name}! 👋\n\n"
        "I'm **Hina** - Bot Creator System! 🤖✨\n\n"
        "🚀 **Instant Bot Setup:**\n"
        "• Create bots with ANY name & personality!\n"
        "• Easy configuration\n"
        "• 100% free forever! 💫\n\n"
        "🤖 **Commands:**\n"
        "• `/clone <name> <personality> <token>` - Setup bot\n"
        "• `/my_bots` - Your created bots\n"
        "• `/help` - Help guide\n\n"
        "💫 **Just one command and your bot is ready!**"
    )
    
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "💖 **Hina Bot Creator** 💖\n\n"
        "🤖 **Bot Creation:**\n"
        "• `/clone <name> <personality> <token>` - Setup bot\n"
        "• `/my_bots` - Your created bots\n\n"
        "💬 **Other Commands:**\n"
        "• `/start` - Welcome message\n"
        "• `/help` - This help\n"
        "• `/couple` - Matchmake in groups\n\n"
        "🎭 **Personality Types:**\n"
        "• `friendly` - Warm and kind 🤗\n"
        "• `playful` - Fun and funny 🎮\n"
        "• `flirty` - Charming and sweet 😘\n\n"
        "🚀 **Quick setup and ready to use!**"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

# --- Message Handler for Hina Bot ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global total_messages_processed
    
    if not update.message or not update.message.text:
        return
        
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    user_message = update.message.text

    if update.effective_chat.type != 'private':
        chat_members[chat_id][user_id] = update.effective_user.full_name

    is_bot_mentioned = (
        update.effective_chat.type != 'private' and 
        ('hina' in user_message.lower() or 'bot' in user_message.lower())
    )

    should_use_ai = (
        global_bot_status and 
        bot_status[chat_id] and 
        (update.effective_chat.type == 'private' or is_bot_mentioned)
    )

    if should_use_ai:
        bot_username = context.bot.username if context.bot.username else ""
        response_text = await get_bot_response(user_message, chat_id, bot_username, should_use_ai, update)
        if response_text:
            await update.message.reply_text(response_text, parse_mode='Markdown')
            total_messages_processed += 1
            return

    total_messages_processed += 1

# --- AI Response Function for Hina Bot ---
async def get_bot_response(user_message: str, chat_id: int, bot_username: str, should_use_ai: bool, update: Update) -> str:
    user_message_lower = user_message.lower()

    # Handle Date/Time Queries
    kolkata_tz = pytz.timezone('Asia/Kolkata')
    if any(pattern in user_message_lower for pattern in ['time kya hai', 'what is the time', 'samay kya hai']):
        current_kolkata_time = datetime.now(kolkata_tz)
        current_time = current_kolkata_time.strftime("%I:%M %p").lstrip('0')
        return f"Abhi {current_time} ho rahe hain! 😉⏰"

    cleaned_user_message = user_message_lower.replace(f"@{bot_username.lower()}", "")
    cleaned_user_message = re.sub(r'hina\s*(ko|ka|se|ne|)\s*', '', cleaned_user_message, flags=re.IGNORECASE)
    cleaned_user_message = re.sub(r'\s+', ' ', cleaned_user_message).strip()

    fallback_responses = {
        "hello": "Hey there! Ready to create some amazing bots? 😉",
        "hi": "Hello! Want to create your personal AI bot? 🚀",
        "how are you": "Absolutely fantastic! Helping people create bots makes me happy! 💫",
    }
    
    static_response = fallback_responses.get(cleaned_user_message, None)
    if static_response:
        return static_response

    if not (should_use_ai or (update.effective_chat and update.effective_chat.type == 'private')):
        return None

    if not DEEPSEEK_API_KEY:
        return "I'm currently upgrading my AI brain! 🧠✨"

    user_first_name = update.effective_user.first_name
    should_use_name = random.random() < 0.4
    
    messages = [
        {"role": "system", "content": HINA_SYSTEM_PROMPT}
    ]
    
    for msg in chat_histories[chat_id]:
        messages.append({"role": msg['role'], "content": msg['content']})
    
    current_msg = f"The user's name is '{user_first_name}'. {user_message}" if should_use_name else user_message
    messages.append({"role": "user", "content": current_msg})

    try:
        async with aiohttp.ClientSession() as session:
            headers = {
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": "deepseek-chat",
                "messages": messages,
                "temperature": 0.8,
                "max_tokens": 500
            }
            
            async with session.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    response_text = data['choices'][0]['message']['content']
                    
                    add_to_history(chat_id, 'user', user_message)
                    add_to_history(chat_id, 'assistant', response_text)
                    
                    return response_text
                else:
                    return "My AI brain is taking a quick break! ☕️"
                    
    except Exception as e:
        return "Oops! Let me try that again! 🔄"

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

# --- Main Function ---
async def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN environment variable is not set.")
        print("❌ ERROR: TELEGRAM_BOT_TOKEN not set!")
        return

    # Initialize user bots
    logger.info("Initializing all user bots...")
    await initialize_all_bots()
    logger.info(f"Initialized {len(user_bots)} user bots")

    # Create main Hina bot application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Add command handlers for Hina bot
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("couple", couple_command))
    application.add_handler(CommandHandler("clone", clone_command))
    application.add_handler(CommandHandler("my_bots", my_bots_command))

    # Add message handler for Hina bot
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Hina Bot starting...")
    
    # Start the main bot with POLLING (webhook issues fixed)
    await application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    asyncio.run(main())
