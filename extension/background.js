// Background Service Worker for Seller Assistant
// Bypasses CORS and CSP by executing HTTP calls inside the WebExtension privileged context.

const browserApi = typeof browser !== "undefined" ? browser : chrome;
const BACKEND_BASE = "http://127.0.0.1:8000";

// Firefox MV3 Host Permissions prompt on action button click
if (browserApi.action && browserApi.action.onClicked) {
  browserApi.action.onClicked.addListener(async () => {
    try {
      if (browserApi.permissions && browserApi.permissions.request) {
        await browserApi.permissions.request({
          origins: [
            "http://127.0.0.1:8000/*",
            "http://localhost:8000/*",
            "*://*.ricardo.ch/*",
            "*://*.tutti.ch/*"
          ]
        });
      }
    } catch (err) {
      console.error("Permission request failed", err);
    }
  });
}

function arrayBufferToBase64DataUrl(buffer, mimeType = "image/jpeg") {
  let binary = "";
  const bytes = new Uint8Array(buffer);
  const len = bytes.byteLength;
  for (let i = 0; i < len; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  const base64 = btoa(binary);
  return `data:${mimeType};base64,${base64}`;
}

browserApi.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "LIST_DRAFTS") {
    fetch(`${BACKEND_BASE}/api/drafts`)
      .then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then(drafts => sendResponse({ ok: true, drafts }))
      .catch(err => sendResponse({ ok: false, error: err.message }));
    return true; // asynchronous response
  }

  if (request.action === "GET_DRAFT") {
    fetch(`${BACKEND_BASE}/api/drafts/${request.draftId}`)
      .then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then(draft => sendResponse({ ok: true, draft }))
      .catch(err => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (request.action === "FETCH_DRAFT_IMAGES") {
    fetch(`${BACKEND_BASE}/api/drafts/${request.draftId}`)
      .then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then(async draft => {
        const imagePayloads = [];
        for (const img of draft.images || []) {
          const imgUrl = `${BACKEND_BASE}/api/drafts/${draft.id}/images/${img.id}/active`;
          const imgRes = await fetch(imgUrl);
          if (!imgRes.ok) continue;
          const buf = await imgRes.arrayBuffer();
          const dataUrl = arrayBufferToBase64DataUrl(buf, "image/jpeg");
          imagePayloads.push({
            id: img.id,
            filename: `${img.id}_${img.active_mode}.jpg`,
            mimeType: "image/jpeg",
            dataUrl: dataUrl
          });
        }
        sendResponse({ ok: true, images: imagePayloads });
      })
      .catch(err => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  return false;
});
