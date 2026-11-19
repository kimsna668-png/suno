"""
Suno Music Downloader Telegram Bot (Public, Unlisted & Private Support)
A self-contained, asynchronous Telegram bot built with `python-telegram-bot` (v20+),
`httpx`, `beautifulsoup4`, and `python-dotenv`.
"""
import io
import logging
import os
import re
from typing import Dict, Optional

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Load environment variables from .env file if present
load_dotenv()

# ---------------------------------------------------------------------------
# Configuration & Logging
# ---------------------------------------------------------------------------
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN_HERE").strip()

# Optional credentials for accessing strictly private Suno tracks
SUNO_COOKIE = os.getenv("SUNO_COOKIE", "").strip()
SUNO_TOKEN = os.getenv("SUNO_TOKEN", "").strip()

# Regex patterns for Suno URLs and UUIDs
SUNO_URL_PATTERN = re.compile(
    r"(https?://(?:www\.)?(?:suno\.com|suno\.ai)/(?:song|s)/[a-zA-Z0-9_-]+)"
)
UUID_PATTERN = re.compile(
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.IGNORECASE,
)

# Configure structured logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=getattr(logging, LOG_LEVEL, logging.INFO),
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helper Functions & Metadata Extraction
# ---------------------------------------------------------------------------
def sanitize_filename(name: str) -> str:
    """Removes characters that are invalid in filenames and limits length."""
    cleaned = re.sub(r'[\/*?:"<>|]', "", name).strip()
    return cleaned[:100] if cleaned else "suno_track"

def extract_uuid(text: str) -> Optional[str]:
    """Extracts a standard Suno song UUID from a URL or string if present."""
    match = UUID_PATTERN.search(text)
    return match.group(1) if match else None

def build_suno_headers() -> Dict[str, str]:
    """Builds HTTP request headers, including optional authentication for private tracks."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    if SUNO_COOKIE:
        headers["Cookie"] = SUNO_COOKIE
    if SUNO_TOKEN:
        token = (
            SUNO_TOKEN
            if SUNO_TOKEN.startswith("Bearer ")
            else f"Bearer {SUNO_TOKEN}"
        )
        headers["Authorization"] = token
    return headers

async def fetch_from_suno_api(
    client: httpx.AsyncClient, song_id: str, headers: Dict[str, str]
) -> Optional[Dict[str, Optional[str]]]:
    """
    Attempts to fetch clip metadata from Suno's Studio API endpoints.
    Includes a fix for Suno returning 'forbidden' URLs in the audio_url field.
    """
    api_endpoints = [
        f"https://studio-api.prod.suno.com/api/clip/{song_id}",
        f"https://studio-api.suno.ai/api/clip/{song_id}",
    ]
    for api_url in api_endpoints:
        try:
            resp = await client.get(api_url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                raw_audio_url = data.get("audio_url")
                
                # FIX: Suno sometimes returns a "forbidden" URL string for private tracks.
                # We detect this and fall back to the direct CDN link instead.
                if (
                    raw_audio_url 
                    and "forbidden" not in raw_audio_url.lower() 
                    and raw_audio_url.startswith("http")
                ):
                    audio_url = raw_audio_url
                else:
                    audio_url = f"https://cdn1.suno.ai/{song_id}.mp3"
                    
                title = (data.get("title") or "").strip() or f"Suno Track ({song_id[:8]})"
                image_url = data.get("image_large_url") or data.get("image_url")
                return {
                    "title": title,
                    "audio_url": audio_url,
                    "image_url": image_url,
                }
        except Exception as exc:
            logger.debug("API lookup failed for %s: %s", api_url, exc)
    return None

async def fetch_suno_metadata(url: str) -> Optional[Dict[str, Optional[str]]]:
    """
    Fetches a public, unlisted, or private Suno song's metadata and audio URL.
    """
    headers = build_suno_headers()
    initial_uuid = extract_uuid(url)
    
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            if initial_uuid:
                api_meta = await fetch_from_suno_api(client, initial_uuid, headers)
                if api_meta:
                    return api_meta

            response = await client.get(url, headers=headers)
            final_url = str(response.url)
            resolved_uuid = initial_uuid or extract_uuid(final_url)

            if resolved_uuid and not initial_uuid:
                api_meta = await fetch_from_suno_api(client, resolved_uuid, headers)
                if api_meta:
                    return api_meta

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
                og_audio = soup.find("meta", property="og:audio")
                og_title = soup.find("meta", property="og:title")
                og_image = soup.find("meta", property="og:image")

                audio_url = (
                    og_audio["content"].strip()
                    if og_audio and og_audio.get("content")
                    else None
                )
                raw_title = (
                    og_title["content"].strip()
                    if og_title and og_title.get("content")
                    else ""
                )
                clean_title = re.sub(
                    r"\s*\|\s*Suno\s*$", "", raw_title, flags=re.IGNORECASE
                ).strip()
                image_url = (
                    og_image["content"].strip()
                    if og_image and og_image.get("content")
                    else None
                )

                if audio_url:
                    return {
                        "title": clean_title or "Suno AI Track",
                        "audio_url": audio_url,
                        "image_url": image_url,
                    }

            if resolved_uuid:
                logger.info("Using direct CDN fallback for UUID: %s", resolved_uuid)
                return {
                    "title": f"Suno Track ({resolved_uuid[:8]})",
                    "audio_url": f"https://cdn1.suno.ai/{resolved_uuid}.mp3",
                    "image_url": f"https://cdn2.suno.ai/image_{resolved_uuid}.jpeg",
                }
                
    except httpx.RequestError as exc:
        logger.error("Network error while fetching Suno page (%s): %s", url, exc)
        if initial_uuid:
            return {
                "title": f"Suno Track ({initial_uuid[:8]})",
                "audio_url": f"https://cdn1.suno.ai/{initial_uuid}.mp3",
                "image_url": f"https://cdn2.suno.ai/image_{initial_uuid}.jpeg",
            }
    except Exception as exc:
        logger.exception("Unexpected error parsing Suno page (%s): %s", url, exc)
        
    return None

async def download_binary(url: str) -> Optional[io.BytesIO]:
    """
    Streams a binary file (audio or cover image) into an in-memory BytesIO buffer.
    """
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                
                buffer = io.BytesIO()
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    buffer.write(chunk)
                    
                buffer.seek(0)
                return buffer
                
    except Exception as exc:
        logger.error("Failed to download binary from %s: %s", url, exc)
        return None

# ---------------------------------------------------------------------------
# Telegram Command & Message Handlers
# ---------------------------------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /start command."""
    if not update.message:
        return
        
    welcome_text = (
        "👋 សូមស្វាគមន៍មកកាន់ Suno Music Downloader Bot!\n\n"
        "ផ្ញើតំណភ្ជាប់ចម្រៀង Suno ណាមួយមកខ្ញុំ (ទាំង Public, Unlisted ឬ Private)\n"
        "ឧទាហរណ៍៖ `https://suno.com/song/...` ឬ `https://suno.com/s/...`\n"
        "នោះខ្ញុំនឹងទាញយកឯកសារ MP3 ជូនអ្នកភ្លាមៗ។"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /help command."""
    if not update.message:
        return
        
    help_text = (
        "ℹ️ របៀបប្រើប្រាស់ Bot៖\n"
        "1. ចម្លងតំណភ្ជាប់ (Link) ចម្រៀងពី Suno (Public ឬ Private)។\n"
        "2. ផ្ញើតំណភ្ជាប់នោះចូលក្នុងប្រអប់សារនេះ។\n\n"
        "🔐 សម្រាប់ចម្រៀង Private តឹងរ៉ឹង៖\n"
        "Bot អាចទាញយកចម្រៀង Unlisted/Private ដោយស្វ័យប្រវត្តិតាមរយៈ Link UUID "
        "ឬប្រើ `SUNO_COOKIE` / `SUNO_TOKEN` នៅក្នុងឯកសារ `.env`។"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Scans incoming text messages for Suno URLs and sends the downloaded audio."""
    if not update.message or not update.message.text:
        return
        
    match = SUNO_URL_PATTERN.search(update.message.text)
    if not match:
        await update.message.reply_text(
            "⚠️ សូមផ្ញើតំណភ្ជាប់ចម្រៀង Suno ដែលត្រឹមត្រូវ (ឧទាហរណ៍៖ `https://suno.com/song/...`)។",
            parse_mode="Markdown",
        )
        return

    suno_url = match.group(1)
    status_msg = await update.message.reply_text("🔍 កំពុងស្វែងរកព័ត៌មានចម្រៀងពី Suno...")
    
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_VOICE
    )

    metadata = await fetch_suno_metadata(suno_url)
    if not metadata or not metadata.get("audio_url"):
        await status_msg.edit_text(
            "❌ មិនអាចទាញយកចម្រៀងពីតំណភ្ជាប់នេះបានទេ។ "
            "សូមពិនិត្យមើលតំណភ្ជាប់ ឬកំណត់ `SUNO_COOKIE` / `SUNO_TOKEN` ក្នុង `.env` សម្រាប់ចម្រៀង Private។",
            parse_mode="Markdown",
        )
        return

    title = metadata["title"] or "Suno AI Track"
    audio_url = metadata["audio_url"]
    image_url = metadata.get("image_url")

    # Smart Size Check: Prevents RAM overload and handles Telegram's 50MB limit
    file_size_mb = 0
    try:
        async with httpx.AsyncClient(timeout=10.0) as head_client:
            head_resp = await head_client.head(audio_url)
            content_length = head_resp.headers.get("Content-Length")
            if content_length:
                file_size_mb = int(content_length) / (1024 * 1024)
    except Exception:
        pass

    if file_size_mb > 50:
        await status_msg.edit_text(
            f"⚠️ ឯកសារនេះមានទំហំធំជាង 50MB ({file_size_mb:.1f} MB)។\n"
            f"Telegram Bot មិនអាចផ្ញើឯកសារធំជាងនេះបានទេ (កំណត់ដោយ Telegram)។\n\n"
            f"🔗 **តំណភ្ជាប់ទាញយកផ្ទាល់ (Unlimited Download):**\n{audio_url}",
            parse_mode="Markdown",
        )
        return

    await status_msg.edit_text(f"⬇️ កំពុងទាញយកបទ *{title}*...", parse_mode="Markdown")

    audio_buffer = await download_binary(audio_url)
    if not audio_buffer:
        await status_msg.edit_text(
            "❌ បរាជ័យក្នុងការទាញយកឯកសារសំឡេង (ឯកសារអាចមានទំហំលើសពី 50MB ឬមិនអាចចូលប្រើបាន)។"
        )
        return

    thumb_buffer = None
    if image_url:
        thumb_buffer = await download_binary(image_url)

    filename = f"{sanitize_filename(title)}.mp3"
    
    try:
        await update.message.reply_audio(
            audio=audio_buffer,
            filename=filename,
            title=title,
            performer="Suno AI",
            thumbnail=thumb_buffer,
            caption=f"🎵 *{title}*\n🔗 [តំណភ្ជាប់ដើម]({suno_url})",
            parse_mode="Markdown",
        )
        await status_msg.delete()
    except Exception as exc:
        logger.error("Error sending audio via Telegram: %s", exc)
        await status_msg.edit_text("❌ មានបញ្ហាក្នុងការផ្ញើឯកសារសំឡេងទៅកាន់ Telegram។")

# ---------------------------------------------------------------------------
# Application Entry Point
# ---------------------------------------------------------------------------
def main() -> None:
    """Initializes and starts the Telegram bot using long polling."""
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        raise ValueError(
            "សូមកំណត់ TELEGRAM_BOT_TOKEN របស់អ្នកនៅក្នុងឯកសារ .env ជាមុនសិន!"
        )

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    logger.info("Bot is running and polling for updates...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
