# video-summarizer

Feed it a YouTube video, TikTok/Instagram clip, or a whole channel/profile URL and it
prints the main points as a bulleted list, using Claude Haiku.

How it works:

1. If the URL is a channel or profile, expands it into individual video URLs (capped by `--limit`).
2. For each video: tries to pull the platform's own captions first (fast, no transcription needed).
   If none exist, downloads just the audio and transcribes it locally with
   [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (no data leaves your machine for
   this step).
3. Sends the transcript to Claude Haiku, which returns the main points. Long-form videos (Haiku
   4.5 has a 200K-token context window) are handled directly - transcripts aren't chopped down to
   the first few minutes.
4. With `--digest`, also asks Haiku to synthesize recurring themes across everything processed.

## Setup

Prerequisites:
- Python 3.9+
- [ffmpeg](https://ffmpeg.org/) on your `PATH` (only needed for the audio-transcription fallback)
- An `ANTHROPIC_API_KEY` environment variable

```bash
cd video-summarizer
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-...
```

## Usage

Single video, printed to stdout:

```bash
python summarize.py https://www.youtube.com/watch?v=XXXXXXXXXXX
```

A whole channel/profile - summarizes each of the most recent videos, one Markdown file each,
plus a combined digest of recurring themes:

```bash
python summarize.py "https://www.tiktok.com/@someuser" --limit 15 --out summaries/ --digest
```

Multiple individual videos, one Markdown file per video:

```bash
python summarize.py URL1 URL2 URL3 --out summaries/
```

Use a bigger (more accurate, slower) local Whisper model for the caption-less fallback path:

```bash
python summarize.py URL --whisper-model small
```

## Running it from your phone

### Option A: Telegram bot on your own computer (recommended)

`bot.py` runs on your computer and you talk to it from Telegram on your phone. It works by
having your computer poll Telegram's servers for new messages (an outbound-only connection) -
nothing on your home network is exposed, no port forwarding, no VPN needed, and it works from
anywhere your phone has signal.

**Setup:**

1. In Telegram, message **[@BotFather](https://t.me/BotFather)** → `/newbot` → follow the
   prompts. It gives you a token that looks like `123456789:AAExxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`.
2. On your computer:
   ```bash
   cd video-summarizer
   pip install -r requirements.txt
   export ANTHROPIC_API_KEY=sk-...
   export TELEGRAM_BOT_TOKEN=123456789:AAExxxx...
   python bot.py
   ```
3. In Telegram, open a chat with your new bot and send `/whoami` - it replies with your chat
   ID. Stop the bot (Ctrl-C), then restrict it to just you:
   ```bash
   export TELEGRAM_ALLOWED_CHAT_IDS=123456789
   python bot.py
   ```
   (Without this, anyone who finds your bot's username could message it and use your API key.)

**Usage from your phone:** send the bot any video link and it replies with the main points.
Send `/channel <url> [limit]` to summarize a whole channel/profile (default 5 videos) plus a
digest across all of them.

**Keeping it running:** `python bot.py` only runs while your terminal session is open. To keep
it running in the background:

- **macOS:** `nohup python bot.py > bot.log 2>&1 &`, or set it up as a
  [LaunchAgent](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html)
  so it survives reboots.
- **Linux:** run it as a `systemd --user` service, or `nohup python bot.py > bot.log 2>&1 &`
  inside a `screen`/`tmux` session.

Your computer needs to be on and awake (not asleep) for the bot to receive messages.

### Option B: GitHub Actions (no computer needs to stay on)

Trigger a one-off run from the GitHub mobile app instead - nothing runs on your machine:

1. Add your Anthropic API key as a repo secret: **Settings → Secrets and variables → Actions →
   New repository secret**, named `ANTHROPIC_API_KEY`.
2. In the GitHub app (or mobile browser), go to **Actions → Summarize Video → Run workflow**.
3. Paste one video/channel URL per line, run it, and it'll post the results as a new GitHub
   Issue - which shows up as a push notification in the GitHub app once you're watching the repo
   (Repo → Watch → Custom → Issues).

The workflow lives at `.github/workflows/summarize.yml`. It installs `ffmpeg` and the Python
dependencies fresh on each run, so no server to maintain - just GitHub Actions minutes (free
for public repos). Slower to kick off than texting the bot, but nothing needs to stay running.

## Notes

- Works on anything [yt-dlp](https://github.com/yt-dlp/yt-dlp) can extract from -
  YouTube, TikTok, and Instagram are all supported out of the box, including channel/profile
  URLs (yt-dlp treats them as playlists).
- Private or login-gated content isn't supported.
- Channels/profiles without platform captions (common on TikTok/Instagram) fall back to local
  Whisper transcription per video, which is much slower than the caption path - keep `--limit`
  modest for those.
- Extremely long transcripts (multi-hour) are still capped (~500k characters) as a safety limit,
  not because Haiku can't handle more.
