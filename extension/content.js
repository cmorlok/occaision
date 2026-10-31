// Content Script for Tutti.ch & Ricardo.ch Smart-Panel
// Injected into ricardo.ch and tutti.ch listing creation wizards.

const browserApi = typeof browser !== "undefined" ? browser : chrome;

// Helper: Convert Data URL to Uint8Array
function dataUrlToUint8Array(dataUrl) {
  const parts = dataUrl.split(",");
  const base64 = parts[1];
  const binaryString = atob(base64);
  const len = binaryString.length;
  const bytes = new Uint8Array(len);
  for (let i = 0; i < len; i++) {
    bytes[i] = binaryString.charCodeAt(i);
  }
  return bytes;
}

// React / Next.js Native Value Setter with Xray Vision unwrap
function setNativeValue(element, value) {
  if (!element) return;
  const target = element.wrappedJSObject || element;
  const win = typeof window !== "undefined" && window.wrappedJSObject ? window.wrappedJSObject : window;

  let prototype = Object.getPrototypeOf(target);
  let descriptor = Object.getOwnPropertyDescriptor(prototype, "value");

  while (prototype && !descriptor) {
    prototype = Object.getPrototypeOf(prototype);
    if (prototype) {
      descriptor = Object.getOwnPropertyDescriptor(prototype, "value");
    }
  }

  if (descriptor && descriptor.set) {
    descriptor.set.call(target, value);
  } else {
    target.value = value;
  }

  target.dispatchEvent(new Event("input", { bubbles: true }));
  target.dispatchEvent(new Event("change", { bubbles: true }));
  target.dispatchEvent(new Event("blur", { bubbles: true }));
}

// Firefox Xray-Safe File Injector for HTMLInputElement and react-dropzone
function injectFilesIntoInput(fileInput, imagePayloads) {
  if (!fileInput || !imagePayloads || imagePayloads.length === 0) return;

  const pageWin = typeof window !== "undefined" && window.wrappedJSObject ? window.wrappedJSObject : window;
  const DataTransferCtor = pageWin.DataTransfer || DataTransfer;
  const FileCtor = pageWin.File || File;
  const dt = new DataTransferCtor();

  for (const img of imagePayloads) {
    const bytes = dataUrlToUint8Array(img.dataUrl);
    const pageBytes = typeof cloneInto === "function" ? cloneInto(bytes, pageWin) : bytes;
    const opts = typeof cloneInto === "function" ? cloneInto({ type: img.mimeType }, pageWin) : { type: img.mimeType };
    const file = new FileCtor([pageBytes], img.filename, opts);
    dt.items.add(file);
  }

  const targetInput = fileInput.wrappedJSObject || fileInput;
  try {
    targetInput.files = dt.files;
  } catch (err) {
    console.warn("Direct input.files assignment warning:", err);
  }

  fileInput.dispatchEvent(new Event("input", { bubbles: true }));
  fileInput.dispatchEvent(new Event("change", { bubbles: true }));

  // Also dispatch synthetic drop event on dropzone container if available
  const dropzone = fileInput.closest("[class*='dropzone'], [class*='upload'], [data-testid*='upload']") || fileInput.parentElement;
  if (dropzone && typeof DragEvent !== "undefined") {
    try {
      const dropEvent = new DragEvent("drop", {
        bubbles: true,
        cancelable: true,
        dataTransfer: dt
      });
      dropzone.dispatchEvent(dropEvent);
    } catch (e) {
      console.warn("Drop event trigger warning:", e);
    }
  }
}

// Platform detection
function isRicardo() {
  return typeof location !== "undefined" && location.hostname.includes("ricardo.ch");
}

function isTutti() {
  return typeof location !== "undefined" && location.hostname.includes("tutti.ch");
}

// Smart-Panel UI Creation & State
let panelElement = null;
let currentDrafts = [];
let activeDraft = null;

function createSmartPanel() {
  if (document.getElementById("ai-listing-smart-panel")) return;

  panelElement = document.createElement("div");
  panelElement.id = "ai-listing-smart-panel";
  panelElement.className = "ai-smart-panel";

  panelElement.innerHTML = `
    <div class="ai-panel-header">
      <span class="ai-panel-title">🤖 Tutti & Ricardo AI</span>
      <div class="ai-panel-header-buttons">
        <button id="ai-ext-collapse-btn" class="ai-btn-icon" title="Minimieren">_</button>
      </div>
    </div>
    <div id="ai-panel-body" class="ai-panel-body">
      <div class="ai-form-group">
        <label for="ai-ext-draft-select">Entwurf wählen:</label>
        <div class="ai-select-row">
          <select id="ai-ext-draft-select"><option value="">Lade Entwürfe...</option></select>
          <button id="ai-ext-refresh-btn" class="ai-btn-small" title="Aktualisieren">🔄</button>
        </div>
      </div>

      <div class="ai-wizard-actions">
        <button id="ai-ext-step1-btn" class="ai-btn ai-btn-primary">
          ▶ Schritt 1: Bilder & Titel einfügen
        </button>
        <button id="ai-ext-step2-btn" class="ai-btn ai-btn-secondary">
          ▶ Schritt 2: Beschreibung, Zustand & Preis
        </button>
      </div>

      <div class="ai-copy-fallbacks">
        <span class="ai-fallback-title">📋 1-Klick-Kopieren (Fallback):</span>
        <div class="ai-fallback-row">
          <span>Titel:</span>
          <button id="ai-copy-title-btn" class="ai-btn-copy">Kopieren</button>
        </div>
        <div class="ai-fallback-row">
          <span>Beschreibung:</span>
          <button id="ai-copy-desc-btn" class="ai-btn-copy">Kopieren</button>
        </div>
        <div class="ai-fallback-row">
          <span>Startpreis:</span>
          <button id="ai-copy-start-btn" class="ai-btn-copy">Kopieren</button>
        </div>
        <div class="ai-fallback-row">
          <span>Sofortkauf/VHB:</span>
          <button id="ai-copy-buynow-btn" class="ai-btn-copy">Kopieren</button>
        </div>
      </div>
    </div>
  `;

  document.body.appendChild(panelElement);
  bindPanelEvents();
  fetchDraftsList();
}

function bindPanelEvents() {
  const collapseBtn = document.getElementById("ai-ext-collapse-btn");
  const panelBody = document.getElementById("ai-panel-body");
  collapseBtn.onclick = () => {
    panelBody.classList.toggle("ai-hidden");
    collapseBtn.textContent = panelBody.classList.contains("ai-hidden") ? "▲" : "_";
  };

  const refreshBtn = document.getElementById("ai-ext-refresh-btn");
  refreshBtn.onclick = fetchDraftsList;

  const draftSelect = document.getElementById("ai-ext-draft-select");
  draftSelect.onchange = () => {
    const selectedId = draftSelect.value;
    activeDraft = currentDrafts.find(d => d.id === selectedId) || null;
  };

  // Step 1: Images & Title
  const step1Btn = document.getElementById("ai-ext-step1-btn");
  step1Btn.onclick = async () => {
    if (!activeDraft) {
      alert("Bitte wähle zuerst einen Entwurf aus.");
      return;
    }
    step1Btn.disabled = true;
    step1Btn.textContent = "⏳ Lade Bilder & fülle Titel...";
    try {
      await executeStep1(activeDraft);
    } finally {
      step1Btn.disabled = false;
      step1Btn.textContent = "▶ Schritt 1: Bilder & Titel einfügen";
    }
  };

  // Step 2: Description & Price
  const step2Btn = document.getElementById("ai-ext-step2-btn");
  step2Btn.onclick = () => {
    if (!activeDraft) {
      alert("Bitte wähle zuerst einen Entwurf aus.");
      return;
    }
    executeStep2(activeDraft);
  };

  // 1-Click Copy fallbacks (navigator.clipboard)
  document.getElementById("ai-copy-title-btn").onclick = () => {
    if (!activeDraft) return;
    const title = isRicardo() ? activeDraft.ricardo.title : activeDraft.tutti.title;
    navigator.clipboard.writeText(title || "");
  };

  document.getElementById("ai-copy-desc-btn").onclick = () => {
    if (!activeDraft) return;
    const desc = isRicardo() ? activeDraft.ricardo.description : activeDraft.tutti.description;
    navigator.clipboard.writeText(desc || "");
  };

  document.getElementById("ai-copy-start-btn").onclick = () => {
    if (!activeDraft) return;
    const price = isRicardo() ? activeDraft.ricardo.start_price_chf : activeDraft.tutti.price_vhb_chf;
    navigator.clipboard.writeText(String(price || 1));
  };

  document.getElementById("ai-copy-buynow-btn").onclick = () => {
    if (!activeDraft) return;
    const price = isRicardo() ? activeDraft.ricardo.buynow_price_chf : activeDraft.tutti.price_vhb_chf;
    navigator.clipboard.writeText(String(price || 10));
  };
}

function fetchDraftsList() {
  const draftSelect = document.getElementById("ai-ext-draft-select");
  if (!draftSelect) return;
  draftSelect.innerHTML = '<option value="">Lade...</option>';

  browserApi.runtime.sendMessage({ action: "LIST_DRAFTS" }, response => {
    if (response && response.ok && response.drafts) {
      currentDrafts = response.drafts;
      draftSelect.innerHTML = "";
      if (currentDrafts.length === 0) {
        draftSelect.innerHTML = '<option value="">Keine Entwürfe vorhanden</option>';
        return;
      }
      currentDrafts.forEach(d => {
        const opt = document.createElement("option");
        opt.value = d.id;
        opt.textContent = `${d.identified_product || d.user_notes || d.id} (${d.status})`;
        draftSelect.appendChild(opt);
      });
      activeDraft = currentDrafts[0];
    } else {
      draftSelect.innerHTML = '<option value="">Fehler beim Laden (Backend online?)</option>';
    }
  });
}

async function executeStep1(draft) {
  // 1. Fetch images through background worker (bypassing CORS)
  const imagesResponse = await new Promise(resolve => {
    browserApi.runtime.sendMessage({ action: "FETCH_DRAFT_IMAGES", draftId: draft.id }, resolve);
  });

  if (imagesResponse && imagesResponse.ok && imagesResponse.images && imagesResponse.images.length > 0) {
    const fileInput = document.querySelector('input[type="file"]');
    if (fileInput) {
      injectFilesIntoInput(fileInput, imagesResponse.images);
    }
  }

  // 2. Inject Title
  const titleVal = isRicardo() ? draft.ricardo.title : draft.tutti.title;
  const titleInput = document.querySelector(
    'input[name*="title" i], input[id*="title" i], input[placeholder*="titel" i], input[data-testid*="title" i]'
  );
  if (titleInput) {
    setNativeValue(titleInput, titleVal);
  }
}

function executeStep2(draft) {
  const descVal = isRicardo() ? draft.ricardo.description : draft.tutti.description;
  const descEl = document.querySelector(
    'textarea[name*="description" i], textarea[id*="description" i], textarea[placeholder*="beschreibung" i], textarea[data-testid*="description" i]'
  );
  if (descEl) {
    setNativeValue(descEl, descVal);
  }

  // Set prices
  if (isRicardo()) {
    const startPriceInput = document.querySelector('input[name*="startPrice" i], input[id*="start-price" i], input[data-testid*="start-price" i]');
    if (startPriceInput) {
      setNativeValue(startPriceInput, draft.ricardo.start_price_chf);
    }
    const buynowPriceInput = document.querySelector('input[name*="buyNowPrice" i], input[id*="buy-now-price" i], input[data-testid*="buy-now-price" i]');
    if (buynowPriceInput) {
      setNativeValue(buynowPriceInput, draft.ricardo.buynow_price_chf);
    }
  } else {
    const priceInput = document.querySelector('input[name*="price" i], input[id*="price" i], input[data-testid*="price" i]');
    if (priceInput) {
      setNativeValue(priceInput, draft.tutti.price_vhb_chf);
    }
  }
}

// Initialize on page ready
if (typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", createSmartPanel);
  } else {
    createSmartPanel();
  }
}

// Export for Node/test environment
if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    setNativeValue,
    injectFilesIntoInput,
    dataUrlToUint8Array,
    createSmartPanel,
    isRicardo,
    isTutti,
  };
}
