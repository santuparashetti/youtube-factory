# YouTube Audio Downloader — Setup Guide

Downloads the audio track of a YouTube video as an mp3 file. Nothing else
— no transcription, no translation.

---

## Files

```
download_audio.py
data/                    # created automatically on first run
└── <video_name>/
    └── audio.mp3
```

---

## Installation

### 1. Check your pip version

```bash
pip3 --version
```

### 2. Install yt-dlp

**If pip is 23.0+:**
```bash
pip3 install -U yt-dlp --break-system-packages
```

**If pip is older (common on Ubuntu/Mint — e.g. pip 22.x):**
```bash
pip3 install -U yt-dlp --user
```

### 3. Fix PATH if needed

If `yt-dlp` was installed but the script can't find it, check:

```bash
which yt-dlp
```

If that comes back empty, `yt-dlp` landed in `~/.local/bin`, which isn't
on your PATH yet:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
which yt-dlp   # should now print a path
```

---

## Run

### Auto-named folder (uses the video's title)

```bash
python3 download_audio.py "<youtube_url>"
```

Example:
```bash
python3 download_audio.py "https://www.youtube.com/watch?v=kok7S16kC40"
```

Output: `data/<video_title>/audio.mp3`

### Custom folder name

```bash
python3 download_audio.py "<youtube_url>" --name "my_folder_name"
```

Example:
```bash
python3 download_audio.py "https://www.youtube.com/watch?v=kok7S16kC40" --name "living_to_earn"
```

Output: `data/living_to_earn/audio.mp3`

---

## Notes

- Re-running the same command skips the download if `audio.mp3` already
  exists in that folder.
- Folder names are sanitized automatically (spaces → underscores, special
  characters stripped, capped at 80 characters) — safe to use video
  titles directly without worrying about invalid filesystem characters.
- No folder nesting beyond `data/<name>/` — the mp3 sits directly inside.

---

## Troubleshooting

**`Command 'python' not found`**
Use `python3` instead.

**`no such option: --break-system-packages`**
Your pip is older than 23.0 — use `--user` instead (see step 2 above).

**`FileNotFoundError: yt-dlp` when running the script**
`yt-dlp` isn't on PATH — follow the PATH fix in step 3 above.
