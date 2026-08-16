# video-summarizer

Feed it a YouTube video, TikTok, or Instagram Reel URL and it prints the main
points as a bulleted list, using Claude Haiku.

How it works:

1. Tries to pull the platform's own captions first (fast, no transcription needed).
2. If none exist, downloads just the audio and transcribes it locally with
   [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (no data leaves your machine
   for this step).
3. Sends the transcript to Claude Haiku, which returns the main points.

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

Multiple videos, one Markdown file per video:

```bash
python summarize.py URL1 URL2 URL3 --out summaries/
```

Use a bigger (more accurate, slower) local Whisper model for the fallback path:

```bash
python summarize.py URL --whisper-model small
```

## Notes

- Works on anything [yt-dlp](https://github.com/yt-dlp/yt-dlp) can extract from -
  YouTube, TikTok, and Instagram Reels are all supported out of the box.
- Private or login-gated content isn't supported.
- Very long transcripts are truncated (~20k characters) before being sent to Claude
  to keep the summary focused and the request fast.
