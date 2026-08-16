#!/usr/bin/env python3
"""Ingest YouTube / TikTok / Instagram videos (or whole channels) and print the main points
via Claude Haiku.

For each URL:
  1. If it's a channel/profile URL, expand it into up to --limit individual video URLs.
  2. For each video: pull captions if the platform provides them (fast path), otherwise
     download the audio and transcribe it locally with faster-whisper.
  3. Send the transcript to Claude Haiku and print a bulleted list of main points.
  4. With --digest, also produce one combined synthesis across everything processed.
"""

import argparse
import re
import sys
import tempfile
from pathlib import Path

import yt_dlp
from anthropic import Anthropic

HAIKU_MODEL = "claude-haiku-4-5"
# Haiku 4.5 has a 200K-token context window (~4 chars/token). Cap well below that
# so even multi-hour transcripts fit in one request with room for the prompt and reply.
MAX_TRANSCRIPT_CHARS = 500000
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


def expand_urls(url: str, limit: int) -> list[str]:
    """If url is a channel/profile/playlist, return up to `limit` individual video URLs."""
    opts = {
        "extract_flat": True,
        "playlistend": limit,
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    entries = info.get("entries")
    if not entries:
        return [url]

    urls = []
    for entry in entries:
        if not entry:
            continue
        video_url = entry.get("url") or entry.get("webpage_url")
        if video_url:
            urls.append(video_url)
        if len(urls) >= limit:
            break
    return urls or [url]


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
        log(f"Transcript is very long ({len(transcript)} chars); truncating for the summary.")
        transcript = transcript[:MAX_TRANSCRIPT_CHARS]

    prompt = f"""You are given the transcript of a video.

Title: {info.get('title', 'Unknown')}
Creator: {info.get('uploader', 'Unknown')}
Description: {info.get('description') or '(none)'}

Transcript:
{transcript}

List the main points made in this video as a concise bulleted list (aim for 3-7 bullets,
more for a long-form video with many distinct points).
Focus on substance, not filler. Do not include an introductory or closing sentence -
output only the bullets."""

    response = client.messages.create(
        model=HAIKU_MODEL,
        max_tokens=1536,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


def build_digest(client: Anthropic, entries: list[tuple[str, str]]) -> str:
    joined = "\n\n".join(f"## {title}\n{points}" for title, points in entries)
    prompt = f"""Below are the main points extracted from {len(entries)} videos, likely from
the same creator or channel.

{joined}

Write a short synthesis (5-10 bullets) of the recurring themes, positions, and topics across
all of these videos. Call out any notable disagreements, shifts, or one-off outliers if present.
Output only the bullets, no introductory or closing sentence."""

    response = client.messages.create(
        model=HAIKU_MODEL,
        max_tokens=1536,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


def process_url(
    client: Anthropic, url: str, whisper_model: str, out_dir: Path | None
) -> tuple[str, str] | None:
    with tempfile.TemporaryDirectory() as tmp:
        info, transcript = get_transcript(url, Path(tmp), whisper_model)

    if not transcript.strip():
        log(f"No transcript could be produced for {url}, skipping.")
        return None

    points = summarize(client, info, transcript)
    title = info.get("title", url)

    output = f"# {title}\n\nSource: {url}\n\n{points}\n"

    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{slugify(title)}.md"
        out_path.write_text(output, encoding="utf-8")
        log(f"Wrote {out_path}")
    else:
        print(output)

    return title, points


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "urls", nargs="+", help="Video, channel, or profile URLs (YouTube / TikTok / Instagram)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Max videos to pull when a URL is a channel/profile (default: 10)",
    )
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
    parser.add_argument(
        "--digest",
        action="store_true",
        help="Also produce one combined summary synthesizing themes across all videos processed",
    )
    args = parser.parse_args()

    client = Anthropic()  # reads ANTHROPIC_API_KEY from the environment

    processed: list[tuple[str, str]] = []
    for raw_url in args.urls:
        try:
            video_urls = expand_urls(raw_url, args.limit)
        except Exception as exc:
            log(f"Failed to expand {raw_url}: {exc}")
            continue

        if len(video_urls) > 1:
            log(f"{raw_url} expanded to {len(video_urls)} videos.")

        for url in video_urls:
            try:
                result = process_url(client, url, args.whisper_model, args.out)
                if result:
                    processed.append(result)
            except Exception as exc:
                log(f"Failed on {url}: {exc}")

    if args.digest and len(processed) > 1:
        digest = build_digest(client, processed)
        output = f"# Digest across {len(processed)} videos\n\n{digest}\n"
        if args.out:
            args.out.mkdir(parents=True, exist_ok=True)
            digest_path = args.out / "channel-digest.md"
            digest_path.write_text(output, encoding="utf-8")
            log(f"Wrote {digest_path}")
        else:
            print(output)


if __name__ == "__main__":
    main()
