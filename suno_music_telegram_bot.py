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
    Attempts to fetch clip metadata (works for both public and authenticated private tracks)
    from Suno's Studio API endpoints.
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
                audio_url = (
                    data.get("audio_url") or f"https://cdn1.suno.ai/{song_id}.mp3"
                )
                title = (data.get("title") or "").strip() or f"Suno Track ({song_id[:8]})"
                image_url = data.get("image_large_url") or data.get("image_url")
                return {
                    "title": title,
                    "audio_url": audio_url,
                    "image_url": image_url,
                }
        except Exception a
