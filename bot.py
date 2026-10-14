import os
import asyncio
import logging
from dotenv import load_dotenv
from googletrans import Translator
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# Load environment variables
load_dotenv()

# Configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required")

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Single shared translator instance (googletrans v4 is synchronous)
translator = Translator()

# User preferred languages (in-memory; swap for a DB in production)
user_prefs = {}

# Common languages for quick selection
LANGUAGES = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "ru": "Russian",
    "ar": "Arabic",
    "zh-cn": "Chinese (Simplified)",
    "ja": "Japanese",
    "ko": "Korean",
    "hi": "Hindi",
    "yo": "Yoruba",
    "ig": "Igbo",
    "ha": "Hausa",
    "sw": "Swahili",
}


# ---------- Helper wrappers (run blocking calls in a thread) ----------

def _sync_translate(text: str, dest: str):
    """Blocking translate call — runs inside asyncio.to_thread."""
    return translator.translate(text, dest=dest)


def _sync_detect(text: str):
    """Blocking detect call — runs inside asyncio.to_thread."""
    return translator.detect(text)


# ---------- Command handlers ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a welcome message with usage instructions."""
    welcome_text = (
        "🌍 *Welcome to LOTTOndbot — Your Language Helper!*\n\n"
        "Here's what I can do:\n\n"
        "• *Translate any text* — just send it to me\n"
        "• `/tr <lang> <text>` — translate to a specific language\n"
        "• `/detect <text>` — detect the language\n"
        "• `/setlang <code>` — set your preferred language\n"
        "• `/langs` — list supported languages\n\n"
        "Example: `/tr fr Hello, how are you?`"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)


async def langs_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang_list = "\n".join([f"`{code}` — {name}" for code, name in LANGUAGES.items()])
    await update.message.reply_text(
        f"*Supported Languages:*\n\n{lang_list}\n\n"
        "Use `/setlang <code>` to save your preference.",
        parse_mode="Markdown",
    )


async def setlang_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: `/setlang <language_code>`\nExample: `/setlang es`",
            parse_mode="Markdown",
        )
        return

    lang_code = args[0].lower().strip()
    if lang_code not in LANGUAGES:
        await update.message.reply_text(
            f"❌ Unsupported language code: `{lang_code}`\n"
            "Use `/langs` to see available codes.",
            parse_mode="Markdown",
        )
        return

    user_prefs[update.effective_user.id] = lang_code
    await update.message.reply_text(
        f"✅ Preferred language set to: *{LANGUAGES[lang_code]}* (`{lang_code}`)",
        parse_mode="Markdown",
    )


async def translate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "Usage: `/tr <language_code> <text>`\nExample: `/tr fr Hello world`",
            parse_mode="Markdown",
        )
        return

    target_lang = args[0].lower()
    text_to_translate = " ".join(args[1:])
    await _perform_translation(update, text_to_translate, dest=target_lang)


async def detect_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: `/detect <text>`\nExample: `/detect Bonjour le monde`",
            parse_mode="Markdown",
        )
        return

    await _perform_detection(update, " ".join(args))


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Auto-translate plain text messages to user's preferred language."""
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    if not text or text.startswith("/"):
        return

    target_lang = user_prefs.get(update.effective_user.id, "en")
    await _perform_translation(update, text, dest=target_lang)


# ---------- Core logic ----------

async def _perform_translation(update: Update, text: str, dest: str = "en") -> None:
    """Translate text and reply with detected language + translation."""
    try:
        # Run the blocking googletrans call in a worker thread
        result = await asyncio.to_thread(_sync_translate, text, dest)

        response_parts = [
            f"🔍 *Detected:* `{result.src}`",
            f"🌐 *Translated ({dest}):*",
            f"`{result.text}`",
        ]

        # googletrans v4 doesn't expose pronunciation — skip if missing
        pronunciation = getattr(result, "pronunciation", None)
        if pronunciation and pronunciation != result.text:
            response_parts.append(f"🔊 *Pronunciation:* `{pronunciation}`")

        await update.message.reply_text("\n".join(response_parts), parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Translation error: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Translation failed. Please try again later or check the language code."
        )


async def _perform_detection(update: Update, text: str) -> None:
    """Detect the language of a text."""
    try:
        result = await asyncio.to_thread(_sync_detect, text)
        lang_name = LANGUAGES.get(result.lang, result.lang)
        confidence = f"{result.confidence:.2%}" if result.confidence else "N/A"

        response = (
            f"🔍 *Language Detected:*\n"
            f"• Code: `{result.lang}`\n"
            f"• Name: *{lang_name}*\n"
            f"• Confidence: `{confidence}`"
        )
        await update.message.reply_text(response, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Detection error: {e}", exc_info=True)
        await update.message.reply_text("❌ Language detection failed. Please try again.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)


# ---------- Entry point ----------

def main() -> None:
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("langs", langs_command))
    application.add_handler(CommandHandler("setlang", setlang_command))
    application.add_handler(CommandHandler("tr", translate_command))
    application.add_handler(CommandHandler("detect", detect_command))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    application.add_error_handler(error_handler)

    logger.info("Bot started — polling for updates...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
