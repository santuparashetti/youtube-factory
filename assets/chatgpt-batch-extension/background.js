// Background service worker — handles image downloads via chrome.downloads API.
// Content scripts can't call chrome.downloads directly, so they message us.

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
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
