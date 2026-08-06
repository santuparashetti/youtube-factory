// =====================================================
// ChatGPT Batch Image Generator — content script
// Injects a floating control panel into the ChatGPT page.
// =====================================================

(function () {
  if (window.__cgbatch_loaded) return;
  window.__cgbatch_loaded = true;

  const existingPanel = document.getElementById('cgb-panel');
  if (existingPanel) existingPanel.remove();

  const CONFIG = {
    imageTimeoutMs: 90000,
    gapBetweenMs: 2000,
    retries: 1
  };

  let scenes = [];
  let setupMessage = null;
  let running = false;
  let cancelRequested = false;
  let failedScenes = [];

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // ---------- Parsing ----------
  function parseSceneMarkdown(text) {
    const out = [];
    const parts = text.split(/^##\s+Scene\s+/mi).slice(1);
    for (const part of parts) {
      // Prefer the "Save to:" path — it carries both the filename and the
      // full intended folder structure. Fall back to the header filename.
      const saveMatch = part.match(/\*\*Save to:\*\*\s*`([^`]+)`/i);
      const savePath = saveMatch ? saveMatch[1].trim() : null;

      const fnMatch = part.match(/`\s*([\w-]+\.png)\s*`/i);
      let filename = fnMatch ? fnMatch[1] : null;
      if (savePath) {
        const tail = savePath.split('/').pop();
        if (tail) filename = tail;
      }

      const promptMatch = part.match(
        /\*\*Image Prompt:\*\*\s*([\s\S]*?)(?:\n\s*\*\*Visual Metadata:\*\*|\n---|\n##\s|$)/i
      );
      if (!filename || !promptMatch) continue;

      const lines = promptMatch[1]
        .split('\n')
        .map((l) => l.replace(/^\s*>\s?/, '').trim())
        .filter(Boolean);
      const prompt = lines.join(' ').trim();

      // Derive a relative folder path from the Save to path, so downloads
      // can mirror the intended structure inside the Downloads folder.
      const relPath = deriveRelPath(savePath, filename);

      if (prompt) out.push({ filename, prompt, savePath, relPath });
    }
    return out;
  }

  // Pull the one-time setup / character-consistency message from the
  // "## Step 0 — Before You Start" section — the first fenced ``` block
  // that appears before the scenes begin.
  function extractSetupMessage(text) {
    // Isolate everything before the first "## Scene" so we don't grab
    // the re-run bash block or anything later.
    const beforeScenes = text.split(/^##\s+Scene\s+/mi)[0];

    // Prefer a fenced block inside the Step 0 section specifically.
    const step0Match = beforeScenes.match(
      /##\s*Step\s*0[\s\S]*?```(?:\w+)?\s*\n([\s\S]*?)\n```/i
    );
    let block = step0Match ? step0Match[1] : null;

    // Fallback: first plain (non-bash) fenced block before the scenes.
    if (!block) {
      const anyMatch = beforeScenes.match(/```(?!bash)(?:\w+)?\s*\n([\s\S]*?)\n```/);
      block = anyMatch ? anyMatch[1] : null;
    }

    if (!block) return null;
    // Collapse the hard-wrapped lines into clean sentences.
    return block
      .split('\n')
      .map((l) => l.trim())
      .filter(Boolean)
      .join(' ')
      .trim();
  }

  // Turn "/home/.../jobs/the-fake-happiness-trap/images/scene-001.png"
  // into "the-fake-happiness-trap/images/scene-001.png".
  // Anchors on jobs/ or workspace/ if present; else keeps last 2 segments.
  function deriveRelPath(savePath, filename) {
    if (!savePath) return filename;
    const segs = savePath.split('/').filter(Boolean);
    let start = -1;
    const jobsIdx = segs.indexOf('jobs');
    const wsIdx = segs.indexOf('workspace');
    if (jobsIdx !== -1 && jobsIdx + 1 < segs.length) start = jobsIdx + 1;
    else if (wsIdx !== -1 && wsIdx + 1 < segs.length) start = wsIdx + 1;
    else if (segs.length >= 2) start = segs.length - 2; // parent folder + file
    if (start === -1) return filename;
    return segs.slice(start).join('/');
  }

  function parseGeneric(text, filename) {
    const ext = (filename.split('.').pop() || '').toLowerCase();
    text = text.trim();
    if (ext === 'json') {
      const data = JSON.parse(text);
      const arr = Array.isArray(data) ? data : data.prompts || Object.values(data);
      return arr
        .map((p, i) => {
          const fn = pad(i + 1) + '_dalle.png';
          return { prompt: String(p).trim(), filename: fn, savePath: null, relPath: fn };
        })
        .filter((x) => x.prompt);
    }
    if (ext === 'csv') {
      return text
        .split('\n')
        .slice(1)
        .map((line, i) => {
          const fn = pad(i + 1) + '_dalle.png';
          return {
            prompt: line.split(',')[0].replace(/^"|"$/g, '').trim(),
            filename: fn,
            savePath: null,
            relPath: fn
          };
        })
        .filter((x) => x.prompt);
    }
    return text
      .split('\n')
      .map((l) => l.trim())
      .filter((l) => l && !l.startsWith('#'))
      .map((p, i) => {
        const fn = pad(i + 1) + '_dalle.png';
        return { prompt: p, filename: fn, savePath: null, relPath: fn };
      });
  }

  function pad(n) {
    return String(n).padStart(3, '0');
  }

  function parseFile(text, filename) {
    const ext = (filename.split('.').pop() || '').toLowerCase();
    if (ext === 'md') {
      const s = parseSceneMarkdown(text);
      if (s.length) return s;
      log('No "## Scene" blocks found — falling back to line-by-line.', 'warn');
    }
    return parseGeneric(text, filename);
  }

  // ---------- ChatGPT DOM helpers ----------
  function getInput() {
    return (
      document.querySelector('#prompt-textarea') ||
      document.querySelector('textarea[placeholder*="Message"]') ||
      document.querySelector('[contenteditable="true"][id*="prompt"]') ||
      document.querySelector('textarea')
    );
  }

  function typePrompt(el, text) {
    el.focus();
    document.execCommand('selectAll', false, null);
    document.execCommand('delete', false, null);
    document.execCommand('insertText', false, text);
    el.dispatchEvent(new InputEvent('input', { bubbles: true }));
  }

  function getSendButton() {
    return (
      document.querySelector('button[data-testid="send-button"]') ||
      document.querySelector('button[aria-label*="Send"]') ||
      document.querySelector('button[aria-label*="send"]')
    );
  }

  function getImageUrls() {
    return new Set(
      Array.from(document.querySelectorAll('main img, [role="main"] img'))
        .map((img) => img.src)
        .filter(
          (src) =>
            src &&
            src.startsWith('http') &&
            !src.includes('avatar') &&
            !src.includes('icon')
        )
    );
  }

  async function waitForNewImage(before, timeoutMs) {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      if (cancelRequested) return null;
      const after = getImageUrls();
      for (const url of after) if (!before.has(url)) return url;
      await sleep(1500);
    }
    return null;
  }

  function downloadViaBackground(url, filename, subfolder) {
    return new Promise((resolve) => {
      chrome.runtime.sendMessage(
        { type: 'DOWNLOAD_IMAGE', url, filename, subfolder },
        (resp) => resolve(resp && resp.ok)
      );
    });
  }

  async function attemptPrompt(prompt) {
    const input = getInput();
    if (!input) {
      log('Input box not found — is this a ChatGPT chat page?', 'error');
      return null;
    }
    const before = getImageUrls();
    typePrompt(input, prompt);
    await sleep(400);
    const btn = getSendButton();
    if (btn) btn.click();
    else
      input.dispatchEvent(
        new KeyboardEvent('keydown', {
          key: 'Enter',
          code: 'Enter',
          keyCode: 13,
          bubbles: true
        })
      );
    return await waitForNewImage(before, CONFIG.imageTimeoutMs);
  }

  // Send a plain text message (e.g. the setup primer) and wait for ChatGPT
  // to acknowledge — we just pause a fixed, generous window rather than
  // watching for an image, since no image is expected here.
  async function sendPlainMessage(text) {
    const input = getInput();
    if (!input) {
      log('Input box not found — is this a ChatGPT chat page?', 'error');
      return false;
    }
    typePrompt(input, text);
    await sleep(400);
    const btn = getSendButton();
    if (btn) btn.click();
    else
      input.dispatchEvent(
        new KeyboardEvent('keydown', {
          key: 'Enter',
          code: 'Enter',
          keyCode: 13,
          bubbles: true
        })
      );
    // Give ChatGPT a moment to read/acknowledge before the first scene.
    await sleep(6000);
    return true;
  }

  // ---------- Batch runner ----------
  async function runBatch() {
    if (!scenes.length) {
      log('No prompts loaded — pick a file first.', 'warn');
      return;
    }
    running = true;
    cancelRequested = false;
    failedScenes = [];
    setControls(true);
    const subfolder = document.getElementById('cgb-subfolder').value;
    const mirror = document.getElementById('cgb-mirror').checked;
    let ok = 0,
      fail = 0;

    log(`Starting — ${scenes.length} prompts.`, 'head');

    // Send the one-time setup / character-consistency primer first.
    if (setupMessage && !cancelRequested) {
      log('Sending setup message first...', 'step');
      log(`   "${setupMessage.slice(0, 90)}${setupMessage.length > 90 ? '...' : ''}"`, 'dim');
      await sendPlainMessage(setupMessage);
      log('   setup sent ✓', 'ok');
    }

    for (let i = 0; i < scenes.length; i++) {
      if (cancelRequested) {
        log('Cancelled by user.', 'warn');
        break;
      }
      const { prompt, filename, relPath } = scenes[i];
      // What we actually hand to the download: mirrored structure or flat name.
      const targetName = mirror && relPath ? relPath : filename;
      setProgress(i, scenes.length);
      log(`[${i + 1}/${scenes.length}] ${targetName}`, 'step');

      let imgUrl = null;
      const maxTries = 1 + CONFIG.retries;
      for (let attempt = 1; attempt <= maxTries; attempt++) {
        if (cancelRequested) break;
        if (attempt > 1) log(`   retry ${attempt - 1}/${CONFIG.retries}...`, 'dim');
        imgUrl = await attemptPrompt(prompt);
        if (imgUrl) break;
        if (attempt < maxTries) await sleep(2000);
      }

      if (imgUrl) {
        const saved = await downloadViaBackground(imgUrl, targetName, subfolder);
        log(`   ${saved ? 'saved ✓ ' : 'download failed '} ${targetName}`, saved ? 'ok' : 'error');
        ok++;
      } else {
        log(`   failed after ${maxTries} attempts — skipping`, 'error');
        failedScenes.push({ ...scenes[i] });
        fail++;
      }
      if (i < scenes.length - 1 && !cancelRequested) await sleep(CONFIG.gapBetweenMs);
    }

    setProgress(scenes.length, scenes.length);
    log(`Done. ${ok} downloaded, ${fail} failed.`, 'head');
    if (failedScenes.length) log('Failed: ' + failedScenes.map(s => s.filename).join(', '), 'error');
    running = false;
    setControls(false);
    if (failedScenes.length > 0) {
      const retryBtn = document.getElementById('cgb-retry');
      if (retryBtn) retryBtn.disabled = false;
    }
  }

  async function retryFailed() {
    if (!failedScenes.length || running) return;
    running = true;
    cancelRequested = false;
    setControls(true);

    const subfolder = document.getElementById('cgb-subfolder').value;
    const mirror = document.getElementById('cgb-mirror').checked;
    let ok = 0,
      fail = 0;
    const stillFailed = [];
    const retryCount = failedScenes.length;

    log(`Retrying ${retryCount} failed images...`, 'head');

    for (let i = 0; i < failedScenes.length; i++) {
      if (cancelRequested) {
        log('Cancelled by user.', 'warn');
        stillFailed.push(...failedScenes.slice(i));
        break;
      }
      const { prompt, filename, relPath } = failedScenes[i];
      const targetName = mirror && relPath ? relPath : filename;
      setProgress(i, retryCount);
      log(`[${i + 1}/${retryCount}] ${targetName}`, 'step');

      let imgUrl = null;
      const maxTries = 1 + CONFIG.retries;
      for (let attempt = 1; attempt <= maxTries; attempt++) {
        if (cancelRequested) break;
        if (attempt > 1) log(`   retry ${attempt - 1}/${CONFIG.retries}...`, 'dim');
        imgUrl = await attemptPrompt(prompt);
        if (imgUrl) break;
        if (attempt < maxTries) await sleep(2000);
      }

      if (imgUrl) {
        const saved = await downloadViaBackground(imgUrl, targetName, subfolder);
        log(`   ${saved ? 'saved ✓ ' : 'download failed '} ${targetName}`, saved ? 'ok' : 'error');
        ok++;
      } else {
        log(`   failed after ${maxTries} attempts — keeping in retry queue`, 'error');
        stillFailed.push(failedScenes[i]);
        fail++;
      }
      if (i < failedScenes.length - 1 && !cancelRequested) await sleep(CONFIG.gapBetweenMs);
    }

    failedScenes = stillFailed;
    setProgress(retryCount - stillFailed.length, retryCount);
    log(`Retry done. ${ok} downloaded, ${fail} failed.`, 'head');
    if (failedScenes.length) log('Still failed: ' + failedScenes.map(s => s.filename).join(', '), 'error');
    running = false;
    setControls(false);
    if (failedScenes.length > 0) {
      const retryBtn = document.getElementById('cgb-retry');
      if (retryBtn) retryBtn.disabled = false;
    }
  }

  // ---------- Panel UI ----------
  function buildPanel() {
    const existing = document.getElementById('cgb-panel');
    if (existing) existing.remove();
    const panel = document.createElement('div');
    panel.id = 'cgb-panel';
    panel.innerHTML = `
      <div id="cgb-header">
        <span id="cgb-title">Batch Image Generator</span>
        <span id="cgb-toggle" title="Collapse">–</span>
      </div>
      <div id="cgb-body">
        <label class="cgb-lbl">Prompts file (.md / .txt / .json / .csv)</label>
        <input type="file" id="cgb-file" accept=".md,.txt,.json,.csv" />
        <div id="cgb-fileinfo" class="cgb-dim">No file loaded</div>

        <label class="cgb-lbl">Save into Downloads subfolder</label>
        <input type="text" id="cgb-subfolder" value="chatgpt-images" placeholder="e.g. youtube-factory" />

        <label class="cgb-check">
          <input type="checkbox" id="cgb-mirror" checked />
          Mirror folder structure from the file's Save to path
        </label>

        <div id="cgb-btns">
          <button id="cgb-preview" class="cgb-btn">Preview</button>
          <button id="cgb-start" class="cgb-btn cgb-primary" disabled>Start</button>
          <button id="cgb-retry" class="cgb-btn cgb-warning" disabled>Retry Failed</button>
          <button id="cgb-cancel" class="cgb-btn cgb-danger" disabled>Cancel</button>
        </div>

        <div id="cgb-progwrap"><div id="cgb-progbar"></div></div>
        <div id="cgb-progtext" class="cgb-dim">Idle</div>

        <div id="cgb-log"></div>
      </div>
    `;
    document.body.appendChild(panel);

    // Events
    document.getElementById('cgb-toggle').onclick = () => {
      const body = document.getElementById('cgb-body');
      const t = document.getElementById('cgb-toggle');
      const hidden = body.style.display === 'none';
      body.style.display = hidden ? 'block' : 'none';
      t.textContent = hidden ? '–' : '+';
    };

    document.getElementById('cgb-file').onchange = (e) => {
      const file = e.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => {
        try {
          scenes = parseFile(reader.result, file.name);
          const ext = (file.name.split('.').pop() || '').toLowerCase();
          setupMessage = ext === 'md' ? extractSetupMessage(reader.result) : null;
          failedScenes = [];
          const retryBtn = document.getElementById('cgb-retry');
          if (retryBtn) retryBtn.disabled = true;
          document.getElementById('cgb-fileinfo').textContent =
            `${file.name} — ${scenes.length} prompts${setupMessage ? ' + setup message' : ''}`;
          document.getElementById('cgb-start').disabled = scenes.length === 0;
          log(`Loaded ${scenes.length} prompts from ${file.name}`, 'ok');
          if (setupMessage) log('Setup message detected — will be sent first.', 'ok');
        } catch (err) {
          log('Parse error: ' + err.message, 'error');
        }
      };
      reader.readAsText(file);
    };

    document.getElementById('cgb-preview').onclick = () => {
      if (!scenes.length) {
        log('Pick a file first.', 'warn');
        return;
      }
      const mirror = document.getElementById('cgb-mirror').checked;
      const sub = document.getElementById('cgb-subfolder').value.trim().replace(/^\/+|\/+$/g, '');
      log('--- Preview ---', 'head');
      if (setupMessage) {
        log('Setup message (sent first):', 'step');
        log(`   ${setupMessage}`, 'dim');
        log('', 'dim');
      }
      scenes.forEach((s, i) => {
        const rel = mirror && s.relPath ? s.relPath : s.filename;
        const full = 'Downloads/' + (sub ? sub + '/' : '') + rel;
        log(`${i + 1}. ${full}`, 'ok');
        log(`     ${s.prompt.slice(0, 76)}${s.prompt.length > 76 ? '...' : ''}`, 'dim');
      });
    };

    document.getElementById('cgb-start').onclick = () => {
      if (!running) runBatch();
    };

    document.getElementById('cgb-retry').onclick = () => {
      if (running || !failedScenes.length) return;
      retryFailed();
    };

    document.getElementById('cgb-cancel').onclick = () => {
      cancelRequested = true;
      log('Cancelling after current image...', 'warn');
    };
  }

  function setControls(isRunning) {
    document.getElementById('cgb-start').disabled = isRunning || scenes.length === 0;
    document.getElementById('cgb-cancel').disabled = !isRunning;
    document.getElementById('cgb-preview').disabled = isRunning;
    document.getElementById('cgb-file').disabled = isRunning;
    const retryBtn = document.getElementById('cgb-retry');
    if (retryBtn) retryBtn.disabled = isRunning || failedScenes.length === 0;
  }

  function setProgress(done, total) {
    const pct = total ? Math.round((done / total) * 100) : 0;
    document.getElementById('cgb-progbar').style.width = pct + '%';
    document.getElementById('cgb-progtext').textContent =
      total ? `${done}/${total} (${pct}%)` : 'Idle';
  }

  function log(msg, kind) {
    const el = document.getElementById('cgb-log');
    if (!el) return;
    const line = document.createElement('div');
    line.className = 'cgb-line cgb-' + (kind || 'dim');
    line.textContent = msg;
    el.appendChild(line);
    el.scrollTop = el.scrollHeight;
  }

  // ---------- Styles ----------
  function injectStyles() {
    if (document.getElementById('cgb-styles')) return;
    const s = document.createElement('style');
    s.id = 'cgb-styles';
    s.textContent = `
      #cgb-panel {
        position: fixed; top: 80px; right: 20px; width: 320px; z-index: 2147483647;
        background: #ffffff; color: #1a1a1a; border: 1px solid #d9d9d9;
        border-radius: 12px; box-shadow: 0 8px 30px rgba(0,0,0,.18);
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        font-size: 13px; overflow: hidden;
      }
      @media (prefers-color-scheme: dark) {
        #cgb-panel { background: #2a2a2e; color: #ececf1; border-color: #444; }
        #cgb-panel input[type=text] { background:#1e1e22; color:#ececf1; border-color:#555; }
        #cgb-fileinfo, .cgb-dim { color:#9a9aa5 !important; }
        #cgb-log { background:#1e1e22; border-color:#444; }
        .cgb-btn { background:#3a3a40; color:#ececf1; border-color:#555; }
        .cgb-btn:hover { background:#46464d; }
        .cgb-warning { background:#b8751a; border-color:#b8751a; }
        .cgb-warning:hover:not(:disabled) { background:#d4921f; }
      }
      #cgb-header {
        display:flex; align-items:center; justify-content:space-between;
        padding:10px 14px; background:#10a37f; color:#fff; cursor:default;
      }
      #cgb-title { font-weight:600; font-size:13px; }
      #cgb-toggle { cursor:pointer; font-size:18px; line-height:1; width:20px; text-align:center; user-select:none; }
      #cgb-body { padding:12px 14px; }
      .cgb-lbl { display:block; font-size:11px; text-transform:uppercase; letter-spacing:.03em;
        color:#888; margin:10px 0 4px; font-weight:600; }
      #cgb-body input[type=file] { width:100%; font-size:12px; }
      #cgb-body input[type=text] {
        width:100%; box-sizing:border-box; padding:6px 8px; border:1px solid #d0d0d0;
        border-radius:6px; font-size:12px; font-family:inherit;
      }
      #cgb-fileinfo { margin-top:6px; font-size:12px; }
      .cgb-check { display:flex; align-items:flex-start; gap:7px; margin-top:12px;
        font-size:12px; line-height:1.4; cursor:pointer; }
      .cgb-check input { margin-top:1px; flex-shrink:0; }
      #cgb-btns { display:flex; gap:6px; margin:14px 0 10px; }
      .cgb-btn {
        flex:1; padding:7px 10px; border:1px solid #d0d0d0; border-radius:7px;
        background:#f5f5f5; color:#1a1a1a; font-size:12px; font-weight:600; cursor:pointer;
        font-family:inherit; transition:background .12s;
      }
      .cgb-btn:hover:not(:disabled) { background:#eaeaea; }
      .cgb-btn:disabled { opacity:.45; cursor:not-allowed; }
      .cgb-primary { background:#10a37f; border-color:#10a37f; color:#fff; }
      .cgb-primary:hover:not(:disabled) { background:#0e916f; }
       .cgb-danger { background:#fff; border-color:#e0b4b4; color:#c0392b; }
       .cgb-danger:hover:not(:disabled) { background:#fbeaea; }
       .cgb-warning { background:#f5a623; border-color:#f5a623; color:#fff; }
       .cgb-warning:hover:not(:disabled) { background:#d4921f; }
      #cgb-progwrap { height:6px; background:#e8e8e8; border-radius:4px; overflow:hidden; margin-top:4px; }
      #cgb-progbar { height:100%; width:0%; background:#10a37f; transition:width .3s; }
      #cgb-progtext { margin-top:5px; font-size:11px; }
      #cgb-log {
        margin-top:10px; max-height:200px; overflow-y:auto; background:#fafafa;
        border:1px solid #eee; border-radius:6px; padding:8px; font-size:11px;
        font-family: ui-monospace, "SF Mono", Menlo, monospace; line-height:1.5;
      }
      .cgb-line { white-space:pre-wrap; word-break:break-word; }
      .cgb-head { color:#10a37f; font-weight:700; margin-top:4px; }
      .cgb-step { color:inherit; font-weight:600; }
      .cgb-ok { color:#1a8a5f; }
      .cgb-error { color:#c0392b; }
      .cgb-warn { color:#c77700; }
      .cgb-dim { color:#999; }
    `;
    document.head.appendChild(s);
  }

  // Wait for body, then build.
  function init() {
    injectStyles();
    buildPanel();
  }
  if (document.body) init();
  else window.addEventListener('DOMContentLoaded', init);
})();
