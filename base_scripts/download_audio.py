#!/usr/bin/env python3
"""
download_audio.py

Downloads the audio track of a YouTube video as an mp3 file.

Usage:
    python3 download_audio.py <youtube_url> [--name "custom_folder_name"]

Output:
    data/<name>/audio.mp3

If --name is not given, the video's title is used (sanitized for
filesystem safety).

Requires: yt-dlp (pip install -U yt-dlp --user)
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path


def get_video_title(url: str) -> str:
    result = subprocess.run(
        ["yt-dlp", "--get-title", url],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def sanitize_folder_name(name: str) -> str:
    # Keep it filesystem-safe and reasonably short.
    name = re.sub(r"[^\w\s-]", "", name)
    name = re.sub(r"\s+", "_", name).strip("_")
    return name[:80] or "untitled"


def download_audio(url: str, folder_name: str) -> Path:
    out_dir = Path("data") / folder_name
    out_dir.mkdir(parents=True, exist_ok=True)
    audio_path = out_dir / "audio.mp3"

    if audio_path.exists():
        print(f"Already downloaded: {audio_path}")
        return audio_path

    subprocess.run(
        [
            "yt-dlp", "-x", "--audio-format", "mp3",
            "-o", str(out_dir / "audio.%(ext)s"),
            url,
        ],
        check=True,
    )
    return audio_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument("--name", default=None, help="folder name (defaults to video title)")
    args = parser.parse_args()

    folder_name = sanitize_folder_name(args.name) if args.name else None

    if not folder_name:
        print("Fetching video title...")
        title = get_video_title(args.url)
        folder_name = sanitize_folder_name(title)

    print(f"Folder: data/{folder_name}")
    audio_path = download_audio(args.url, folder_name)
    print(f"\nDone -> {audio_path}")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        print(f"Command failed: {e}", file=sys.stderr)
        sys.exit(1)
