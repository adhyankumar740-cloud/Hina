# main.py - Hina Bot (Fixed Event Loop)
import os
import logging
import asyncio
import uuid
import pytz
import traceback
import random
from collections import defaultdict
from datetime import datetime
import psutil
import re
import aiohttp
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

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

# --- User Bot Storage ---
user_bots_storage = {}

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

# --- Fallback Responses ---
fallback_responses = {
    "hello": "Hey there! Missed me? 😉",
    "hi": "Well hello there! 💫",
    "how are you": "Absolutely fabulous now that you're here! 😘",
    "who are you": "I'm Hina! Your favorite playful companion! 🌟",
}

# --- User Bot Management ---
def generate_personalized_prompt(bot_name, personality_type):
    """Generate personalized system prompt"""
    
    base_prompts = {
        "friendly": f"""You are {bot_name}, a friendly and cheerful AI companion. Always be warm, supportive and use emojis! 🤗""",
        "playful": f"""You are {bot_name}, a playful and mischievous AI companion! Be fun, energetic and use lots of emojis! 🎮""",
        "flirty": f"""You are {bot_name}, a charming and slightly flirty AI companion! Be classy, charming and use flirty emojis! 😘"""
    }
    
    return base_prompts.get(personality_type, base_prompts["friendly"])

async def save_user_bot(user_id, bot_name, bot_token, personality):
    """Save user bot to storage"""
    key = f"{user_id}_{bot_name}"
    user_bots_storage[key] = {
        'user_id': user_id,
        'bot_name': bot_name, 
        'bot_token': bot_token,
        'personality': personality
    }
    return True

async def get_user_bots(user_id):
    """Get user's bots"""
    user_bots = []
    for key, bot_data in user_bots_storage.items():
        if str(user_id) in key:
            user_bots.append(bot_data)
    return user_bots

# --- Clone Command ---
async def clone_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Create a user bot"""
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
            "💡 *I'll save your bot configuration!* 🚀"
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
        from telegram import Bot
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
    
    if success:
        # Generate bot code
        personality_prompt = generate_personalized_prompt(bot_name, personality_type)
        bot_code = generate_bot_code(bot_name, personality_prompt)
        
        success_msg = (
            f"✅ **{bot_name} Bot Configuration Saved!** ✅\n\n"
            f"**Bot Username:** @{bot_username}\n"
            f"**Personality:** {personality_type.title()}\n\n"
            "**Next Steps:**\n"
            "1. I'm sending you the Python code\n"
            "2. Deploy to Render.com (free)\n"
            "3. Add environment variables\n"
            "4. Your bot will be live! 🚀\n\n"
            "Use `/deploy_help` for detailed guide!"
        )
        
        await update.message.reply_text(success_msg, parse_mode='Markdown')
        
        # Send the code as file
        code_filename = f"{bot_name}_bot.py"
        await update.message.reply_document(
            document=bot_code.encode('utf-8'),
            filename=code_filename,
            caption=f"Here's your {bot_name} bot code! 💻"
        )
        
    else:
        await update.message.reply_text("❌ Failed to save your bot. Please try again!")

def generate_bot_code(bot_name, personality_prompt):
    """Generate bot code for user"""
    
    return f'''# {bot_name} Bot - Your Personal AI Companion
import os
import logging
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import aiohttp

# Configuration
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# {bot_name}'s Personality
SYSTEM_PROMPT = """{personality_prompt}"""

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        f"Namaste! 👋\\n\\n"
        f"I'm **{bot_name}** - your personal AI companion! 💫\\n\\n"
        "I'm here to chat, have fun, and make your day better! \\n"
        "Just start talking to me naturally! 😊\\n\\n"
        "*Let's create some amazing memories together!* ✨"
    )
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def get_ai_response(user_message: str) -> str:
    if not DEEPSEEK_API_KEY:
        return "🔧 I'm getting an upgrade! Please try again later."
    
    try:
        async with aiohttp.ClientSession() as session:
            headers = {{
                "Authorization": f"Bearer {{DEEPSEEK_API_KEY}}",
                "Content-Type": "application/json"
            }}
            
            messages = [
                {{"role": "system", "content": SYSTEM_PROMPT}},
                {{"role": "user", "content": user_message}}
            ]
            
            payload = {{
                "model": "deepseek-chat",
                "messages": messages,
                "temperature": 0.8,
                "max_tokens": 500
            }}
            
            async with session.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    return data['choices'][0]['message']['content']
                else:
                    return "🤔 I'm having trouble thinking right now. Try again later!"
                        
    except Exception as e:
        logger.error(f"API Error: {{e}}")
        return "😴 I'm feeling a bit sleepy... Try again in a moment!"

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    
    if update.message.text.startswith('/'):
        return
    
    user_message = update.message.text
    
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, 
        action="typing"
    )
    
    response = await get_ai_response(user_message)
    await update.message.reply_text(response, parse_mode='Markdown')

def main():
    if not BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set!")
        return
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print(f"🚀 {bot_name} Bot is starting...")
    application.run_polling()

if __name__ == "__main__":
    main()
'''

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
    
    bots_list = ["🤖 **Your Created Bots** 🤖\n\n"]
    
    for i, bot in enumerate(user_bots_list, 1):
        bot_info = (
            f"{i}. **{bot['bot_name']}**\n"
            f"   🎭 {bot['personality'].title()} Personality\n"
            f"   🔑 Token: `{bot['bot_token'][:10]}...`\n"
        )
        bots_list.append(bot_info)
    
    response = "\n".join(bots_list)
    response += "\n\n💡 Use `/deploy_help` for deployment guide!"
    
    await update.message.reply_text(response, parse_mode='Markdown')

async def deploy_help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deployment help"""
    help_text = (
        "🚀 **Deployment Guide** 🚀\n\n"
        
        "1. **Get Free Resources:**\n"
        "• Bot Token: From @BotFather\n"
        "• API Key: https://openrouter.ai/ (free)\n"
        "• Hosting: https://render.com (free)\n\n"
        
        "2. **Deploy to Render.com:**\n"
        "• Create new Web Service\n"
        "• Connect your GitHub repo\n"
        "• Build Command: `pip install -r requirements.txt`\n"
        "• Start Command: `python your_bot_file.py`\n"
        "• Add environment variables\n\n"
        
        "3. **Environment Variables:**\n"
        "• `TELEGRAM_BOT_TOKEN`: your bot token\n"
        "• `DEEPSEEK_API_KEY`: your DeepSeek API key\n\n"
        
        "🎉 **Your bot will be live in minutes!**"
    )
    
    await update.message.reply_text(help_text, parse_mode='Markdown')

# --- Hina Bot Commands ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    welcome_text = (
        f"Hey there {user.first_name}! 👋\n\n"
        "I'm **Hina** - Bot Creator! 🤖✨\n\n"
        "🚀 **What I can do:**\n"
        "• Create personalized AI bots for you!\n"
        "• Give you complete deployable code\n"
        "• Help you deploy for FREE! 💫\n\n"
        "🤖 **Commands:**\n"
        "• `/clone <name> <personality> <token>` - Create bot\n"
        "• `/my_bots` - Your created bots\n"
        "• `/deploy_help` - Deployment guide\n"
        "• `/help` - All commands\n\n"
        "Let's create something amazing! 🎉"
    )
    
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "💖 **Hina Bot Commands** 💖\n\n"
        "🤖 **Bot Creation:**\n"
        "• `/clone <name> <personality> <token>` - Create bot\n"
        "• `/my_bots` - Your created bots\n"
        "• `/deploy_help` - Deployment guide\n\n"
        "💬 **Chat Commands:**\n"
        "• `/start` - Welcome message\n"
        "• `/help` - This help\n"
        "• `/couple` - Matchmake in groups\n\n"
        "🎭 **Personality Types:**\n"
        "• `friendly` - Warm and kind 🤗\n"
        "• `playful` - Fun and funny 🎮\n"
        "• `flirty` - Charming and sweet 😘\n\n"
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

# --- AI Response Function ---
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

# --- Main Function ---
def main():
    """Main function using synchronous approach"""
    if not TELEGRAM_BOT_TOKEN:
        print("❌ ERROR: TELEGRAM_BOT_TOKEN not set!")
        print("💡 Please set TELEGRAM_BOT_TOKEN in Render environment variables")
        return

    print("🤖 Hina Bot starting...")
    
    # Create application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("couple", couple_command))
    application.add_handler(CommandHandler("clone", clone_command))
    application.add_handler(CommandHandler("my_bots", my_bots_command))
    application.add_handler(CommandHandler("deploy_help", deploy_help_command))

    # Add message handler
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🚀 Bot is running with polling...")
    
    # Start polling (synchronous)
    application.run_polling()

if __name__ == "__main__":
    main()
