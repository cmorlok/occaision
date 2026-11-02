// Background Service Worker for Seller Assistant
// Bypasses CORS and CSP by executing HTTP calls and hybrid price scraping inside the WebExtension privileged context.

const browserApi =
  typeof browser !== "undefined"
    ? browser
    : typeof chrome !== "undefined"
    ? chrome
    : null;
const BACKEND_BASE = "http://127.0.0.1:8000";

const ALL_HOST_ORIGINS = [
  "http://127.0.0.1:8000/*",
  "http://localhost:8000/*",
  "*://*.ricardo.ch/*",
  "*://*.tutti.ch/*",
  "*://*.ebay.de/*",
  "*://*.kleinanzeigen.de/*",
  "*://*.idealo.de/*",
  "*://*.toppreise.ch/*",
  "*://*.digitec.ch/*",
];

// Firefox MV3 Host Permissions prompt on action button click
if (browserApi && browserApi.action && browserApi.action.onClicked) {
  browserApi.action.onClicked.addListener(async () => {
    try {
      if (browserApi.permissions && browserApi.permissions.request) {
        await browserApi.permissions.request({
          origins: ALL_HOST_ORIGINS,
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

function buildVerificationLinks(query) {
  const q = encodeURIComponent((query || "").trim()).replace(/%20/g, "+");
  return {
    ebay_sold_url: `https://www.ebay.de/sch/i.html?_nkw=${q}&LH_Sold=1&LH_Complete=1&LH_ItemCondition=3000`,
    kleinanzeigen_search_url: `https://www.kleinanzeigen.de/s-${q}/k0`,
    idealo_url: `https://www.idealo.de/preisvergleich/MainSearchProductCategory.html?q=${q}`,
    ricardo_search_url: `https://www.ricardo.ch/de/s/${q}`,
    toppreise_url: `https://www.toppreise.ch/produktsuche?q=${q}`,
    digitec_url: `https://www.digitec.ch/de/search?q=${q}`,
  };
}

function parsePriceText(text) {
  if (!text || typeof text !== "string") return null;
  const lower = text.toLowerCase();
  if (lower.includes("bis") || lower.includes(" to ") || lower.includes(" - ")) {
    return null;
  }
  // Normalize Swiss apostrophe thousands separators (e.g. 1'250.00 or 419.–)
  const cleaned = text
    .replace(/['’]/g, "")
    .replace(/\.–|\.-|--/g, ".00");
  const match = cleaned.match(/(\d+(?:[.,]\d+)*)/);
  if (!match) return null;

  let numStr = match[1];
  if (numStr.includes(",") && numStr.includes(".")) {
    if (numStr.lastIndexOf(",") > numStr.lastIndexOf(".")) {
      numStr = numStr.replace(/\./g, "").replace(",", ".");
    } else {
      numStr = numStr.replace(/,/g, "");
    }
  } else if (numStr.includes(",")) {
    numStr = numStr.replace(",", ".");
  }

  const val = parseFloat(numStr);
  if (isNaN(val) || val < 1.0 || val > 100000) return null;
  return Math.round(val * 100) / 100;
}

function extractJsonLdPrices(html) {
  const prices = [];
  const scriptRegex = /<script[^>]*type=["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi;
  let match;
  while ((match = scriptRegex.exec(html)) !== null) {
    try {
      const data = JSON.parse(match[1].trim());
      const visit = obj => {
        if (!obj || typeof obj !== "object") return;
        if (Array.isArray(obj)) {
          obj.forEach(visit);
          return;
        }
        for (const key of ["price", "lowPrice", "highPrice"]) {
          if (obj[key] !== undefined && obj[key] !== null) {
            const p = parsePriceText(String(obj[key]));
            if (p !== null) prices.push(p);
          }
        }
        for (const v of Object.values(obj)) {
          if (v && typeof v === "object") visit(v);
        }
      };
      visit(data);
    } catch (_) {
      // ignore malformed JSON-LD blocks
    }
  }
  return prices;
}

function extractPricesFromHtml(sourceId, html) {
  if (!html || typeof html !== "string") return [];

  // Detect anti-bot challenge pages
  if (
    html.includes("splashui/challenge") ||
    html.includes("Pardon Our Interruption") ||
    html.includes("cf-chl-bypass") ||
    html.includes("captcha-delivery.com")
  ) {
    return [];
  }

  const prices = [];

  if (sourceId === "ebay_de_sold") {
    // Parse eBay .s-item / .s-card blocks
    const itemBlocks = html.split(/class=["'][^"']*s-(?:item|card)\b/i).slice(1);
    for (const block of itemBlocks) {
      if (block.includes("Shop on eBay")) continue;
      const priceMatch = block.match(
        /class=["'][^"']*s-(?:item|card)__price[^"']*["'][^>]*>([\s\S]*?)<\/(?:span|div)>/i
      );
      if (priceMatch) {
        const rawText = priceMatch[1].replace(/<[^>]+>/g, " ").trim();
        const val = parsePriceText(rawText);
        if (val !== null) prices.push(val);
      }
    }
    return prices.slice(0, 30);
  }

  // Try JSON-LD structured product/offer data first
  const ldPrices = extractJsonLdPrices(html);
  prices.push(...ldPrices);

  if (sourceId === "kleinanzeigen") {
    const kaRegex = /aditem-main--middle--price-shipping--price[^>]*>([\s\S]*?)<\/p>/gi;
    let m;
    while ((m = kaRegex.exec(html)) !== null) {
      const rawText = m[1].replace(/<[^>]+>/g, " ").trim();
      const val = parsePriceText(rawText);
      if (val !== null) prices.push(val);
    }
  } else if (sourceId === "idealo") {
    const idealoRegex = /(?:ab\s*)?(\d{1,5}(?:[.,]\d{2}))\s*€/gi;
    let m;
    while ((m = idealoRegex.exec(html)) !== null) {
      const val = parsePriceText(m[1]);
      if (val !== null) prices.push(val);
    }
  } else if (sourceId === "ricardo") {
    const ricJsonRegex = /"(?:buyNowPrice|currentPrice|startPrice)"\s*:\s*(\d+(?:\.\d+)?)/gi;
    let m;
    while ((m = ricJsonRegex.exec(html)) !== null) {
      const val = parsePriceText(m[1]);
      if (val !== null) prices.push(val);
    }
  } else if (sourceId === "toppreise") {
    const tpRegex = /(?:CHF|Fr\.)\s*(\d{1,5}(?:['’.,]\d{2,3})*)/gi;
    let m;
    while ((m = tpRegex.exec(html)) !== null) {
      const val = parsePriceText(m[1]);
      if (val !== null) prices.push(val);
    }
  } else if (sourceId === "digitec") {
    const digJsonRegex = /"amountIncl"\s*:\s*(\d+(?:\.\d+)?)/gi;
    let m;
    while ((m = digJsonRegex.exec(html)) !== null) {
      const val = parsePriceText(m[1]);
      if (val !== null) prices.push(val);
    }
    const digChfRegex = /(?:CHF|Fr\.)\s*(\d{1,5}(?:['’.,]\d{2}|['’.,]–|\.--)?)/gi;
    while ((m = digChfRegex.exec(html)) !== null) {
      const val = parsePriceText(m[1]);
      if (val !== null) prices.push(val);
    }
  }

  return prices.slice(0, 30);
}

function computeSourceStats(sourceConfig, rawPrices, url, method, eurToChfRate = 0.94) {
  const valid = (rawPrices || []).filter(p => typeof p === "number" && !isNaN(p) && p > 0);
  if (valid.length === 0) {
    return {
      source_id: sourceConfig.id,
      label: sourceConfig.label,
      currency: sourceConfig.currency,
      sample_count: 0,
      min_price: null,
      max_price: null,
      median_price: null,
      median_chf: null,
      url: url,
      method: method,
    };
  }

  const sorted = [...valid].sort((a, b) => a - b);
  const minPrice = Math.round(sorted[0] * 100) / 100;
  const maxPrice = Math.round(sorted[sorted.length - 1] * 100) / 100;
  const sampleCount = sorted.length;

  let calc = sorted;
  if (sampleCount >= 4) {
    const trimK = Math.max(1, Math.floor(sampleCount * 0.1));
    if (calc.length - 2 * trimK >= 1) {
      calc = calc.slice(trimK, calc.length - trimK);
    }
  }

  const mid = Math.floor(calc.length / 2);
  const medianRaw =
    calc.length % 2 !== 0 ? calc[mid] : (calc[mid - 1] + calc[mid]) / 2.0;
  const medianPrice = Math.round(medianRaw * 100) / 100;
  const medianChf =
    sourceConfig.currency === "CHF"
      ? medianPrice
      : Math.round(medianPrice * eurToChfRate * 100) / 100;

  return {
    source_id: sourceConfig.id,
    label: sourceConfig.label,
    currency: sourceConfig.currency,
    sample_count: sampleCount,
    min_price: minPrice,
    max_price: maxPrice,
    median_price: medianPrice,
    median_chf: medianChf,
    url: url,
    method: method,
  };
}

async function scrapeViaBackgroundTab(url, sourceId) {
  if (!browserApi || !browserApi.tabs || !browserApi.scripting) {
    return [];
  }
  let tab = null;
  try {
    tab = await browserApi.tabs.create({ url: url, active: false });
    await new Promise(resolve => {
      const timeout = setTimeout(() => {
        browserApi.tabs.onUpdated.removeListener(listener);
        resolve();
      }, 9000);
      function listener(tabId, info) {
        if (tabId === tab.id && info.status === "complete") {
          clearTimeout(timeout);
          browserApi.tabs.onUpdated.removeListener(listener);
          resolve();
        }
      }
      browserApi.tabs.onUpdated.addListener(listener);
    });

    // Wait 1800ms for SPA client-side hydration (Digitec, Ricardo, Idealo, eBay)
    await new Promise(r => setTimeout(r, 1800));

    const results = await browserApi.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => {
        const html = document.documentElement ? document.documentElement.outerHTML : "";
        const priceNodes = Array.from(
          document.querySelectorAll(
            '.s-item__price, .s-card__price, .aditem-main--middle--price-shipping--price, [class*="price" i], [data-testid*="price" i]'
          )
        )
          .slice(0, 40)
          .map(el => (el.textContent || "").trim())
          .filter(Boolean);
        return { html, priceNodes };
      },
    });

    if (results && results[0] && results[0].result) {
      const { html, priceNodes } = results[0].result;
      const extracted = extractPricesFromHtml(sourceId, html);
      if (extracted.length > 0) return extracted;
      const domPrices = [];
      for (const txt of priceNodes || []) {
        const p = parsePriceText(txt);
        if (p !== null) domPrices.push(p);
      }
      return domPrices.slice(0, 30);
    }
  } catch (err) {
    console.warn(`[Seller Assistant] Tab fallback failed for ${sourceId}:`, err);
  } finally {
    if (tab && tab.id !== undefined) {
      try {
        await browserApi.tabs.remove(tab.id);
      } catch (_) {}
    }
  }
  return [];
}

async function scrapeSourceHybrid(sourceConfig, query, eurToChfRate = 0.94) {
  const url = sourceConfig.url;
  let prices = [];
  let method = "fetch";

  // Step 1: Fast background fetch()
  try {
    const resp = await fetch(url, {
      credentials: "include",
      headers: {
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8",
      },
    });
    if (resp.ok) {
      const html = await resp.text();
      prices = extractPricesFromHtml(sourceConfig.id, html);
    }
  } catch (err) {
    console.warn(`[Seller Assistant] Direct fetch failed for ${sourceConfig.id}:`, err);
  }

  // Step 2: Fallback to inactive background tab if fetch returned 0 prices
  if (prices.length === 0) {
    method = "tab";
    prices = await scrapeViaBackgroundTab(url, sourceConfig.id);
  }

  return computeSourceStats(sourceConfig, prices, url, method, eurToChfRate);
}

async function scrapeAllPriceSources(query, eurToChfRate = 0.94) {
  const links = buildVerificationLinks(query);
  const sourceConfigs = [
    {
      id: "ebay_de_sold",
      label: "eBay DE (Gebraucht & Beendet)",
      currency: "EUR",
      url: links.ebay_sold_url,
    },
    {
      id: "kleinanzeigen",
      label: "Kleinanzeigen.de Suche",
      currency: "EUR",
      url: links.kleinanzeigen_search_url,
    },
    {
      id: "idealo",
      label: "Idealo.de Neupreis",
      currency: "EUR",
      url: links.idealo_url,
    },
    {
      id: "ricardo",
      label: "Ricardo.ch Suche",
      currency: "CHF",
      url: links.ricardo_search_url,
    },
    {
      id: "toppreise",
      label: "Toppreise.ch Neupreis",
      currency: "CHF",
      url: links.toppreise_url,
    },
    {
      id: "digitec",
      label: "Digitec/Galaxus Suche",
      currency: "CHF",
      url: links.digitec_url,
    },
  ];

  const results = await Promise.all(
    sourceConfigs.map(cfg => scrapeSourceHybrid(cfg, query, eurToChfRate))
  );

  const sourcesMap = {};
  for (const r of results) {
    sourcesMap[r.source_id] = r;
  }

  return {
    ok: true,
    query: query,
    sources: sourcesMap,
    verification_links: links,
  };
}

if (browserApi && browserApi.runtime && browserApi.runtime.onMessage) {
  browserApi.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "LIST_DRAFTS") {
      fetch(`${BACKEND_BASE}/api/drafts`)
        .then(res => {
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          return res.json();
        })
        .then(drafts => sendResponse({ ok: true, drafts }))
        .catch(err => sendResponse({ ok: false, error: err.message }));
      return true;
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
              dataUrl: dataUrl,
            });
          }
          sendResponse({ ok: true, images: imagePayloads });
        })
        .catch(err => sendResponse({ ok: false, error: err.message }));
      return true;
    }

    if (request.action === "SCRAPE_ALL_PRICE_SOURCES") {
      scrapeAllPriceSources(request.query || "", request.eurToChfRate || 0.94)
        .then(res => sendResponse(res))
        .catch(err => sendResponse({ ok: false, error: err.message }));
      return true;
    }

    return false;
  });
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    buildVerificationLinks,
    parsePriceText,
    extractPricesFromHtml,
    computeSourceStats,
    scrapeSourceHybrid,
    scrapeAllPriceSources,
  };
}
