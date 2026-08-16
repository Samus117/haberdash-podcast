#!/usr/bin/env python3
"""Telegram front-end for summarize.py.

Run this on your own computer and talk to it from your phone via Telegram.
No inbound network exposure is needed - the bot polls Telegram's servers
outward for new messages, so it works from anywhere your phone has signal,
with nothing opened up on your home network.

Usage:
  - Send any message containing one or more video links -> summarizes each.
  - /channel <url> [limit] -> expands a channel/profile URL (default limit 5),
    summarizes each video, and adds a digest across all of them.
  - /whoami -> replies with your Telegram chat ID (for setting the allowlist).
"""

import asyncio
import logging
import os
import re

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from summarize import Anthropic, build_digest, expand_urls, summarize_url

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("video-summarizer-bot")

URL_RE = re.compile(r"https?://\S+")
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "base")
TELEGRAM_MESSAGE_LIMIT = 4000

ALLOWED_CHAT_IDS = {
    int(chat_id)
    for chat_id in os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "").split(",")
    if chat_id.strip()
}

client = Anthropic()  # reads ANTHROPIC_API_KEY from the environment


def is_authorized(update: Update) -> bool:
    if not ALLOWED_CHAT_IDS:
        return True
    return update.effective_chat.id in ALLOWED_CHAT_IDS


async def send_long_message(update: Update, text: str) -> None:
    for i in range(0, len(text), TELEGRAM_MESSAGE_LIMIT):
        await update.message.reply_text(text[i : i + TELEGRAM_MESSAGE_LIMIT])


async def handle_whoami(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f"Your chat ID is {update.effective_chat.id}")


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Send me one or more video links and I'll reply with the main points.\n"
        "Use /channel <url> [limit] to summarize a whole channel/profile plus a digest."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        log.warning("Ignoring message from unauthorized chat %s", update.effective_chat.id)
        return

    urls = URL_RE.findall(update.message.text or "")
    if not urls:
        await update.message.reply_text(
            "Send me a video link, or /channel <url> for a whole channel."
        )
        return

    await update.message.reply_text(
        f"Working on {len(urls)} video(s)... this can take a minute or two each."
    )
    for url in urls:
        await _summarize_and_reply(update, url)


async def handle_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        log.warning("Ignoring message from unauthorized chat %s", update.effective_chat.id)
        return

    if not context.args:
        await update.message.reply_text("Usage: /channel <url> [limit]")
        return

    url = context.args[0]
    limit = 5
    if len(context.args) > 1 and context.args[1].isdigit():
        limit = int(context.args[1])

    await update.message.reply_text(f"Expanding channel (up to {limit} videos)...")
    try:
        video_urls = await asyncio.to_thread(expand_urls, url, limit)
    except Exception as exc:
        await update.message.reply_text(f"Failed to expand that URL: {exc}")
        return

    await update.message.reply_text(f"Found {len(video_urls)} video(s), summarizing...")
    processed: list[tuple[str, str]] = []
    for video_url in video_urls:
        result = await _summarize_and_reply(update, video_url)
        if result:
            processed.append(result)

    if len(processed) > 1:
        digest = await asyncio.to_thread(build_digest, client, processed)
        await send_long_message(
            update, f"Digest across {len(processed)} videos\n\n{digest}"
        )


async def _summarize_and_reply(update: Update, url: str) -> tuple[str, str] | None:
    try:
        result = await asyncio.to_thread(summarize_url, client, url, WHISPER_MODEL)
    except Exception as exc:
        log.exception("Failed on %s", url)
        await update.message.reply_text(f"Failed on {url}: {exc}")
        return None

    if result is None:
        await update.message.reply_text(f"Couldn't get a transcript for {url}")
        return None

    title, points = result
    await send_long_message(update, f"{title}\n\n{points}")
    return title, points


def main() -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    if not ALLOWED_CHAT_IDS:
        log.warning(
            "TELEGRAM_ALLOWED_CHAT_IDS is not set - this bot will respond to ANYONE who "
            "messages it. Message it with /whoami to get your chat ID, then set "
            "TELEGRAM_ALLOWED_CHAT_IDS and restart."
        )

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("help", handle_start))
    app.add_handler(CommandHandler("whoami", handle_whoami))
    app.add_handler(CommandHandler("channel", handle_channel))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("Bot starting - polling Telegram for messages.")
    app.run_polling()


if __name__ == "__main__":
    main()
