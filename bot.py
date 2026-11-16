"""
Azaam Video Downloader Telegram Bot
- Accepts a video page URL and downloads supported, non-DRM media with yt-dlp.
- Sends the result back to the requesting Telegram user.
- Configure BOT_TOKEN as an environment variable. Never hard-code or share it.
"""

import asyncio
import logging
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "49"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("azaam-video-bot")

URL_RE = re.compile(r"https?://[^\s<>()]+")


def valid_http_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def download_video(url: str, folder: str) -> Path:
    # yt-dlp supports many public video sites. DRM-protected streams and
    # sites requiring unsupported authentication are not supported.
    options = {
        "outtmpl": str(Path(folder) / "%(title).100B-%(id)s.%(ext)s"),
        "format": f"best[filesize<={MAX_UPLOAD_BYTES}]/best[filesize_approx<={MAX_UPLOAD_BYTES}]/best",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "restrictfilenames": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 25,
        "retries": 2,
        "fragment_retries": 2,
        "max_filesize": MAX_UPLOAD_BYTES,
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
        if info is None:
            raise RuntimeError("Video lama helin.")
        filename = ydl.prepare_filename(info)
        candidate = Path(filename)
        if not candidate.exists():
            mp4_candidate = candidate.with_suffix(".mp4")
            if mp4_candidate.exists():
                candidate = mp4_candidate
            else:
                files = list(Path(folder).glob("*"))
                if not files:
                    raise RuntimeError("Faylka video-ga lama helin.")
                candidate = max(files, key=lambda p: p.stat().st_mtime)
        return candidate


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Salaan! Ii soo dir link video oo website taageersan ah. "
        "Waxaan isku dayayaa inaan kuu soo dejiyo MP4."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Sida loo isticmaalo:\n"
        "1. Nuqul ka samee link-ga bogga video-ga.\n"
        "2. Halkan iigu soo dir.\n"
        "3. Sug inta aan soo dejinayo.\n\n"
        "DRM, link-yo gaar loo xidhay, iyo bogag u baahan login lama taageero. "
        "Kaliya soo dejiso wax aad xaq u leedahay inaad kaydsato."
    )


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message or not message.text:
        return

    match = URL_RE.search(message.text.strip())
    if not match:
        await message.reply_text("Fadlan ii soo dir link HTTP ama HTTPS ah.")
        return

    url = match.group(0).rstrip(".,!?)]}")
    if not valid_http_url(url):
        await message.reply_text("Link-ga sax ma aha. Hubi oo mar kale soo dir.")
        return

    status = await message.reply_text("Link-ga waan hubinayaa, sug fadlan...")
    await context.bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.TYPING)

    try:
        with tempfile.TemporaryDirectory(prefix="azaam_dl_") as temp_dir:
            # Run blocking yt-dlp work away from the async event loop.
            file_path = await asyncio.to_thread(download_video, url, temp_dir)
            size = file_path.stat().st_size

            if size > MAX_UPLOAD_BYTES:
                await status.edit_text(
                    f"Video-gu wuxuu ka weyn yahay xadka {MAX_UPLOAD_MB} MB ee bot-kan."
                )
                return

            await status.edit_text("Waa la helay. Hadda Telegram ayaan kuu soo dirayaa...")
            await context.bot.send_chat_action(
                chat_id=message.chat_id, action=ChatAction.UPLOAD_VIDEO
            )

            caption = file_path.stem[:900]
            with file_path.open("rb") as media:
                if file_path.suffix.lower() in (".mp4", ".m4v", ".mov", ".webm"):
                    await message.reply_video(
                        video=media,
                        caption=caption,
                        supports_streaming=True,
                        read_timeout=120,
                        write_timeout=120,
                        connect_timeout=30,
                    )
                else:
                    await message.reply_document(
                        document=media,
                        caption=caption,
                        read_timeout=120,
                        write_timeout=120,
                        connect_timeout=30,
                    )

            await status.delete()

    except yt_dlp.utils.DownloadError as exc:
        log.info("yt-dlp download error: %s", exc)
        await status.edit_text(
            "Video-ga lama soo dejin karin. Hubi link-ga, ama website-ku wuxuu u baahan "
            "yahay login, DRM ayuu leeyahay, ama lama taageero."
        )
    except Exception:
        log.exception("Unexpected download failure")
        await status.edit_text(
            "Cilad ayaa dhacday. Isku day link kale ama mar dambe."
        )


def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit(
            "BOT_TOKEN lama dejin. Ku dar token cusub environment variable-ka BOT_TOKEN."
        )

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    log.info("Azaam Video Bot is running.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
