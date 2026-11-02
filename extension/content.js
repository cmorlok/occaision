// Content Script for Seller Assistant Smart-Panel
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
function isRicardo(hostname) {
  const h = hostname || (typeof location !== "undefined" ? location.hostname : "");
  return h.includes("ricardo.ch");
}

function isTutti(hostname) {
  const h = hostname || (typeof location !== "undefined" ? location.hostname : "");
  return h.includes("tutti.ch");
}

function isEbayDE(hostname) {
  const h = hostname || (typeof location !== "undefined" ? location.hostname : "");
  return h.includes("ebay.de");
}

function isKleinanzeigen(hostname) {
  const h = hostname || (typeof location !== "undefined" ? location.hostname : "");
  return h.includes("kleinanzeigen.de");
}

function isLocalDashboard(hostname) {
  const h = hostname || (typeof location !== "undefined" ? location.hostname : "");
  return h === "127.0.0.1" || h === "localhost" || h.includes("127.0.0.1") || h.includes("localhost");
}

function detectPlatform(hostname) {
  if (isRicardo(hostname)) return "ricardo";
  if (isTutti(hostname)) return "tutti";
  if (isEbayDE(hostname)) return "ebay_de";
  if (isKleinanzeigen(hostname)) return "kleinanzeigen";
  if (isLocalDashboard(hostname)) return "dashboard";
  return "unknown";
}

function getPlatformData(draft, platform) {
  if (!draft) return {};
  const p = platform || detectPlatform();
  if (p === "ricardo") {
    return {
      title: draft.ricardo ? draft.ricardo.title : "",
      description: draft.ricardo ? draft.ricardo.description : "",
      condition: draft.ricardo ? draft.ricardo.condition : "",
      startPrice: draft.ricardo ? draft.ricardo.start_price_chf : 1.0,
      buyNowPrice: draft.ricardo ? draft.ricardo.buynow_price_chf : 10.0,
      currency: "CHF",
      priceType: "auction"
    };
  } else if (p === "tutti") {
    return {
      title: draft.tutti ? draft.tutti.title : "",
      description: draft.tutti ? draft.tutti.description : "",
      condition: draft.tutti ? draft.tutti.condition : "",
      startPrice: null,
      buyNowPrice: draft.tutti ? draft.tutti.price_vhb_chf : 10.0,
      currency: "CHF",
      priceType: "vb"
    };
  } else if (p === "ebay_de") {
    return {
      title: draft.ebay_de ? draft.ebay_de.title : "",
      description: draft.ebay_de ? draft.ebay_de.description : "",
      condition: draft.ebay_de ? draft.ebay_de.condition : "",
      startPrice: draft.ebay_de ? draft.ebay_de.start_price_eur : 1.0,
      buyNowPrice: draft.ebay_de ? draft.ebay_de.buynow_price_eur : 10.0,
      currency: "EUR",
      priceType: draft.ebay_de ? draft.ebay_de.offer_type : "auction"
    };
  } else if (p === "kleinanzeigen") {
    return {
      title: draft.kleinanzeigen ? draft.kleinanzeigen.title : "",
      description: draft.kleinanzeigen ? draft.kleinanzeigen.description : "",
      condition: draft.kleinanzeigen ? draft.kleinanzeigen.condition : "",
      startPrice: null,
      buyNowPrice: draft.kleinanzeigen ? draft.kleinanzeigen.price_eur : 10.0,
      currency: "EUR",
      priceType: draft.kleinanzeigen ? draft.kleinanzeigen.price_type : "vb"
    };
  }
  return {
    title: "",
    description: "",
    condition: "",
    startPrice: 1.0,
    buyNowPrice: 10.0,
    currency: "CHF",
    priceType: "auction"
  };
}

function setDescriptionValue(value, rootDoc) {
  if (typeof value !== "string") value = value || "";
  const doc = rootDoc || (typeof document !== "undefined" ? document : null);
  if (!doc) return false;

  // 1. Textarea search
  const textarea = doc.querySelector(
    '#pstad-descrptn, #pstad-descr, textarea[name*="description" i], textarea[name="body"], textarea[id*="description" i], textarea[placeholder*="beschreibung" i], textarea[data-testid*="description" i]'
  );
  if (textarea) {
    setNativeValue(textarea, value);
    return true;
  }

  // 2. Same-origin iframe search (e.g. eBay.de)
  const iframes = doc.querySelectorAll(
    'iframe.ux-action-menu__iframe, iframe[id*="desc" i], iframe[title*="Beschreibung" i], iframe[title*="description" i]'
  );
  for (const iframe of iframes) {
    try {
      const iframeDoc = iframe.contentDocument || (iframe.contentWindow && iframe.contentWindow.document);
      if (iframeDoc) {
        const editable = iframeDoc.querySelector('.editable-text-area, [contenteditable="true"], body');
        if (editable) {
          const htmlVal = value.replace(/\n/g, "<br>");
          editable.innerHTML = htmlVal;
          editable.dispatchEvent(new Event("input", { bubbles: true }));
          editable.dispatchEvent(new Event("change", { bubbles: true }));
          editable.dispatchEvent(new Event("blur", { bubbles: true }));
          return true;
        }
      }
    } catch (e) {
      console.warn("Could not access description iframe", e);
    }
  }

  // 3. Direct contenteditable editor in document
  const contentEditable = doc.querySelector('[contenteditable="true"]');
  if (contentEditable) {
    contentEditable.textContent = value;
    contentEditable.dispatchEvent(new Event("input", { bubbles: true }));
    contentEditable.dispatchEvent(new Event("blur", { bubbles: true }));
    return true;
  }

  return false;
}

// Smart-Panel UI Creation & State
let panelElement = null;
let currentDrafts = [];
let activeDraft = null;

function createSmartPanel() {
  if (!isRicardo() && !isTutti() && !isEbayDE() && !isKleinanzeigen()) return;
  if (document.getElementById("ai-listing-smart-panel")) return;

  panelElement = document.createElement("div");
  panelElement.id = "ai-listing-smart-panel";
  panelElement.className = "ai-smart-panel";

  panelElement.innerHTML = `
    <div class="ai-panel-header">
      <span class="ai-panel-title">🤖 Seller Assistant</span>
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
    const data = getPlatformData(activeDraft);
    navigator.clipboard.writeText(data.title || "");
  };

  document.getElementById("ai-copy-desc-btn").onclick = () => {
    if (!activeDraft) return;
    const data = getPlatformData(activeDraft);
    navigator.clipboard.writeText(data.description || "");
  };

  document.getElementById("ai-copy-start-btn").onclick = () => {
    if (!activeDraft) return;
    const data = getPlatformData(activeDraft);
    navigator.clipboard.writeText(String(data.startPrice || 1));
  };

  document.getElementById("ai-copy-buynow-btn").onclick = () => {
    if (!activeDraft) return;
    const data = getPlatformData(activeDraft);
    navigator.clipboard.writeText(String(data.buyNowPrice || 10));
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
  const data = getPlatformData(draft);
  const titleInput = document.querySelector(
    '#postad-title, #pstad-title, input[name="title"], input[name="pstad-title"], input[name="subject"], input[name*="title" i], input[id*="title" i], input[aria-label*="Titel" i], input[placeholder*="titel" i], input[data-testid*="title" i]'
  );
  if (titleInput && data.title) {
    setNativeValue(titleInput, data.title);
  }
}

function executeStep2(draft) {
  const data = getPlatformData(draft);
  const platform = detectPlatform();

  // Description
  if (data.description) {
    setDescriptionValue(data.description);
  }

  // Condition
  const condEl = document.querySelector(
    'select[name*="condition" i], select[id*="condition" i], select[data-testid*="condition" i], input[name*="condition" i]'
  );
  if (condEl && data.condition) {
    setNativeValue(condEl, data.condition);
  }

  // Prices
  if (platform === "ricardo" || platform === "ebay_de") {
    const startPriceInput = document.querySelector(
      'input[name*="startPrice" i], input[id*="start-price" i], input[aria-label*="Startpreis" i], input[data-testid*="start-price" i]'
    );
    if (startPriceInput && data.startPrice !== null && data.startPrice !== undefined) {
      setNativeValue(startPriceInput, data.startPrice);
    }
    const buynowPriceInput = document.querySelector(
      'input[name*="buyNowPrice" i], input[name*="buyItNowPrice" i], input[id*="buy-now-price" i], input[aria-label*="Sofort-Kaufen" i], input[data-testid*="buy-now-price" i], input[name="price"]'
    );
    if (buynowPriceInput && data.buyNowPrice !== null && data.buyNowPrice !== undefined) {
      setNativeValue(buynowPriceInput, data.buyNowPrice);
    }
  } else {
    // tutti or kleinanzeigen
    const priceInput = document.querySelector(
      '#pstad-price, input[name="price"], input[name*="price" i], input[id*="price" i], input[data-testid*="price" i]'
    );
    if (priceInput && data.buyNowPrice !== null && data.buyNowPrice !== undefined) {
      setNativeValue(priceInput, data.buyNowPrice);
    }
    if (platform === "kleinanzeigen") {
      const priceTypeEl = document.querySelector('select[name="priceType"], input[name="priceType"], select[id*="price-type" i]');
      if (priceTypeEl && data.priceType) {
        setNativeValue(priceTypeEl, data.priceType);
      }
    }
  }
}

// Setup Dashboard Bridge on http://127.0.0.1:8000 / http://localhost:8000
function sendToPage(payloadObj) {
  if (typeof window === "undefined") return;
  try {
    // Send as JSON string to bypass Firefox Xray compartment restrictions on Object properties
    window.postMessage(JSON.stringify(payloadObj), "*");
  } catch (e) {
    console.warn("[Seller Assistant] postMessage warning:", e);
  }
}

function setupDashboardBridge() {
  if (typeof document !== "undefined" && document.documentElement) {
    document.documentElement.dataset.sellerAssistantExtension = "installed";
  }
  if (typeof window === "undefined") return;

  console.log("[Seller Assistant] Dashboard Content-Script Bridge aktiv auf", location.href);

  window.addEventListener("message", event => {
    if (!event || !event.data) return;

    let msg = event.data;
    if (typeof msg === "string") {
      try {
        msg = JSON.parse(msg);
      } catch (_) {
        return;
      }
    }
    if (!msg || typeof msg !== "object") return;

    if (msg.type === "SELLER_ASSISTANT_PING") {
      sendToPage({ type: "SELLER_ASSISTANT_PONG" });
      return;
    }

    if (msg.type === "SELLER_ASSISTANT_SCRAPE_PRICES") {
      const reqId = msg.requestId;
      const query = msg.query || "";
      const eurToChfRate = msg.eurToChfRate || 0.94;
      const enabledSources = Array.isArray(msg.enabledSources) ? msg.enabledSources : null;
      const keepTabsOpen = Boolean(msg.keepTabsOpen);

      console.log(`[Seller Assistant] Content-Script empfängt Scrape-Anfrage (${reqId}) für '${query}' (enabled: ${enabledSources ? enabledSources.join(',') : 'all'}, keepTabsOpen: ${keepTabsOpen})`);

      browserApi.runtime.sendMessage(
        {
          action: "SCRAPE_ALL_PRICE_SOURCES",
          requestId: reqId,
          query: query,
          eurToChfRate: eurToChfRate,
          enabledSources: enabledSources,
          keepTabsOpen: keepTabsOpen,
        },
        response => {
          if (response && response.sources && response.sources.ebay_de_sold && response.sources.ebay_de_sold.items) {
            const items = response.sources.ebay_de_sold.items;
            console.group(`[Seller Assistant] [Content-Bridge] eBay DE verkaufte Artikel (${items.length} Treffer):`);
            items.forEach((it, idx) => {
              console.log(`  [#${idx + 1}] ${it.price} € | Zustand: [${it.condition}] | "${it.title}"`);
            });
            console.groupEnd();
            if (typeof console.table === "function") {
              try {
                console.table(
                  items.map((it, idx) => ({
                    "#": idx + 1,
                    "Preis (€)": it.price,
                    "Zustand": it.condition,
                    "Titel": it.title,
                  }))
                );
              } catch (_) {}
            }
          }
          if (response && response.sources && response.sources.kleinanzeigen && response.sources.kleinanzeigen.items) {
            const kaItems = response.sources.kleinanzeigen.items;
            console.group(`[Seller Assistant] [Content-Bridge] Kleinanzeigen Artikel (${kaItems.length} Treffer):`);
            kaItems.forEach((it, idx) => {
              console.log(`  [#${idx + 1}] ${it.price} € | Zustand: [${it.condition || "Gebraucht"}] | "${it.title}"`);
            });
            console.groupEnd();
            if (typeof console.table === "function") {
              try {
                console.table(
                  kaItems.map((it, idx) => ({
                    "#": idx + 1,
                    "Preis (€)": it.price,
                    "Zustand": it.condition || "Gebraucht",
                    "Titel": it.title,
                  }))
                );
              } catch (_) {}
            }
          }
          if (response && response.sources && response.sources.idealo && response.sources.idealo.items) {
            const idealoItems = response.sources.idealo.items;
            console.group(`[Seller Assistant] [Content-Bridge] Idealo Neupreise (${idealoItems.length} Treffer):`);
            idealoItems.forEach((it, idx) => {
              console.log(`  [#${idx + 1}] ${it.price} € | Zustand: [${it.condition || "Neu"}] | "${it.title}"`);
            });
            console.groupEnd();
            if (typeof console.table === "function") {
              try {
                console.table(
                  idealoItems.map((it, idx) => ({
                    "#": idx + 1,
                    "Preis (€)": it.price,
                    "Zustand": it.condition || "Neu",
                    "Titel": it.title,
                  }))
                );
              } catch (_) {}
            }
          }
          if (response && response.sources && response.sources.toppreise && response.sources.toppreise.items) {
            const toppreiseItems = response.sources.toppreise.items;
            console.group(`[Seller Assistant] [Content-Bridge] Toppreise Neupreise (${toppreiseItems.length} Treffer):`);
            toppreiseItems.forEach((it, idx) => {
              console.log(`  [#${idx + 1}] ${it.price} CHF | Zustand: [${it.condition || "Neu"}] | "${it.title}"`);
            });
            console.groupEnd();
            if (typeof console.table === "function") {
              try {
                console.table(
                  toppreiseItems.map((it, idx) => ({
                    "#": idx + 1,
                    "Preis (CHF)": it.price,
                    "Zustand": it.condition || "Neu",
                    "Titel": it.title,
                  }))
                );
              } catch (_) {}
            }
          }
          if (response && response.sources && response.sources.digitec && response.sources.digitec.items) {
            const digitecItems = response.sources.digitec.items;
            console.group(`[Seller Assistant] [Content-Bridge] Galaxus/Digitec Neupreise (${digitecItems.length} Treffer):`);
            digitecItems.forEach((it, idx) => {
              console.log(`  [#${idx + 1}] ${it.price} CHF | Zustand: [${it.condition || "Neu"}] | "${it.title}"`);
            });
            console.groupEnd();
            if (typeof console.table === "function") {
              try {
                console.table(
                  digitecItems.map((it, idx) => ({
                    "#": idx + 1,
                    "Preis (CHF)": it.price,
                    "Zustand": it.condition || "Neu",
                    "Titel": it.title,
                  }))
                );
              } catch (_) {}
            }
          }
          const payload = Object.assign(
            {
              type: "SELLER_ASSISTANT_SCRAPE_PRICES_RESULT",
              requestId: reqId,
            },
            response || { ok: false, error: "Keine Antwort vom Extension Background-Worker" }
          );
          sendToPage(payload);
        }
      );
    }
  });
}

// Support tab extraction message fallback for background scraping
if (typeof browserApi !== "undefined" && browserApi.runtime && browserApi.runtime.onMessage) {
  browserApi.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg && msg.action === "EXTRACT_PAGE_DATA") {
      const html = document.documentElement ? document.documentElement.outerHTML : (document.body ? document.body.innerText : "");
      const currentUrl = location.href || "";

      const idealoCards = [];
      const firstPriceEl = document.querySelector('[class*="sr-detailedPriceInfo__price"]');
      if (firstPriceEl) {
        const firstTitleEl = document.querySelector('[class*="productSummary__title"], [class*="sr-productSummary__title"]');
        idealoCards.push({
          title: firstTitleEl ? firstTitleEl.textContent.trim() : "Idealo Top-Ergebnis",
          rawPrice: firstPriceEl.textContent.trim(),
        });
      }

      const toppreiseCards = [];
      let tpSingleTitle = "";
      let tpSinglePrice = "";
      const jsonLdScripts = document.querySelectorAll('script[type="application/ld+json"]');
      for (const s of jsonLdScripts) {
        try {
          const d = JSON.parse(s.textContent || "");
          if (d && d["@type"] === "Product") {
            tpSingleTitle = d.name || "";
            if (d.offers) {
              tpSinglePrice = String(d.offers.lowPrice ?? d.offers.price ?? "");
            }
            break;
          }
        } catch (_) {}
      }
      if (!tpSingleTitle) {
        const h1 = document.querySelector("h1");
        if (h1 && (location.href.includes("/preisvergleich/") || location.href.includes("toppreise.ch"))) {
          tpSingleTitle = h1.textContent.trim();
        }
      }
      if (!tpSinglePrice && tpSingleTitle) {
        const pEl = document.querySelector(".Plugin_Price");
        if (pEl) tpSinglePrice = pEl.textContent.trim();
      }
      if (tpSingleTitle && tpSinglePrice) {
        toppreiseCards.push({
          title: tpSingleTitle,
          rawPrice: tpSinglePrice,
        });
      } else {
        const mainEl = document.querySelector("main") || document;
        const firstProdEl = mainEl.querySelector(".Plugin_Product");
        if (firstProdEl) {
          const titleEl = firstProdEl.querySelector('a.bold, a[href*="/preisvergleich/"], .product-name');
          const priceEl = firstProdEl.querySelector('.Plugin_Price');
          if (priceEl) {
            toppreiseCards.push({
              title: titleEl ? titleEl.textContent.trim() : "Toppreise Produkt",
              rawPrice: priceEl.textContent.trim(),
            });
          }
        }
      }

      const priceNodes = Array.from(
        document.querySelectorAll(
          '.s-item__price, .s-card__price, .aditem-main--middle--price-shipping--price, [class*="sr-detailedPriceInfo__price"], [class*="Plugin_Price"], [class*="price" i], [data-testid*="price" i]'
        )
      )
        .slice(0, 40)
        .map(el => (el.textContent || "").trim())
        .filter(Boolean);

      const digitecCards = [];
      let dgSingleTitle = "";
      let dgSinglePrice = "";
      const dgJsonLdScripts = document.querySelectorAll('script[type="application/ld+json"]');
      for (const s of dgJsonLdScripts) {
        try {
          const d = JSON.parse(s.textContent || "");
          if (d && d["@type"] === "Product") {
            dgSingleTitle = d.name || "";
            if (d.offers) {
              dgSinglePrice = String(d.offers.price ?? d.offers.lowPrice ?? "");
            }
            break;
          }
        } catch (_) {}
      }
      if (!dgSingleTitle) {
        const h1 = document.querySelector("h1");
        if (h1 && location.href.includes("/product/")) {
          dgSingleTitle = h1.textContent.trim();
        }
      }
      if (!dgSinglePrice && dgSingleTitle) {
        const pEl = document.querySelector('[data-test*="price" i], strong[class*="price" i], span[class*="price" i]');
        if (pEl) dgSinglePrice = pEl.textContent.trim();
      }
      if (dgSingleTitle && dgSinglePrice) {
        digitecCards.push({
          title: dgSingleTitle,
          rawPrice: dgSinglePrice,
        });
      } else {
        const firstArt = document.querySelector("article");
        if (firstArt) {
          let title = "";
          const titleLink = firstArt.querySelector('a[aria-label][href*="/product/"]');
          if (titleLink && titleLink.getAttribute("aria-label")) {
            title = titleLink.getAttribute("aria-label").trim();
          }
          if (!title) {
            const img = firstArt.querySelector('img[alt*="Produktbild"]');
            if (img && img.getAttribute("alt")) {
              title = img.getAttribute("alt").replace(/^Produktbild\s+/i, "").trim();
            }
          }
          if (!title) {
            const p = firstArt.querySelector("p");
            if (p) title = p.textContent.trim();
          }
          if (!title) title = "Galaxus Produkt";

          let rawPrice = "";
          for (const el of firstArt.querySelectorAll("span, div, p, strong")) {
            const t = el.textContent || "";
            if (t.includes(".–") || t.includes(".-") || t.includes("CHF")) {
              const m = t.match(/(?:CHF|Fr\.)?\s*(\d{1,5}(?:['’.,\s\u00a0\u202f]\d{2,3})*(?:\.–|\.-|--|,\d{2}|\.\d{2}))/i) ||
                        t.match(/(\d{1,5}(?:['’.,\s\u00a0\u202f]\d{2,3})*(?:\.–|\.-|--))/i);
              if (m) {
                rawPrice = m[1].trim();
                break;
              }
            }
          }
          if (!rawPrice) {
            const priceText = firstArt.textContent || "";
            const m = priceText.match(/(?:CHF|Fr\.)[\s\S]*?(\d{1,5}(?:['’.,\s\u00a0\u202f]\d{2,3})*(?:\.–|\.-|--|,\d{2}|\.\d{2}))/i) ||
                      priceText.match(/(\d{1,5}(?:['’.,\s\u00a0\u202f]\d{2,3})*(?:\.–|\.-|--))/i);
            if (m) rawPrice = m[1].trim();
          }
          if (rawPrice) {
            digitecCards.push({
              title: title.trim(),
              rawPrice: rawPrice.trim(),
            });
          }
        }
      }

      sendResponse({ html, currentUrl, priceNodes, idealoCards, toppreiseCards, digitecCards });
      return true;
    }
    return false;
  });
}

// Initialize on page ready
if (typeof document !== "undefined") {
  const initExt = () => {
    if (isLocalDashboard()) {
      setupDashboardBridge();
    } else {
      createSmartPanel();
    }
  };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initExt);
  } else {
    initExt();
  }
}

// Export for Node/test environment
if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    setNativeValue,
    setDescriptionValue,
    injectFilesIntoInput,
    dataUrlToUint8Array,
    createSmartPanel,
    setupDashboardBridge,
    isRicardo,
    isTutti,
    isEbayDE,
    isKleinanzeigen,
    isLocalDashboard,
    detectPlatform,
    getPlatformData,
  };
}
