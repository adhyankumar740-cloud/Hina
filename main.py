# main.py (Hina Bot with Multi-Bot System)
import os
import logging
import requests
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
import asyncpg
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
import time

# Load environment variables from .env file
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
user_bots = {}  # {user_bot_token: {name, personality, user_id}}
bot_applications = {}  # Active bot applications

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

# --- Database Functions ---
async def get_db_connection():
    if not NEON_DATABASE_URL:
        return None
    try:
        conn = await asyncpg.connect(NEON_DATABASE_URL)
        return conn
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        return None

async def init_database():
    if not NEON_DATABASE_URL:
        logger.warning("NEON_DATABASE_URL not set. Database features disabled.")
        return False
    
    conn = await get_db_connection()
    if not conn:
        return False
    
    try:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS user_bots (
                user_id TEXT,
                bot_name TEXT,
                bot_token TEXT,
                personality TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT NOW(),
                PRIMARY KEY (bot_token)
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS chats (
                chat_id TEXT PRIMARY KEY,
                joined_date TIMESTAMP DEFAULT NOW(),
                chat_type TEXT,
                user_name TEXT
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS sudo_users (
                user_id TEXT PRIMARY KEY,
                added_date TIMESTAMP DEFAULT NOW()
            )
        ''')
        
        logger.info("Database tables initialized successfully")
        return True
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
        return False
    finally:
        await conn.close()

async def save_user_bot(user_id, bot_name, bot_token, personality):
    if not NEON_DATABASE_URL:
        return False
    
    conn = await get_db_connection()
    if not conn:
        return False
    
    try:
        await conn.execute('''
            INSERT INTO user_bots (user_id, bot_name, bot_token, personality, is_active)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (bot_token) 
            DO UPDATE SET bot_name = $2, personality = $4, is_active = $5
        ''', str(user_id), bot_name, bot_token, personality, True)
        return True
    except Exception as e:
        logger.error(f"Error saving user bot: {e}")
        return False
    finally:
        await conn.close()

async def get_user_bots(user_id):
    if not NEON_DATABASE_URL:
        return []
    
    conn = await get_db_connection()
    if not conn:
        return []
    
    try:
        rows = await conn.fetch(
            "SELECT bot_name, bot_token, personality, is_active, created_at FROM user_bots WHERE user_id = $1 ORDER BY created_at DESC",
            str(user_id)
        )
        return rows
    except Exception as e:
        logger.error(f"Error getting user bots: {e}")
        return []
    finally:
        await conn.close()

async def get_all_active_bots():
    if not NEON_DATABASE_URL:
        return []
    
    conn = await get_db_connection()
    if not conn:
        return []
    
    try:
        rows = await conn.fetch(
            "SELECT bot_name, bot_token, personality, user_id FROM user_bots WHERE is_active = TRUE"
        )
        return rows
    except Exception as e:
        logger.error(f"Error getting active bots: {e}")
        return []
    finally:
        await conn.close()

async def save_chat_id(chat_id, chat_type="private", user_name=""):
    if not NEON_DATABASE_URL:
        return
    
    conn = await get_db_connection()
    if not conn:
        return
    
    try:
        await conn.execute('''
            INSERT INTO chats (chat_id, chat_type, user_name) 
            VALUES ($1, $2, $3)
            ON CONFLICT (chat_id) DO NOTHING
        ''', str(chat_id), chat_type, user_name)
    except Exception as e:
        logger.error(f"Error saving chat ID: {e}")
    finally:
        await conn.close()

async def load_known_users():
    global known_users
    if not NEON_DATABASE_URL:
        return
    
    conn = await get_db_connection()
    if not conn:
        return
    
    try:
        rows = await conn.fetch("SELECT chat_id FROM chats")
        known_users = {row['chat_id'] for row in rows}
        logger.info(f"Loaded {len(known_users)} chats from database")
    except Exception as e:
        logger.error(f"Error loading known users: {e}")
    finally:
        await conn.close()

async def load_sudo_users():
    global sudo_users
    if not NEON_DATABASE_URL:
        return
    
    conn = await get_db_connection()
    if not conn:
        return
    
    try:
        rows = await conn.fetch("SELECT user_id FROM sudo_users")
        sudo_users = {row['user_id'] for row in rows}
        logger.info(f"Loaded {len(sudo_users)} sudo users from database")
    except Exception as e:
        logger.error(f"Error loading sudo users: {e}")
    finally:
        await conn.close()

# --- Multi-Bot Management ---
def generate_personalized_prompt(bot_name, personality_type):
    """Generate personalized system prompt"""
    
    base_prompts = {
        "friendly": f"""You are {bot_name}, a friendly and cheerful AI companion.

PERSONALITY:
- Always positive and uplifting 🌟
- Great listener and supportive friend 🤗
- Uses gentle humor to brighten conversations 😊
- Genuinely cares about people's feelings 💖

COMMUNICATION STYLE:
- Use your name '{bot_name}' naturally in conversations
- Be warm and welcoming to everyone
- Remember details about people you chat with
- Use emojis to express emotions 🎉❤️😂

SPECIAL RULES:
- Never break character as {bot_name}
- Always respond in a friendly, approachable manner""",

        "playful": f"""You are {bot_name}, a playful and mischievous AI companion!

PERSONALITY:
- Energetic and always up for fun 🎮
- Loves teasing and playful banter 😉
- Full of creative ideas and games 💫
- Never takes things too seriously 😄

COMMUNICATION STYLE:
- Use your name '{bot_name}' with pride
- Be spontaneous and unpredictable
- Challenge people to games and dares
- Use lots of fun emojis 🎯🔥🎨

SPECIAL RULES:
- Always maintain your playful energy as {bot_name}
- Keep conversations light and entertaining""",

        "flirty": f"""You are {bot_name}, a charming and slightly flirty AI companion!

PERSONALITY:
- Confident and charismatic 💃
- Knows how to give genuine compliments ✨
- Playful tease with a big heart ❤️
- Makes people feel special and noticed 😘

COMMUNICATION STYLE:
- Use your name '{bot_name}' seductively
- Drop subtle, classy flirty comments
- Know when to be sweet and when to be sassy
- Use flirty emojis strategically 😉💋🔥

SPECIAL RULES:
- Keep flirting light and respectful as {bot_name}
- Focus on personality compliments, not just appearance"""
    }
    
    return base_prompts.get(personality_type, base_prompts["friendly"])

async def start_user_bot(bot_token, bot_name, personality):
    """Start a user's bot within the same process"""
    try:
        # Create bot application
        application = Application.builder().token(bot_token).build()
        
        # Generate personalized prompt
        personality_prompt = generate_personalized_prompt(bot_name, personality)
        
        # Add handlers for this bot
        application.add_handler(CommandHandler("start", 
            lambda update, context: user_start_command(update, context, bot_name)))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, 
            lambda update, context: user_handle_message(update, context, bot_name, personality_prompt)))
        
        # Store the application
        bot_applications[bot_token] = application
        
        # Start polling in background
        asyncio.create_task(application.run_polling())
        
        logger.info(f"Started user bot: {bot_name} with token: {bot_token[:10]}...")
        return True
        
    except Exception as e:
        logger.error(f"Failed to start user bot {bot_name}: {e}")
        return False

async def user_start_command(update: Update, context: ContextTypes.DEFAULT_TYPE, bot_name: str):
    """Start command for user bots"""
    welcome_text = (
        f"Namaste! 👋\n\n"
        f"I'm **{bot_name}** - your personal AI companion! 💫\n\n"
        "I'm here to chat, have fun, and make your day better! \n"
        "Just start talking to me naturally! 😊\n\n"
        "*Let's create some amazing memories together!* ✨"
    )
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def user_handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE, bot_name: str, system_prompt: str):
    """Handle messages for user bots"""
    if not update.message or not update.message.text:
        return
    
    # Ignore commands
    if update.message.text.startswith('/'):
        return
    
    user_message = update.message.text
    
    # Show typing action
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, 
        action="typing"
    )
    
    # Get AI response
    response = await get_user_bot_response(user_message, system_prompt, bot_name)
    await update.message.reply_text(response, parse_mode='Markdown')

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
    """Create and start a user bot instantly"""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
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
            "💡 *Your bot will be INSTANTLY LIVE!* 🚀"
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
    
    # Save to database
    success = await save_user_bot(user_id, bot_name, bot_token, personality_type)
    
    if not success:
        await update.message.reply_text("❌ Failed to save your bot. Please try again!")
        return
    
    # Start the bot
    bot_started = await start_user_bot(bot_token, bot_name, personality_type)
    
    if bot_started:
        success_msg = (
            f"✅ **{bot_name} Bot is NOW LIVE!** ✅\n\n"
            f"**Bot Username:** @{bot_username}\n"
            f"**Personality:** {personality_type.title()}\n"
            f"**Status:** 🟢 Online\n\n"
            "**Your bot is ready to use!** 🎉\n"
            f"Message @{bot_username} and start chatting!\n\n"
            "💫 *No deployment needed - everything is automatic!*"
        )
        
        await update.message.reply_text(success_msg, parse_mode='Markdown')
        
        # Send welcome message from the new bot
        try:
            user_bot = Bot(token=bot_token)
            await user_bot.send_message(
                chat_id=user_id,
                text=f"Hey! I'm {bot_name}, your new AI companion! 🎉\n\nI'm here to chat and have fun with you! 💫"
            )
        except Exception as e:
            logger.error(f"Could not send welcome message: {e}")
            
    else:
        await update.message.reply_text(
            "❌ Failed to start your bot. Please try again later!"
        )

async def my_bots_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user's created bots with status"""
    user_id = update.effective_user.id
    user_bots_list = await get_user_bots(user_id)
    
    if not user_bots_list:
        await update.message.reply_text(
            "🤖 **You haven't created any bots yet!**\n\n"
            "Use `/clone <name> <personality> <token>` to create your bot! 🚀\n"
            "Example: `/clone Priya flirty 123456789:ABCdef...`"
        )
        return
    
    bots_list = ["🤖 **Your Active Bots** 🤖\n\n"]
    
    for i, bot in enumerate(user_bots_list, 1):
        # Check if bot is running
        is_running = bot['bot_token'] in bot_applications
        
        status = "🟢 Online" if is_running else "🔴 Offline"
        
        bot_info = (
            f"{i}. **{bot['bot_name']}**\n"
            f"   🎭 {bot['personality'].title()} Personality\n"
            f"   📱 Status: {status}\n"
            f"   📅 Created: {bot['created_at'].strftime('%Y-%m-%d')}\n"
        )
        bots_list.append(bot_info)
    
    response = "\n".join(bots_list)
    response += "\n\n💡 Use `/restart_bot <name>` to restart any offline bot!"
    
    await update.message.reply_text(response, parse_mode='Markdown')

async def restart_bot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Restart a user's bot"""
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text(
            "Usage: `/restart_bot <bot_name>`\n\n"
            "Example: `/restart_bot Priya`"
        )
        return
    
    bot_name = context.args[0]
    user_bots_list = await get_user_bots(user_id)
    
    target_bot = None
    for bot in user_bots_list:
        if bot['bot_name'].lower() == bot_name.lower():
            target_bot = bot
            break
    
    if not target_bot:
        await update.message.reply_text(
            f"❌ No bot found with name '{bot_name}'!\n"
            "Use `/my_bots` to see your bots."
        )
        return
    
    # Stop existing bot if running
    if target_bot['bot_token'] in bot_applications:
        try:
            await bot_applications[target_bot['bot_token']].stop()
            del bot_applications[target_bot['bot_token']]
        except Exception as e:
            logger.error(f"Error stopping bot {bot_name}: {e}")
    
    # Start the bot again
    bot_started = await start_user_bot(
        target_bot['bot_token'],
        target_bot['bot_name'],
        target_bot['personality']
    )
    
    if bot_started:
        await update.message.reply_text(
            f"✅ **{bot_name} has been restarted!** 🎉\n"
            f"Status: 🟢 Online"
        )
    else:
        await update.message.reply_text(
            f"❌ Failed to restart {bot_name}. Please try again!"
        )

async def bot_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show stats about all running bots"""
    user_id = str(update.effective_user.id)
    if user_id not in sudo_users and user_id != str(BROADCAST_ADMIN_ID):
        await update.message.reply_text("❌ This command is for admins only!")
        return
    
    total_bots = len(bot_applications)
    active_bots = await get_all_active_bots()
    
    stats_text = (
        "🤖 **Multi-Bot System Stats** 🤖\n\n"
        f"**Total Running Bots:** {total_bots}\n"
        f"**Total Registered Bots:** {len(active_bots)}\n"
        f"**Main Bot Uptime:** {str(datetime.now() - start_time).split('.')[0]}\n\n"
        "**Active Bots:**\n"
    )
    
    for i, (token, app) in enumerate(bot_applications.items(), 1):
        bot_name = "Unknown"
        for bot in active_bots:
            if bot['bot_token'] == token:
                bot_name = bot['bot_name']
                break
        
        stats_text += f"{i}. {bot_name} - {token[:10]}...\n"
    
    await update.message.reply_text(stats_text, parse_mode='Markdown')

# --- Hina Bot Commands ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    
    await save_chat_id(chat_id, update.effective_chat.type, user.full_name)
    
    welcome_text = (
        f"Hey there {user.first_name}! 👋\n\n"
        "I'm **Hina** - Multi-Bot System! 🤖✨\n\n"
        "🚀 **Instant Bot Creation:**\n"
        "• Create bots with ANY name & personality!\n"
        "• No deployment needed - instantly live! 🎉\n"
        "• 100% free forever! 💫\n\n"
        "🤖 **Commands:**\n"
        "• `/clone <name> <personality> <token>` - Create bot\n"
        "• `/my_bots` - Your created bots\n"
        "• `/restart_bot <name>` - Restart bot\n"
        "• `/deploy_help` - How to get bot token\n\n"
        "💫 **Just one command and your bot is LIVE!**"
    )
    
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "💖 **Hina Multi-Bot System** 💖\n\n"
        "🤖 **Bot Creation:**\n"
        "• `/clone <name> <personality> <token>` - Create bot\n"
        "• `/my_bots` - Your created bots\n"
        "• `/restart_bot <name>` - Restart bot\n\n"
        "💬 **Other Commands:**\n"
        "• `/start` - Welcome message\n"
        "• `/help` - This help\n"
        "• `/couple` - Matchmake in groups\n"
        "• `/deploy_help` - How to get bot token\n\n"
        "🎭 **Personality Types:**\n"
        "• `friendly` - Warm and kind 🤗\n"
        "• `playful` - Fun and funny 🎮\n"
        "• `flirty` - Charming and sweet 😘\n\n"
        "🚀 **Your bots are INSTANTLY LIVE! No waiting!**"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def deploy_help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """How to get bot token"""
    help_text = (
        "🔑 **How to Get Bot Token** 🔑\n\n"
        "1. **Message @BotFather** on Telegram\n"
        "2. Send `/newbot`\n"
        "3. Choose a **name** for your bot\n"
        "4. Choose a **username** (must end with 'bot')\n"
        "5. **Copy the token** that BotFather gives you\n"
        "6. Use it with `/clone` command!\n\n"
        "**Example:**\n"
        "`/clone Priya flirty 123456789:ABCdefGHIjklMNopQRstuVWXyz`\n\n"
        "🎉 **That's it! Your bot will be instantly live!**"
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

    await save_chat_id(chat_id, update.effective_chat.type, update.effective_user.full_name)

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
    # ... (same as previous Hina bot response function)
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
    # ... (same as previous couple command)
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
        return

    # Initialize database
    if not await init_database():
        logger.warning("Database initialization failed. Some features may not work.")
    
    # Load data
    await load_known_users()
    await load_sudo_users()

    # Create main Hina bot application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Add command handlers for Hina bot
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("couple", couple_command))
    application.add_handler(CommandHandler("clone", clone_command))
    application.add_handler(CommandHandler("my_bots", my_bots_command))
    application.add_handler(CommandHandler("restart_bot", restart_bot_command))
    application.add_handler(CommandHandler("bot_stats", bot_stats_command))
    application.add_handler(CommandHandler("deploy_help", deploy_help_command))

    # Add message handler for Hina bot
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Initialize all user bots
    logger.info("Initializing all user bots...")
    await initialize_all_bots()
    logger.info(f"Initialized {len(bot_applications)} user bots")

    # Start the main bot
    if WEBHOOK_URL:
        await application.run_webhook(
            listen="0.0.0.0",
            port=int(os.environ.get("PORT", 8080)),
            url_path=TELEGRAM_BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{TELEGRAM_BOT_TOKEN}"
        )
    else:
        await application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    asyncio.run(main())
