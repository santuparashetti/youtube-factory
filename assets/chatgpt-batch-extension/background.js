// Background service worker — handles image downloads via chrome.downloads API.
// Content scripts can't call chrome.downloads directly, so they message us.

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'CHECK_DOWNLOADS') {
    const { subfolder, filenames } = msg;
    const targetFilenames = new Set();
    if (subfolder && subfolder.trim()) {
      const clean = subfolder.trim().replace(/^\/+|\/+$/g, '');
      filenames.forEach((fn) => targetFilenames.add(clean + '/' + fn));
    } else {
      filenames.forEach((fn) => targetFilenames.add(fn));
    }

    chrome.downloads.search({ state: 'complete' }, (results) => {
      const existing = new Set();
      results.forEach((d) => {
        if (!d.filename) return;
        const normalized = d.filename.replace(/\\/g, '/');
        const base = normalized.split('/').pop();
        for (const target of targetFilenames) {
          const t = target.replace(/\\/g, '/');
          if (normalized.endsWith('/' + t) || normalized.endsWith(t) || base === t) {
            existing.add(target);
            break;
          }
        }
      });
      console.log('[CGBatch] CHECK_DOWNLOADS targets:', targetFilenames.size, 'existing:', existing.size, Array.from(existing));
      sendResponse({ existing: Array.from(existing) });
    });
    return true;
  }

  if (msg.type === 'DOWNLOAD_IMAGE') {
    const { url, filename, subfolder } = msg;

    // Build a safe relative path inside the Downloads folder.
    // e.g. subfolder "youtube-factory" + "scene-001.png"
    let path = filename;
    if (subfolder && subfolder.trim()) {
      const clean = subfolder.trim().replace(/^\/+|\/+$/g, '');
      path = clean + '/' + filename;
    }

    chrome.downloads.download(
      {
        url: url,
        filename: path,
        conflictAction: 'overwrite',
        saveAs: false
      },
      (downloadId) => {
        if (chrome.runtime.lastError) {
          sendResponse({ ok: false, error: chrome.runtime.lastError.message });
        } else {
          sendResponse({ ok: true, downloadId });
        }
      }
    );
    return true; // keep the message channel open for the async response
  }
});
