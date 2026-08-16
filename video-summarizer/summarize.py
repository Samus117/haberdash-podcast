#!/usr/bin/env python3
"""Ingest a YouTube / TikTok / Instagram Reel and print its main points via Claude Haiku.

For each URL:
  1. Pull the video's captions if the platform provides them (fast path).
  2. Otherwise download the audio and transcribe it locally with faster-whisper.
  3. Send the transcript to Claude Haiku and print a bulleted list of main points.
"""

import argparse
import re
import sys
import tempfile
from pathlib import Path

import yt_dlp
from anthropic import Anthropic

HAIKU_MODEL = "claude-haiku-4-5-20251001"
MAX_TRANSCRIPT_CHARS = 20000
CAPTION_LANGS = ["en", "en-US", "en-GB", "en-orig"]


def log(message: str) -> None:
    print(message, file=sys.stderr)


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:80] or "video"


def vtt_to_text(vtt_path: Path) -> str:
    tag_re = re.compile(r"<[^>]+>")
    seen = set()
    lines = []
    for raw_line in vtt_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line == "WEBVTT" or "-->" in line:
            continue
        if line.isdigit() or line.startswith(("NOTE", "Kind:", "Language:")):
            continue
        line = tag_re.sub("", line).strip()
        if line and line not in seen:
            seen.add(line)
            lines.append(line)
    return " ".join(lines)


def fetch_captions(url: str, workdir: Path) -> tuple[dict, str | None]:
    """Probe the video and grab caption text if available. Returns (info, transcript_or_None)."""
    opts = {
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": CAPTION_LANGS,
        "subtitlesformat": "vtt",
        "outtmpl": str(workdir / "%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)

    vtt_files = sorted(workdir.glob("*.vtt"))
    if not vtt_files:
        return info, None
    return info, vtt_to_text(vtt_files[0])


def download_audio(url: str, workdir: Path) -> Path:
    opts = {
        "format": "bestaudio/best",
        "outtmpl": str(workdir / "audio.%(ext)s"),
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
                "preferredquality": "192",
            }
        ],
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

    audio_files = list(workdir.glob("audio.wav"))
    if not audio_files:
        raise RuntimeError("Audio download/conversion failed - is ffmpeg installed?")
    return audio_files[0]


def transcribe_audio(audio_path: Path, model_size: str) -> str:
    from faster_whisper import WhisperModel

    log(f"Transcribing locally with whisper model '{model_size}' (no captions available)...")
    model = WhisperModel(model_size, compute_type="int8")
    segments, _ = model.transcribe(str(audio_path))
    return " ".join(segment.text.strip() for segment in segments)


def get_transcript(url: str, workdir: Path, whisper_model: str) -> tuple[dict, str]:
    log(f"Fetching {url}")
    info, transcript = fetch_captions(url, workdir)
    if transcript:
        log("Using platform captions.")
        return info, transcript

    log("No captions available, downloading audio instead.")
    audio_path = download_audio(url, workdir)
    transcript = transcribe_audio(audio_path, whisper_model)
    return info, transcript


def summarize(client: Anthropic, info: dict, transcript: str) -> str:
    transcript = transcript.strip()
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        log(f"Transcript is long ({len(transcript)} chars); truncating for the summary.")
        transcript = transcript[:MAX_TRANSCRIPT_CHARS]

    prompt = f"""You are given the transcript of a short video.

Title: {info.get('title', 'Unknown')}
Creator: {info.get('uploader', 'Unknown')}
Description: {info.get('description') or '(none)'}

Transcript:
{transcript}

List the main points made in this video as a concise bulleted list (aim for 3-7 bullets).
Focus on substance, not filler. Do not include an introductory or closing sentence -
output only the bullets."""

    response = client.messages.create(
        model=HAIKU_MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


def process_url(client: Anthropic, url: str, whisper_model: str, out_dir: Path | None) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        info, transcript = get_transcript(url, Path(tmp), whisper_model)

    if not transcript.strip():
        log(f"No transcript could be produced for {url}, skipping.")
        return

    points = summarize(client, info, transcript)
    title = info.get("title", url)

    header = f"# {title}\n\nSource: {url}\n"
    output = f"{header}\n{points}\n"

    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{slugify(title)}.md"
        out_path.write_text(output, encoding="utf-8")
        log(f"Wrote {out_path}")
    else:
        print(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("urls", nargs="+", help="YouTube / TikTok / Instagram Reel URLs")
    parser.add_argument(
        "--whisper-model",
        default="base",
        choices=["tiny", "base", "small", "medium", "large-v3"],
        help="faster-whisper model size used when captions aren't available (default: base)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Directory to write one Markdown summary per video instead of printing to stdout",
    )
    args = parser.parse_args()

    client = Anthropic()  # reads ANTHROPIC_API_KEY from the environment

    for url in args.urls:
        try:
            process_url(client, url, args.whisper_model, args.out)
        except Exception as exc:
            log(f"Failed on {url}: {exc}")


if __name__ == "__main__":
    main()
