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

There's no native mobile app, but you can trigger this without hosting anything by running it
as a GitHub Action from the GitHub mobile app:

1. Add your Anthropic API key as a repo secret: **Settings → Secrets and variables → Actions →
   New repository secret**, named `ANTHROPIC_API_KEY`.
2. In the GitHub app (or mobile browser), go to **Actions → Summarize Video → Run workflow**.
3. Paste one video/channel URL per line, run it, and it'll post the results as a new GitHub
   Issue - which shows up as a push notification in the GitHub app once you're watching the repo
   (Repo → Watch → Custom → Issues).

The workflow lives at `.github/workflows/summarize.yml`. It installs `ffmpeg` and the Python
dependencies fresh on each run, so no server to maintain - just GitHub Actions minutes (free
for public repos).

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
