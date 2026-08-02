# 🎨 ChatGPT Batch Image Generator — Chrome Extension

Generates every image from a prompts file inside ChatGPT and downloads each
one with its exact scene filename. No console pasting.

Works with your `IMAGE_PROMPTS.md` scene format, plus `.txt`, `.json`, `.csv`.

---

## 📦 Install (load unpacked — one time)

1. Unzip this folder somewhere permanent (e.g. `Documents/chatgpt-batch-extension`).
2. Open Chrome and go to: `chrome://extensions`
3. Turn on **Developer mode** (toggle, top-right).
4. Click **Load unpacked** and select the unzipped folder.
5. The extension icon appears in your toolbar. Done.

> To update later: replace the files, then click the **refresh** icon on the
> extension card at `chrome://extensions`.

---

## 🚀 Use

1. Open **https://chatgpt.com** and start a new chat (image generation enabled).
2. A green **Batch Image Generator** panel appears in the top-right of the page.
   - If it's not there, refresh the tab.
3. Click **Choose file** and pick your `IMAGE_PROMPTS.md`.
   - It shows how many prompts it found.
4. (Optional) Set a **Downloads subfolder** — images save into
   `Downloads/<subfolder>/`. Default is `chatgpt-images`.
5. Click **Preview** to see the parsed prompts + filenames in the log first.
6. Click **Start**. It types each prompt, waits for the image, and downloads it.
7. Use **Cancel** to stop after the current image.

---

## 📄 File format

### Scene markdown (`.md`) — your format
The parser reads each `## Scene N` block, ignores the intro sections
(How to Use / Tools / Re-run Command), and for each scene extracts only the
**Image Prompt** section (the `>` guardrail line + the description paragraph).
Each image is saved with the exact filename from the scene header
(`scene-001.png`, `scene-002.png`, ...).

**Setup message (character consistency):** if the file has a
`## Step 0 — Before You Start` section with a fenced ``` block, that message
(e.g. the consistent-character description) is sent to ChatGPT **first**, as a
single plain message, before any scene prompt. This primes ChatGPT to keep the
same character across all images. The scene loop then begins normally. If the
file has no Step 0 block, this step is simply skipped. Click **Preview** to see
the exact setup message that will be sent.

### Also supported
- `.txt` — one prompt per line (`#` comments ignored)
- `.json` — array of strings, or `{ "prompts": [...] }`
- `.csv` — first column used, header row skipped

For non-`.md` files, images are named `001_dalle.png`, `002_dalle.png`, ...

---

## ⚙️ Settings

Open `content.js` and edit the top `CONFIG` block if needed:

```js
const CONFIG = {
  imageTimeoutMs: 90000,   // how long to wait for each image
  gapBetweenMs:   2000,    // pause between prompts
  retries:        1        // extra attempts if an image fails
};
```

Refresh the extension after editing.

---

## 📁 Where images go

Browsers **cannot** write to an absolute path like
`/home/santosh/pvt-files/.../images/scene-001.png` — Chrome downloads are
locked to your Downloads folder. No extension can change that (OS sandbox).

### Mirror folder structure (on by default)

The `.md` file's `**Save to:**` line carries the full intended path. With the
**"Mirror folder structure"** checkbox ticked, the extension recreates that
structure *inside* Downloads. For your file:

```
Save to:  /home/santosh/pvt-files/youtube-factory/workspace/jobs/the-fake-happiness-trap/images/scene-001.png
Saved to: Downloads/<subfolder>/the-fake-happiness-trap/images/scene-001.png
```

It anchors on `jobs/` (or `workspace/`) and keeps everything after it, so the
job-name/images hierarchy is preserved. Two ways to use this:

- **Drag once:** let them download into `Downloads/youtube-factory/...`, then
  move that one folder to your real location.
- **Zero moving:** set Chrome's download location
  (Settings → Downloads → Location) to
  `/home/santosh/pvt-files/youtube-factory/workspace/jobs/` and leave the
  subfolder box empty — images then land in the exact `images/` folders your
  pipeline expects.

Untick the checkbox to get a flat dump of just `scene-001.png`, `scene-002.png`
into the subfolder instead.

Files use `conflictAction: overwrite`, so re-running replaces old versions
cleanly instead of adding `(1)`, `(2)` suffixes.

> **Preview shows the real target.** Click **Preview** and each line prints the
> exact `Downloads/...` path each image will be saved to, so you can confirm
> before generating.

---

## ❓ Troubleshooting

| Problem | Fix |
|--------|-----|
| No panel on the page | Refresh the ChatGPT tab; confirm you're on chatgpt.com |
| "Input box not found" | Make sure you're inside an actual chat, not the settings page |
| Images not downloading | Check `chrome://settings/downloads` — allow multiple/auto downloads |
| Prompt sent but no image | ChatGPT may be rate-limiting; increase `imageTimeoutMs` or slow down |
| Wrong prompts parsed | Click **Preview** to inspect; confirm your `.md` uses `## Scene` headers |

---

## 🔒 Privacy

Everything runs locally in your browser. The extension only reads the file you
pick and interacts with the ChatGPT tab. No data is sent anywhere else.
