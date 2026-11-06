// Background Service Worker for OccAIsion
// Bypasses CORS and CSP by executing HTTP calls and hybrid price scraping inside the WebExtension privileged context.

function getBrowserApi() {
  if (typeof browser !== "undefined") return browser;
  if (typeof chrome !== "undefined") return chrome;
  return null;
}

const browserApi = getBrowserApi();
const BACKEND_BASE = "http://127.0.0.1:8000";

let cachedAuthToken = null;

async function getAuthToken() {
  if (cachedAuthToken) return cachedAuthToken;
  if (browserApi && browserApi.storage && browserApi.storage.local) {
    try {
      const data = await browserApi.storage.local.get(["occaision_auth_token"]);
      if (data && data.occaision_auth_token) {
        cachedAuthToken = data.occaision_auth_token;
        return cachedAuthToken;
      }
    } catch (_) {}
  }
  return null;
}

async function getAuthHeaders() {
  const token = await getAuthToken();
  const headers = {};
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  return headers;
}

const ALL_HOST_ORIGINS = [
  "http://127.0.0.1/*",
  "http://localhost/*",
  "*://*.ricardo.ch/*",
  "*://*.tutti.ch/*",
  "*://*.ebay.de/*",
  "*://*.kleinanzeigen.de/*",
  "*://*.idealo.de/*",
  "*://*.toppreise.ch/*",
  "*://*.digitec.ch/*",
  "*://*.galaxus.ch/*",
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
  const trimmed = (query || "").trim();
  const q = encodeURIComponent(trimmed).replace(/%20/g, "+");
  const qRaw = encodeURIComponent(trimmed);
  return {
    ebay_sold_url: `https://www.ebay.de/sch/i.html?_nkw=${q}&LH_Sold=1&LH_Complete=1&LH_ItemCondition=3000`,
    kleinanzeigen_search_url: `https://www.kleinanzeigen.de/anbieter:privat/s-${q}/k0+global.zustand:alright%2Clike_new%2Cok`,
    idealo_url: `https://www.idealo.de/preisvergleich/MainSearchProductCategory.html?q=${q}`,
    ricardo_search_url: `https://www.ricardo.ch/de/s/${qRaw}/?item_condition=used&seller_type=individual`,
    toppreise_url: `https://www.toppreise.ch/produktsuche?q=${q}`,
    digitec_url: `https://www.galaxus.ch/de/search?q=${q}`,
    tutti_search_url: "https://www.tutti.ch/de",
  };
}

function parsePriceText(text) {
  if (!text || typeof text !== "string") return null;
  const lower = text.toLowerCase();
  if (lower.includes("bis") || lower.includes(" to ") || lower.includes(" - ")) {
    return null;
  }
  // Decode HTML entities for apostrophes, quotes, and non-breaking spaces
  let cleaned = text
    .replace(/&(?:#39|#039|#x27|#x0027|apos|rsquo|lsquo|#8217|#8216);/gi, "")
    .replace(/&(?:nbsp|#160|#xa0);/gi, " ")
    .replace(/['’‘ʼʻʽ‛′‵´`]/g, "")
    .replace(/\.–|\.-|--/g, ".00");

  // Normalize thousands separators formatted as spaces (e.g. 2 173.45, 2\u00a0173, 2\u202f173)
  while (/(\d)(?:[\s\u00a0\u202f]+)(\d{3})/i.test(cleaned)) {
    cleaned = cleaned.replace(/(\d)(?:[\s\u00a0\u202f]+)(\d{3})/gi, "$1$2");
  }

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

function isEbayLoginRequired(html, finalUrl = "") {
  const u = (finalUrl || "").toLowerCase();
  if (
    u.includes("signin.ebay.") ||
    u.includes("/signin") ||
    u.includes("ebayisapi.dll?signin")
  ) {
    return true;
  }
  if (!html || typeof html !== "string") return false;
  const lower = html.toLowerCase();
  if (
    lower.includes('id="signin-form"') ||
    lower.includes("id='signin-form'") ||
    lower.includes('name="signinform"') ||
    lower.includes('id="userid"') ||
    lower.includes("signin-intro") ||
    lower.includes("bitte einloggen") ||
    lower.includes("melden sie sich an, um") ||
    /<title[^>]*>[^<]*(?:einloggen|anmelden|sign in|sicherheitsma)/i.test(html)
  ) {
    return true;
  }
  return false;
}

function extractEbayItemsFromHtml(html) {
  if (!html || typeof html !== "string") return [];

  if (
    html.includes("splashui/challenge") ||
    html.includes("Pardon Our Interruption") ||
    html.includes("cf-chl-bypass") ||
    html.includes("captcha-delivery.com")
  ) {
    return [];
  }

  // Filter out everything from "Ergebnisse für weniger Suchbegriffe" / "Results matching fewer words" onwards
  const fewerWordsMatch = html.match(
    /(?:Ergebnisse für weniger Suchbegriffe|Ergebnisse für weniger Suchwörter|Results matching fewer words)/i
  );
  if (fewerWordsMatch && fewerWordsMatch.index !== undefined) {
    console.log(
      `[OccAIsion] [ebay_de_sold] 'Ergebnisse für weniger Suchbegriffe' an Position ${fewerWordsMatch.index} erkannt – filtere alle nachfolgenden ungenauen Treffer heraus.`
    );
    html = html.substring(0, fewerWordsMatch.index);
  }

  const items = [];
  const itemBlocks = html.split(/class=["'][^"']*s-(?:item|card)\b/i).slice(1);

  for (const block of itemBlocks) {
    if (block.includes("Shop on eBay")) continue;

    // 1. Price
    const priceMatch = block.match(
      /class=["'][^"']*s-(?:item|card)__price[^"']*["'][^>]*>([\s\S]*?)<\/(?:span|div)>/i
    );
    if (!priceMatch) continue;
    const rawPrice = priceMatch[1].replace(/<[^>]+>/g, " ").trim();
    const price = parsePriceText(rawPrice);
    if (price === null) continue;

    // 2. Title
    let title = "Unbekannter Titel";
    const titleMatch = block.match(
      /class=["'][^"']*(?:s-item__title|s-card__title)[^"']*["'][^>]*>([\s\S]*?)<\/(?:div|h3|span)>/i
    );
    if (titleMatch) {
      title = titleMatch[1]
        .replace(/<span[^>]*class=["'][^"']*clipped[^"']*["'][^>]*>[\s\S]*?<\/span>/gi, "")
        .replace(/<[^>]+>/g, " ")
        .replace(/\s+/g, " ")
        .trim();
    }
    if (!title || title.toLowerCase().includes("shop on ebay") || title === "Neues Angebot") {
      continue;
    }

    // 3. Condition (Zustand)
    let condition = "Gebraucht";
    const condMatch = block.match(
      /class=["'][^"']*(?:SECONDARY_INFO|s-item__subtitle|s-item__condition)[^"']*["'][^>]*>([\s\S]*?)<\/(?:span|div)>/i
    );
    if (condMatch) {
      const parsedCond = condMatch[1]
        .replace(/<[^>]+>/g, " ")
        .replace(/\s+/g, " ")
        .trim();
      if (parsedCond) {
        condition = parsedCond;
      }
    }

    items.push({
      title,
      condition,
      price,
      rawPrice,
    });
  }

  return items.slice(0, 30);
}

function logExtractedItems(sourceKey, label, items, currency = "EUR", isSingleTop = false) {
  if (!items || items.length === 0) {
    console.log(`[OccAIsion] [${sourceKey}] Keine ${label} extrahiert (0 Treffer).`);
    return;
  }
  if (isSingleTop) {
    const top = items[0];
    console.group(`[OccAIsion] [${sourceKey}] ${label} (Bestpreis des ersten Produkts):`);
    console.log(`  Top-Treffer: ${top.price} ${currency} | Zustand: [${top.condition || "Neu"}] | Titel: "${top.title}"`);
    console.groupEnd();
    if (typeof console.table === "function") {
      try {
        console.table([{
          [`Preis (${currency})`]: top.price,
          "Zustand": top.condition || "Neu",
          "Produktname": top.title,
        }]);
      } catch (_) {}
    }
  } else {
    console.group(`[OccAIsion] [${sourceKey}] ${label} (${items.length} Treffer):`);
    items.forEach((it, idx) => {
      const extra = it.bidType ? ` | [${it.bidType}]` : (it.condition ? ` | Zustand: [${it.condition}]` : "");
      console.log(`  #${idx + 1}: ${it.price} ${currency}${extra} | Titel: "${it.title}"`);
    });
    console.groupEnd();
    if (typeof console.table === "function") {
      try {
        console.table(
          items.map((it, idx) => ({
            "#": idx + 1,
            [`Preis (${currency})`]: it.price,
            "Zustand": it.condition || it.bidType || "-",
            "Titel": it.title,
          }))
        );
      } catch (_) {}
    }
  }
}

function logEbayExtractedItems(items) {
  logExtractedItems("ebay_de_sold", "verkaufte Artikel", items, "€");
}

function extractKleinanzeigenItems(content) {
  if (!content) return [];

  let data = null;
  if (typeof content === "object") {
    data = content;
  } else if (typeof content === "string") {
    let trimmed = content.trim();
    if (trimmed.includes("<pre") && trimmed.includes("</pre>")) {
      const m = trimmed.match(/<pre[^>]*>([\s\S]*?)<\/pre>/i);
      if (m) trimmed = m[1].trim();
    }
    if (trimmed.startsWith("{") || trimmed.includes('"resultList"')) {
      try {
        const start = trimmed.indexOf("{");
        const end = trimmed.lastIndexOf("}");
        if (start !== -1 && end > start) {
          data = JSON.parse(trimmed.slice(start, end + 1));
        } else {
          data = JSON.parse(trimmed);
        }
      } catch (_) {}
    }
  }

  // 1. Kleinanzeigen JSON API parsing
  if (data && data.result && Array.isArray(data.result.resultList)) {
    const items = [];
    for (const entry of data.result.resultList) {
      const ad = entry.organicAdPreview || entry.adPreview;
      if (!ad) continue;
      // Filter for private sellers only
      if (ad.posterType && ad.posterType !== "PRIVATE") continue;

      const rawPrice = (ad.price || "").trim();
      const price = parsePriceText(rawPrice);
      if (price === null) continue;

      let condition = "Gebraucht";
      if (ad.condition && typeof ad.condition === "string") {
        condition = ad.condition.trim();
      } else if (ad.attributes && Array.isArray(ad.attributes)) {
        const condAttr = ad.attributes.find(a =>
          typeof a === "string" && /neu|wie neu|sehr gut|gut|in ordnung|defekt/i.test(a)
        );
        if (condAttr) condition = condAttr.trim();
      }
      if (condition === "Gebraucht" && ad.description && typeof ad.description === "string") {
        const m = ad.description.match(/(?:Zustand|Condition)\s*[:\-]\s*([^\n.,;]+)/i);
        if (m && m[1]) {
          condition = m[1].trim();
        }
      }

      items.push({
        id: ad.id,
        title: (ad.title || "").trim(),
        condition,
        price,
        rawPrice,
        posterType: ad.posterType || "PRIVATE",
      });
    }
    return items.slice(0, 30);
  }

  // 2. Kleinanzeigen HTML fallback parsing
  if (typeof content === "string") {
    const items = [];
    const articleRegex = /<article[^>]*class=["'][^"']*aditem[^"']*["'][\s\S]*?<\/article>/gi;
    let m;
    while ((m = articleRegex.exec(content)) !== null) {
      const block = m[0];
      if (/class=["'][^"']*(?:badge-commercial|is-topad)[^"']*["']/i.test(block) && !block.includes("badge-private")) {
        continue;
      }
      let title = "";
      const titleMatch = block.match(/<a[^>]*class=["'][^"']*(?:ellipsis|text-module-begin)[^"']*["'][^>]*>([\s\S]*?)<\/a>/i);
      if (titleMatch) {
        title = titleMatch[1].replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
      }
      const priceMatch = block.match(/class=["'][^"']*aditem-main--middle--price-shipping--price[^"']*["'][^>]*>([\s\S]*?)<\/p>/i);
      if (!priceMatch) continue;
      const rawPrice = priceMatch[1].replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
      const price = parsePriceText(rawPrice);
      if (price === null) continue;

      let condition = "Gebraucht";
      const condMatch = block.match(/class=["'][^"']*(?:aditem-main--middle--attribute|condition)[^"']*["'][^>]*>([\s\S]*?)<\/(?:span|div|p)>/i);
      if (condMatch) {
        condition = condMatch[1].replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
      } else {
        const descMatch = block.match(/class=["'][^"']*aditem-main--middle--description[^"']*["'][^>]*>([\s\S]*?)<\/p>/i);
        if (descMatch) {
          const descText = descMatch[1].replace(/<[^>]+>/g, " ");
          const cm = descText.match(/(?:Zustand|Condition)\s*[:\-]\s*([^\n.,;]+)/i);
          if (cm && cm[1]) condition = cm[1].trim();
        }
      }

      items.push({
        title: title || "Kleinanzeigen Anzeige",
        condition,
        price,
        rawPrice,
        posterType: "PRIVATE",
      });
    }
    if (items.length > 0) {
      return items.slice(0, 30);
    }

    const kaRegex = /aditem-main--middle--price-shipping--price[^>]*>([\s\S]*?)<\/p>/gi;
    while ((m = kaRegex.exec(content)) !== null) {
      const rawText = m[1].replace(/<[^>]+>/g, " ").trim();
      const val = parsePriceText(rawText);
      if (val !== null) {
        items.push({
          title: "Kleinanzeigen Anzeige",
          condition: "Gebraucht",
          price: val,
          rawPrice: rawText,
          posterType: "PRIVATE",
        });
      }
    }
    return items.slice(0, 30);
  }

  return [];
}

function logKleinanzeigenExtractedItems(items) {
  logExtractedItems("kleinanzeigen", "Kleinanzeigen-Artikel", items, "€");
}

function extractRicardoItems(html, priceNodes = [], ricardoCards = []) {
  const items = [];
  const seenUrls = new Set();

  // 1. Live DOM-extracted cards from background tab
  if (Array.isArray(ricardoCards) && ricardoCards.length > 0) {
    for (const card of ricardoCards) {
      if (card.url && seenUrls.has(card.url)) continue;
      if (card.url) seenUrls.add(card.url);

      const p = parsePriceText(card.rawPrice);
      if (p !== null && p > 0) {
        items.push({
          title: (card.title || "Ricardo Angebot").trim(),
          condition: "Gebraucht",
          bidType: card.bidType || "Angebot",
          price: p,
          rawPrice: card.rawPrice,
          url: card.url || "",
        });
      }
    }
    if (items.length > 0) return items.slice(0, 30);
  }

  // 2. HTML parsing from rendered HTML string (scoped to [data-testid="regular-results"] to exclude relaxed search keywords)
  if (html && typeof html === "string") {
    let scope = html;
    const regMatch = html.match(/data-testid=["']regular-results["'][\s\S]*/i);
    if (regMatch) {
      scope = regMatch[0];
      const divider = scope.match(/(?:<h[2-6][^>]*>[^<]*ergebnisse f[uü]r|<a[^>]*href=["'][^"']*\/de\/s\/[^"']+["'][^>]*>[^<]*Alle Ergebnisse anzeigen)/i);
      if (divider) {
        scope = scope.slice(0, divider.index);
      }
    } else {
      const divider = html.match(/(?:<h[2-6][^>]*>[^<]*ergebnisse f[uü]r|<a[^>]*href=["'][^"']*\/de\/s\/[^"']+["'][^>]*>[^<]*Alle Ergebnisse anzeigen)/i);
      if (divider) {
        scope = html.slice(0, divider.index);
      }
    }

    const aRegex = /<a[^>]+href=["']([^"']*(?:\/de)?\/a\/[^"']+)["'][^>]*>([\s\S]*?)<\/a>/gi;
    let m;
    while ((m = aRegex.exec(scope)) !== null) {
      const url = m[1];
      if (seenUrls.has(url)) continue;
      seenUrls.add(url);

      const content = m[2];
      const tMatch = content.match(/<span[^>]*class=["'][^"']*MuiTypography-body1[^"']*["'][^>]*>([^<]+)<\/span>/i);
      const altMatch = content.match(/<img[^>]*alt=["']([^"']+)["']/i);
      const title = (tMatch ? tMatch[1] : (altMatch ? altMatch[1] : "Ricardo Angebot")).trim();

      const clean = content.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");
      const sofortM = clean.match(/(\d{1,5}(?:['’.,\s\u00a0\u202f]\d{2,3})*(?:\.\d{2})?)\s*(?:Sofort kaufen|Achat direct|Compra subito)/i);
      const gebotM = clean.match(/(\d{1,5}(?:['’.,\s\u00a0\u202f]\d{2,3})*(?:\.\d{2})?)\s*\(\d+\s*(?:Gebot|offre|offerta)/i);

      let rawPrice = sofortM ? sofortM[1].trim() : (gebotM ? gebotM[1].trim() : null);
      if (!rawPrice) {
        const numM = clean.match(/(\d{1,5}(?:['’.,\s\u00a0\u202f]\d{2,3})*\.\d{2})/);
        if (numM) rawPrice = numM[1].trim();
      }

      if (rawPrice) {
        const p = parsePriceText(rawPrice);
        if (p !== null && p > 0) {
          items.push({
            title: title || "Ricardo Angebot",
            condition: "Gebraucht",
            bidType: sofortM ? "Sofortkauf" : "Auktion",
            price: p,
            rawPrice,
            url,
          });
        }
      }
    }
    if (items.length > 0) return items.slice(0, 30);
  }

  // 3. Fallback: priceNodes
  if (Array.isArray(priceNodes) && priceNodes.length > 0) {
    for (const raw of priceNodes) {
      const p = parsePriceText(raw);
      if (p !== null && p > 0) {
        items.push({
          title: "Ricardo Angebot",
          condition: "Gebraucht",
          bidType: "Angebot",
          price: p,
          rawPrice: raw,
        });
      }
    }
  }

  return items.slice(0, 30);
}

function logRicardoExtractedItems(items) {
  logExtractedItems("ricardo", "Ricardo-Angebote", items, "CHF");
}

function extractTuttiItems(html, priceNodes = [], tuttiCards = []) {
  const items = [];
  const seenUrls = new Set();

  // 1. Live DOM-extracted cards from background tab
  if (Array.isArray(tuttiCards) && tuttiCards.length > 0) {
    for (const card of tuttiCards) {
      if (card.url && seenUrls.has(card.url)) continue;
      if (card.url) seenUrls.add(card.url);

      const p = parsePriceText(card.rawPrice);
      if (p !== null && p > 0) {
        items.push({
          title: (card.title || "Tutti Inserat").trim(),
          condition: "Gebraucht",
          price: p,
          rawPrice: card.rawPrice,
          url: card.url || "",
        });
      }
    }
    if (items.length > 0) return items.slice(0, 30);
  }

  // 2. HTML parsing from rendered HTML string
  if (html && typeof html === "string") {
    const cardRegex = /<div[^>]*?data-private-srp-listing-item-id=\"([^\"]+)\"[\s\S]*?(?=<div[^>]*?data-private-srp-listing-item-id=|$)/gi;
    let match;
    while ((match = cardRegex.exec(html)) !== null) {
      const cardHtml = match[0];
      if (cardHtml.includes("ricardo.ch") || cardHtml.includes("utm_source=tutti-web")) continue;

      const hrefMatch = cardHtml.match(/href=\"([^\"]*\/vi\/[^\"]*)\"/i);
      const url = hrefMatch ? hrefMatch[1] : "";
      if (!url || seenUrls.has(url)) continue;
      seenUrls.add(url);

      const titleMatch = cardHtml.match(/<h2[^>]*>([\s\S]*?)<\/h2>/i);
      const title = (titleMatch ? titleMatch[1].replace(/<[^>]+>/g, "").trim() : "Tutti Inserat");

      const priceMatch = cardHtml.match(/(\d+['’.,\s\u00a0\u202f\d]*(?:\.–|\.-|--))/);
      if (priceMatch) {
        const p = parsePriceText(priceMatch[1]);
        if (p !== null && p > 0) {
          items.push({
            title,
            condition: "Gebraucht",
            price: p,
            rawPrice: priceMatch[1].trim(),
            url,
          });
        }
      }
    }
    if (items.length > 0) return items.slice(0, 30);
  }

  // 3. Fallback: priceNodes
  if (Array.isArray(priceNodes) && priceNodes.length > 0) {
    for (const raw of priceNodes) {
      const p = parsePriceText(raw);
      if (p !== null && p > 0) {
        items.push({
          title: "Tutti Inserat",
          condition: "Gebraucht",
          price: p,
          rawPrice: raw,
          url: "",
        });
      }
    }
  }

  return items.slice(0, 30);
}

function logTuttiExtractedItems(items) {
  logExtractedItems("tutti", "Tutti.ch Inserate", items, "CHF");
}

function findIdealoProductsInNextData(obj) {
  const items = [];
  function walk(node, depth = 0) {
    if (!node || depth > 10 || items.length >= 30) return;
    if (typeof node !== "object") return;
    if (Array.isArray(node)) {
      for (const el of node) walk(el, depth + 1);
      return;
    }
    const title = node.title || node.name || node.productTitle || "";
    const rawPrice = node.price || node.minPrice || node.lowestPrice || node.bestPrice || (node.priceInfo && node.priceInfo.price);
    if (title && rawPrice) {
      const p = typeof rawPrice === "number" ? rawPrice : parsePriceText(String(rawPrice));
      if (p !== null && p > 0) {
        items.push({
          title: String(title).trim(),
          condition: items.length === 0 ? "Neu (Bestpreis)" : "Neu",
          price: p,
          rawPrice: `${p} €`,
        });
      }
    }
    for (const k of Object.keys(node)) {
      if (typeof node[k] === "object") {
        walk(node[k], depth + 1);
      }
    }
  }
  walk(obj);
  return items;
}

function calculateTokenOverlap(query, candidateTitle) {
  if (!query || !candidateTitle) return 0.0;
  const tokenize = s => s.toLowerCase().replace(/[^a-z0-9äöüß]/gi, " ").split(/\s+/).filter(w => w.length > 1);
  const qTokens = tokenize(query);
  if (qTokens.length === 0) return 1.0;
  const tTokens = new Set(tokenize(candidateTitle));
  let matchCount = 0;
  for (const t of qTokens) {
    if (tTokens.has(t)) matchCount++;
  }
  return Math.round((matchCount / qTokens.length) * 100) / 100;
}

function selectBestMatchingItem(items, query) {
  if (!Array.isArray(items) || items.length === 0) return null;
  if (!query || items.length === 1) return items[0];
  let bestItem = items[0];
  let bestScore = -1;
  for (const item of items) {
    const score = calculateTokenOverlap(query, item.title || "");
    if (score > bestScore) {
      bestScore = score;
      bestItem = item;
    }
  }
  return bestItem;
}

function extractIdealoItems(html, priceNodes = [], idealoCards = []) {
  const items = [];

  // 1. Live DOM-extracted first card from .sr-resultList_*
  if (Array.isArray(idealoCards) && idealoCards.length > 0) {
    const first = idealoCards[0];
    const p = parsePriceText(first.rawPrice);
    if (p !== null) {
      items.push({
        title: first.title || "Idealo Produkt",
        condition: "Neu (Bestpreis)",
        price: p,
        rawPrice: first.rawPrice,
      });
      return items;
    }
  }

  // 2. Extract from window.csr.initialData in HTML string
  if (html && typeof html === "string") {
    const csrMatch = html.match(/window\.csr\.initialData\[.searchResult.\]\s*=\s*[\x22\x27]([^\x22\x27]+)[\x22\x27]/);
    if (csrMatch) {
      try {
        let jsonStr = "";
        if (typeof Buffer !== "undefined") {
          jsonStr = Buffer.from(csrMatch[1], "base64").toString("utf-8");
        } else if (typeof atob === "function") {
          const binary = atob(csrMatch[1]);
          const bytes = new Uint8Array(binary.length);
          for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
          jsonStr = new TextDecoder("utf-8").decode(bytes);
        }
        if (jsonStr) {
          const data = JSON.parse(jsonStr);
          if (data && Array.isArray(data.items) && data.items.length > 0) {
            const first = data.items[0];
            const title = first.title || "Idealo Produkt";
            const price = typeof first.rawPrice === "number" ? first.rawPrice : parsePriceText(first.offerInfo && first.offerInfo.formattedPrice ? first.offerInfo.formattedPrice : "");
            const rawPrice = (first.offerInfo && first.offerInfo.formattedPrice) ? first.offerInfo.formattedPrice : (price ? `${price} €` : "");
            if (price !== null && price > 0) {
              items.push({
                title,
                condition: "Neu (Bestpreis)",
                price,
                rawPrice,
                url: first.href || "",
              });
              return items;
            }
          }
        }
      } catch (_) {}
    }

    // Extract first product summary title
    let title = "";
    const titleMatch = html.match(/class=["'][^"']*(?:productSummary__title|sr-productSummary__title)[^"']*["'][^>]*>([\s\S]*?)<\/(?:div|span|h2|h3|a)>/i);
    if (titleMatch) {
      title = titleMatch[1].replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
    }

    // Extract first price in sr-detailedPriceInfo__price
    const priceMatch = html.match(/class=["'][^"']*sr-detailedPriceInfo__price[^"']*["'][\s\S]*?(\d{1,5}(?:[.,]\d{2}))\s*€/i);
    if (priceMatch) {
      const val = parsePriceText(priceMatch[1]);
      if (val !== null) {
        items.push({
          title: title || "Idealo Produkt",
          condition: "Neu (Bestpreis)",
          price: val,
          rawPrice: `${priceMatch[1]} €`,
        });
        return items;
      }
    }

    // Check __NEXT_DATA__
    if (html.includes("__NEXT_DATA__")) {
      const nextMatch = html.match(/<script[^>]*id=["']__NEXT_DATA__["'][^>]*>([\s\S]*?)<\/script>/i);
      if (nextMatch) {
        try {
          const nextData = JSON.parse(nextMatch[1]);
          const found = findIdealoProductsInNextData(nextData);
          if (found.length > 0) {
            return [found[0]];
          }
        } catch (_) {}
      }
    }
  }

  // 3. Fallback: priceNodes (first price only)
  if (Array.isArray(priceNodes) && priceNodes.length > 0) {
    const val = parsePriceText(priceNodes[0]);
    if (val !== null) {
      items.push({
        title: "Idealo Produkt",
        condition: "Neu (Bestpreis)",
        price: val,
        rawPrice: priceNodes[0],
      });
      return items;
    }
  }

  return [];
}

function logIdealoExtractedItems(items) {
  logExtractedItems("idealo", "Idealo Neupreis", items, "€", true);
}

function extractToppreiseItems(html, priceNodes = [], toppreiseCards = []) {
  const items = [];

  // 1. Live DOM-extracted first card from browser tab
  if (Array.isArray(toppreiseCards) && toppreiseCards.length > 0) {
    const first = toppreiseCards[0];
    const p = parsePriceText(first.rawPrice);
    if (p !== null) {
      items.push({
        title: (first.title || "Toppreise Produkt").trim(),
        condition: "Neu (Bestpreis)",
        price: p,
        rawPrice: first.rawPrice,
      });
      return items;
    }
  }

  if (html && typeof html === "string") {
    // 2. Check JSON-LD for single product page (@type: Product)
    const scriptRegex = /<script[^>]*type=["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi;
    let match;
    while ((match = scriptRegex.exec(html)) !== null) {
      try {
        const data = JSON.parse(match[1].trim());
        if (data && data["@type"] === "Product") {
          let lowPrice = null;
          if (data.offers) {
            const offers = data.offers;
            if (typeof offers.lowPrice !== "undefined") lowPrice = offers.lowPrice;
            else if (typeof offers.price !== "undefined") lowPrice = offers.price;
            else if (Array.isArray(offers) && offers[0] && offers[0].price) lowPrice = offers[0].price;
          }
          const p = parsePriceText(String(lowPrice || ""));
          if (p !== null) {
            items.push({
              title: String(data.name || "Toppreise Produkt").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim(),
              condition: "Neu (Bestpreis)",
              price: p,
              rawPrice: `CHF ${p}`,
            });
            return items;
          }
        }
      } catch (_) {}
    }

    // 3. Search Results / Variant List: Restrict scope to <main> to ignore header history dropdowns
    const mainMatch = html.match(/<main[\s\S]*?<\/main>/i);
    const scope = mainMatch ? mainMatch[0] : html;

    // In Toppreise search results, each product entry has class Plugin_Product
    const prodBlockMatch = scope.match(/class=["'][^"']*\bPlugin_Product\b[^"']*["'][\s\S]*?(?:(?=class=["'][^"']*\bPlugin_Product\b)|<\/main>|$)/i);
    const targetBlock = prodBlockMatch ? prodBlockMatch[0] : scope;

    // Extract title: from a.bold or a[href*="/preisvergleich/"] or .product-name
    let title = "";
    const titleMatch = targetBlock.match(/<a[^>]*class=["'][^"']*\bbold\b[^"']*["'][^>]*href=["'][^"']*\/preisvergleich\/[^"']*["'][^>]*>([\s\S]*?)<\/a>/i) ||
                       targetBlock.match(/<a[^>]*href=["'][^"']*\/preisvergleich\/[^"']*["'][^>]*class=["'][^"']*\bbold\b[^"']*["'][^>]*>([\s\S]*?)<\/a>/i) ||
                       targetBlock.match(/class=["'][^"']*\bproduct-name\b[^"']*["'][\s\S]*?<a[^>]*href=["'][^"']*\/preisvergleich\/[^"']*["'][^>]*>([\s\S]*?)<\/a>/i);
    if (titleMatch) {
      title = titleMatch[1].replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
    }

    // Extract price from Plugin_Price inside targetBlock
    const priceMatch = targetBlock.match(/class=["'][^"']*\bPlugin_Price\b[^"']*["'][^>]*>([\s\S]*?)<\/(?:div|span|p|a)>/i) ||
                       targetBlock.match(/(?:CHF|Fr\.)\s*(\d{1,5}(?:['’.,]\d{2,3})*)/i);
    if (priceMatch) {
      const p = parsePriceText(priceMatch[1]);
      if (p !== null) {
        items.push({
          title: title || "Toppreise Produkt",
          condition: "Neu (Bestpreis)",
          price: p,
          rawPrice: priceMatch[1].trim(),
        });
        return items;
      }
    }
  }

  // 4. Fallback: priceNodes (first price only)
  if (Array.isArray(priceNodes) && priceNodes.length > 0) {
    const val = parsePriceText(priceNodes[0]);
    if (val !== null) {
      items.push({
        title: "Toppreise Produkt",
        condition: "Neu (Bestpreis)",
        price: val,
        rawPrice: priceNodes[0],
      });
      return items;
    }
  }

  return [];
}

function logToppreiseExtractedItems(items) {
  logExtractedItems("toppreise", "Toppreise Neupreis", items, "CHF", true);
}

function extractDigitecItems(html, priceNodes = [], digitecCards = []) {
  const items = [];

  // 1. Live DOM-extracted first card from browser tab
  if (Array.isArray(digitecCards) && digitecCards.length > 0) {
    const first = digitecCards[0];
    const p = parsePriceText(first.rawPrice);
    if (p !== null) {
      items.push({
        title: (first.title || "Galaxus Produkt").trim(),
        condition: "Neu (Bestpreis)",
        price: p,
        rawPrice: first.rawPrice,
      });
      return items;
    }
  }

  if (html && typeof html === "string") {
    // 2. Check JSON-LD for single product page (@type: Product)
    const scriptRegex = /<script[^>]*type=["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi;
    let match;
    while ((match = scriptRegex.exec(html)) !== null) {
      try {
        const data = JSON.parse(match[1].trim());
        if (data && data["@type"] === "Product") {
          let lowPrice = null;
          if (data.offers) {
            const offers = data.offers;
            if (typeof offers.price !== "undefined") lowPrice = offers.price;
            else if (typeof offers.lowPrice !== "undefined") lowPrice = offers.lowPrice;
            else if (Array.isArray(offers) && offers[0] && offers[0].price) lowPrice = offers[0].price;
          }
          const p = parsePriceText(String(lowPrice || ""));
          if (p !== null) {
            items.push({
              title: String(data.name || "Galaxus Produkt").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim(),
              condition: "Neu (Bestpreis)",
              price: p,
              rawPrice: `CHF ${p}`,
            });
            return items;
          }
        }
      } catch (_) {}
    }

    // 3. Search Results: Find first <article>
    const articleMatch = html.match(/<article[\s\S]*?<\/article>/i);
    if (articleMatch) {
      const artHtml = articleMatch[0];

      // Extract title: from a[aria-label] with /product/ href, alt="Produktbild...", or p strong+span
      let title = "";
      const ariaMatch = artHtml.match(/<a[^>]*aria-label=["']([^"']+)["'][^>]*href=["'][^"']*\/product\/[^"']*["']/i) ||
                        artHtml.match(/<a[^>]*href=["'][^"']*\/product\/[^"']*["'][^>]*aria-label=["']([^"']+)["']/i);
      if (ariaMatch) {
        title = ariaMatch[1].trim();
      } else {
        const altMatch = artHtml.match(/alt=["']Produktbild\s+([^"']+)["']/i);
        if (altMatch) {
          title = altMatch[1].trim();
        }
      }

      // Extract price from article
      const priceMatch = artHtml.match(/(?:CHF|Fr\.)[\s\S]*?(\d{1,5}(?:['’.,\s\u00a0\u202f]\d{2,3})*(?:\.–|\.-|--|,\d{2}|\.\d{2}))/i) ||
                         artHtml.match(/(\d{1,5}(?:['’.,\s\u00a0\u202f]\d{2,3})*(?:\.–|\.-|--))/i);
      if (priceMatch) {
        const p = parsePriceText(priceMatch[1]);
        if (p !== null) {
          items.push({
            title: title || "Galaxus Produkt",
            condition: "Neu (Bestpreis)",
            price: p,
            rawPrice: priceMatch[1].trim(),
          });
          return items;
        }
      }
    }
  }

  // 4. Fallback: priceNodes (first price only)
  if (Array.isArray(priceNodes) && priceNodes.length > 0) {
    const val = parsePriceText(priceNodes[0]);
    if (val !== null) {
      items.push({
        title: "Galaxus Produkt",
        condition: "Neu (Bestpreis)",
        price: val,
        rawPrice: priceNodes[0],
      });
      return items;
    }
  }

  return [];
}

function logDigitecExtractedItems(items) {
  logExtractedItems("digitec", "Galaxus/Digitec Neupreis", items, "CHF", true);
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
    const items = extractEbayItemsFromHtml(html);
    return items.map(it => it.price);
  }

  if (sourceId === "kleinanzeigen") {
    const items = extractKleinanzeigenItems(html);
    return items.map(it => it.price);
  }

  if (sourceId === "idealo") {
    const items = extractIdealoItems(html);
    return items.map(it => it.price);
  }

  if (sourceId === "toppreise") {
    const items = extractToppreiseItems(html);
    return items.map(it => it.price);
  }

  if (sourceId === "digitec") {
    const items = extractDigitecItems(html);
    return items.map(it => it.price);
  }

  if (sourceId === "ricardo") {
    const items = extractRicardoItems(html);
    return items.map(it => it.price);
  }

  if (sourceId === "tutti") {
    const items = extractTuttiItems(html);
    return items.map(it => it.price);
  }

  // Try JSON-LD structured product/offer data first
  const ldPrices = extractJsonLdPrices(html);
  prices.push(...ldPrices);

  if (sourceId === "ricardo") {
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

function computeSourceStats(
  sourceConfig,
  rawPrices,
  url,
  method,
  eurToChfRate = 0.94,
  extra = {}
) {
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
      login_required: Boolean(extra.login_required),
      error: extra.error || null,
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
    login_required: Boolean(extra.login_required),
    error: extra.error || null,
    items: extra.items || null,
    captured_at: new Date().toISOString(),
    query: extra.query || "",
    confidence: extra.confidence !== undefined ? extra.confidence : 1.0,
  };
}

async function scrapeViaBackgroundTab(url, sourceId, keepTabsOpen = false, query = "") {
  const api = getBrowserApi();
  if (!api || !api.tabs || !api.scripting) {
    return { prices: [], loginRequired: false };
  }
  let tab = null;
  try {
    tab = await api.tabs.create({ url: url, active: false });
    await new Promise(resolve => {
      const timeout = setTimeout(() => {
        api.tabs.onUpdated.removeListener(listener);
        resolve();
      }, 5000);
      function listener(tabId, info) {
        if (tabId === tab.id && info.status === "complete") {
          clearTimeout(timeout);
          api.tabs.onUpdated.removeListener(listener);
          resolve();
        }
      }
      api.tabs.onUpdated.addListener(listener);
    });

    // Wait standard 1200ms for DOM ready / client hydration
    await new Promise(r => setTimeout(r, 1200));

    if (sourceId === "tutti" && query) {
      try {
        console.log(`[OccAIsion] [tutti] Fülle Suchmaske für '${query}' auf ${url} aus...`);
        const searchAction = await api.scripting.executeScript({
          target: { tabId: tab.id },
          args: [query],
          func: async (q) => {
            const curUrl = location.href || "";
            if (curUrl.includes("/q/") || curUrl.includes("/suche")) {
              return { status: "already_on_search_page", url: curUrl };
            }

            const input = document.querySelector(
              'input[data-testid="search-field"], input[data-e2e-testid="search-field"], input[placeholder*="suchst du"]'
            );
            if (!input) {
              return { status: "no_input_found", url: curUrl };
            }

            input.focus();
            const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set;
            if (nativeSetter) {
              nativeSetter.call(input, q);
            } else {
              input.value = q;
            }
            input.dispatchEvent(new Event("input", { bubbles: true }));
            input.dispatchEvent(new Event("change", { bubbles: true }));

            // Wait 250ms for React/MUI Autocomplete state update
            await new Promise(r => setTimeout(r, 250));

            const form = input.closest("form") || input.form;
            const submitBtn = (form ? form.querySelector('button[type="submit"]') : null) ||
                              document.querySelector('form button[type="submit"], button[aria-label="Suchen"], button[type="submit"][aria-label="Suchen"]');
            if (submitBtn) {
              submitBtn.focus();
              submitBtn.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, cancelable: true }));
              submitBtn.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true }));
              submitBtn.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, cancelable: true }));
              submitBtn.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true }));
              submitBtn.click();
            }

            // Also dispatch Enter on input
            input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true, cancelable: true }));
            input.dispatchEvent(new KeyboardEvent("keypress", { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true, cancelable: true }));
            input.dispatchEvent(new KeyboardEvent("keyup", { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true, cancelable: true }));

            if (form && typeof form.requestSubmit === "function") {
              try {
                form.requestSubmit(submitBtn || undefined);
              } catch (_) {
                try {
                  form.requestSubmit();
                } catch (_) {}
              }
            }

            return { status: "submitted", query: q, inputFound: true, buttonFound: Boolean(submitBtn) };
          },
        });

        console.log("[OccAIsion] [tutti] Suchmaske-Aktion Ergebnis:", searchAction?.[0]?.result);

        // Wait for results to render or navigate (poll up to 8s)
        const startWait = Date.now();
        let navigatedToSearch = false;
        while (Date.now() - startWait < 8000) {
          await new Promise(r => setTimeout(r, 600));
          try {
            const checkRes = await api.scripting.executeScript({
              target: { tabId: tab.id },
              func: () => {
                const cur = location.href || "";
                const isSearch = cur.includes("/q/") || cur.includes("/suche");
                const count = isSearch ? document.querySelectorAll('[data-private-srp-listing-item-id]').length : 0;
                const hasNoResults = isSearch && /keine inserate|keine treffer|0 inserate|keine ergebnisse/i.test(document.body ? document.body.innerText : "");
                return { isSearch, count, hasNoResults, url: cur };
              },
            });
            if (checkRes && checkRes[0] && checkRes[0].result) {
              const res = checkRes[0].result;
              if (res.isSearch) {
                console.log(`[OccAIsion] [tutti] Suchergebnisseite erfolgreich geladen: ${res.url} (${res.count} Treffer, keineTreffer=${res.hasNoResults})`);
                navigatedToSearch = true;
                if (res.count === 0 && !res.hasNoResults) {
                  await new Promise(r => setTimeout(r, 600));
                }
                break;
              }
            }
          } catch (_) {}
        }
        if (!navigatedToSearch) {
          console.warn("[OccAIsion] [tutti] Konnte Suchergebnisseite nach 8s nicht erreichen (Tab verbleibt möglicherweise auf Startseite).");
        }
      } catch (tuttiSearchErr) {
        console.warn("[OccAIsion] [tutti] Fehler beim Ausfüllen der Suchmaske:", tuttiSearchErr);
      }
    }

    let pageData = null;
    try {
      const results = await api.scripting.executeScript({
        target: { tabId: tab.id },
        func: () => {
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
          if (idealoCards.length === 0) {
            const scripts = document.querySelectorAll("script");
            for (const s of scripts) {
              const txt = s.textContent || "";
              if (txt.includes("window.csr") && txt.includes("searchResult")) {
                const m = txt.match(/window\.csr\.initialData\[.searchResult.\]\s*=\s*['"]([^'"]+)['"]/);
                if (m) {
                  try {
                    const binary = atob(m[1]);
                    const bytes = new Uint8Array(binary.length);
                    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
                    const jsonStr = new TextDecoder("utf-8").decode(bytes);
                    const data = JSON.parse(jsonStr);
                    if (data && Array.isArray(data.items) && data.items.length > 0) {
                      const first = data.items[0];
                      const title = first.title || "Idealo Produkt";
                      const price = typeof first.rawPrice === "number" ? first.rawPrice : null;
                      const rawPrice = first.offerInfo?.formattedPrice || (price ? `${price} €` : "");
                      if (rawPrice) {
                        idealoCards.push({
                          title,
                          rawPrice,
                          url: first.href || "",
                        });
                      }
                    }
                  } catch (_) {}
                }
                break;
              }
            }
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

          const ricardoCards = [];
          const regContainer = document.querySelector('[data-testid="regular-results"]');
          const ricardoScope = regContainer || document;
          const ricardoLinks = ricardoScope.querySelectorAll('a[href*="/de/a/"], a[href*="/a/"]');
          const seenRicardoUrls = new Set();
          for (const a of ricardoLinks) {
            if (!regContainer) {
              const prevText = a.parentElement ? a.parentElement.textContent : "";
              if (/ergebnisse f[uü]r/i.test(prevText)) break;
            }

            const href = a.getAttribute("href") || "";
            if (!href || seenRicardoUrls.has(href)) continue;
            seenRicardoUrls.add(href);

            const titleEl = a.querySelector('[class*="MuiTypography-body1"]');
            const imgEl = a.querySelector('img[alt]');
            const title = (titleEl ? titleEl.textContent : (imgEl ? imgEl.getAttribute("alt") : "Ricardo Angebot")).trim();

            const cardText = a.textContent || "";
            const sofortM = cardText.match(/(\d{1,5}(?:['’.,\s\u00a0\u202f]\d{2,3})*(?:\.\d{2})?)\s*(?:Sofort kaufen|Achat direct|Compra subito)/i);
            const gebotM = cardText.match(/(\d{1,5}(?:['’.,\s\u00a0\u202f]\d{2,3})*(?:\.\d{2})?)\s*\(\d+\s*(?:Gebot|offre|offerta)/i);

            const buyNowRaw = sofortM ? sofortM[1].trim() : null;
            const bidRaw = gebotM ? gebotM[1].trim() : null;
            let rawPrice = buyNowRaw || bidRaw;
            if (!rawPrice) {
              const numM = cardText.match(/(\d{1,5}(?:['’.,\s\u00a0\u202f]\d{2,3})*\.\d{2})/);
              if (numM) rawPrice = numM[1].trim();
            }

            if (rawPrice) {
              ricardoCards.push({
                title: title || "Ricardo Angebot",
                rawPrice,
                buyNowRaw,
                bidRaw,
                bidType: sofortM ? "Sofortkauf" : "Auktion",
                url: href,
              });
            }
          }

          const tuttiCards = [];
          const tuttiItems = document.querySelectorAll('[data-private-srp-listing-item-id]');
          for (const item of tuttiItems) {
            const link = item.querySelector('a[href*="/vi/"]');
            if (!link) continue;
            const href = link.href || link.getAttribute("href") || "";
            if (href.includes("ricardo.ch") || href.includes("utm_source=tutti-web")) continue;

            const h2 = item.querySelector("h2");
            const title = (h2 ? h2.textContent : "").trim() || "Tutti Inserat";

            let rawPrice = "";
            for (const el of item.querySelectorAll("span, p, div")) {
              if (el.children && el.children.length > 0) continue;
              const t = (el.textContent || "").trim();
              if (
                /^(?:CHF|Fr\.)?\s*(\d{1,5}(?:['’.,\s\u00a0\u202f]\d{2,3})*(?:\.–|\.-|--|,\d{2}|\.\d{2})?)\s*(?:CHF|Fr\.)?$/i.test(t) &&
                (/[.\-–]|CHF|Fr/i.test(t))
              ) {
                rawPrice = t;
                break;
              }
            }
            if (!rawPrice) {
              for (const el of item.querySelectorAll("span, p")) {
                const t = (el.textContent || "").trim();
                if (
                  /^(?:CHF|Fr\.)?\s*(\d{1,5}(?:['’.,\s\u00a0\u202f]\d{2,3})*(?:\.–|\.-|--|,\d{2}|\.\d{2})?)\s*(?:CHF|Fr\.)?$/i.test(t) &&
                  (/[.\-–]|CHF|Fr/i.test(t))
                ) {
                  rawPrice = t;
                  break;
                }
              }
            }
            if (!rawPrice) {
              const allText = item.textContent || "";
              const m = allText.match(/(\d+['’.,\s\u00a0\u202f\d]*(?:\.–|\.-|--))/);
              if (m) rawPrice = m[1].trim();
            }

            if (rawPrice) {
              tuttiCards.push({
                title,
                rawPrice,
                url: href,
              });
            }
          }

          return { html, currentUrl, priceNodes, idealoCards, toppreiseCards, digitecCards, ricardoCards, tuttiCards };
        },
      });

      if (results && results[0] && results[0].result) {
        pageData = results[0].result;
      }
    } catch (scriptErr) {
      console.warn(`[OccAIsion] Tab-Scripting fehlgeschlagen (${scriptErr.message}). Versuche content.js Message-Fallback...`);
      if (api.tabs && api.tabs.sendMessage) {
        try {
          pageData = await api.tabs.sendMessage(tab.id, { action: "EXTRACT_PAGE_DATA" });
        } catch (_) {}
      }
    }

    if (pageData) {
      const { html, currentUrl, priceNodes } = pageData;
      if (sourceId === "ebay_de_sold" && isEbayLoginRequired(html, currentUrl)) {
        return { prices: [], loginRequired: true };
      }
      if (sourceId === "ebay_de_sold") {
        const ebayItems = extractEbayItemsFromHtml(html);
        if (ebayItems.length > 0) {
          return { prices: ebayItems.map(it => it.price), ebayItems, loginRequired: false };
        }
      }
      if (sourceId === "kleinanzeigen") {
        const kaItems = extractKleinanzeigenItems(html);
        if (kaItems.length > 0) {
          return { prices: kaItems.map(it => it.price), kleinanzeigenItems: kaItems, loginRequired: false };
        }
      }
      if (sourceId === "idealo") {
        const idealoItems = extractIdealoItems(html, priceNodes, pageData.idealoCards || []);
        if (idealoItems.length > 0) {
          return { prices: [idealoItems[0].price], idealoItems, loginRequired: false };
        }
        if (priceNodes && priceNodes.length > 0) {
          const p = parsePriceText(priceNodes[0]);
          if (p !== null) {
            const fallbackItem = [{
              title: "Idealo Top-Ergebnis",
              condition: "Neu (Bestpreis)",
              price: p,
              rawPrice: priceNodes[0],
            }];
            return { prices: [p], idealoItems: fallbackItem, loginRequired: false };
          }
        }
        return { prices: [], idealoItems: [], loginRequired: false };
      }
      if (sourceId === "toppreise") {
        const toppreiseItems = extractToppreiseItems(html, priceNodes, pageData.toppreiseCards || []);
        if (toppreiseItems.length > 0) {
          return { prices: [toppreiseItems[0].price], toppreiseItems, loginRequired: false };
        }
        if (priceNodes && priceNodes.length > 0) {
          const p = parsePriceText(priceNodes[0]);
          if (p !== null) {
            const fallbackItem = [{
              title: "Toppreise Top-Ergebnis",
              condition: "Neu (Bestpreis)",
              price: p,
              rawPrice: priceNodes[0],
            }];
            return { prices: [p], toppreiseItems: fallbackItem, loginRequired: false };
          }
        }
        return { prices: [], toppreiseItems: [], loginRequired: false };
      }
      if (sourceId === "digitec") {
        const digitecItems = extractDigitecItems(html, priceNodes, pageData.digitecCards || []);
        if (digitecItems.length > 0) {
          return { prices: [digitecItems[0].price], digitecItems, loginRequired: false };
        }
        if (priceNodes && priceNodes.length > 0) {
          const p = parsePriceText(priceNodes[0]);
          if (p !== null) {
            const fallbackItem = [{
              title: "Galaxus Top-Ergebnis",
              condition: "Neu (Bestpreis)",
              price: p,
              rawPrice: priceNodes[0],
            }];
            return { prices: [p], digitecItems: fallbackItem, loginRequired: false };
          }
        }
        return { prices: [], digitecItems: [], loginRequired: false };
      }
      if (sourceId === "ricardo") {
        const ricardoItems = extractRicardoItems(html, priceNodes, pageData.ricardoCards || []);
        if (ricardoItems.length > 0) {
          return { prices: ricardoItems.map(it => it.price), ricardoItems, loginRequired: false };
        }
        if (priceNodes && priceNodes.length > 0) {
          const domPrices = [];
          for (const txt of priceNodes) {
            const p = parsePriceText(txt);
            if (p !== null && p > 0) domPrices.push(p);
          }
          if (domPrices.length > 0) {
            return { prices: domPrices.slice(0, 30), loginRequired: false };
          }
        }
        return { prices: [], ricardoItems: [], loginRequired: false };
      }
      if (sourceId === "tutti") {
        const isSearchPage = (currentUrl || "").includes("/q/") || (currentUrl || "").includes("/suche");
        if (!isSearchPage) {
          console.warn(`[OccAIsion] [tutti] Nicht auf Suchergebnisseite (${currentUrl}), ignoriere Startseiten-Karten.`);
          return { prices: [], tuttiItems: [], finalUrl: currentUrl, loginRequired: false };
        }
        const tuttiItems = extractTuttiItems(html, priceNodes, pageData.tuttiCards || []);
        if (tuttiItems.length > 0) {
          return { prices: tuttiItems.map(it => it.price), tuttiItems, finalUrl: currentUrl, loginRequired: false };
        }
        if (priceNodes && priceNodes.length > 0) {
          const domPrices = [];
          for (const txt of priceNodes) {
            const p = parsePriceText(txt);
            if (p !== null && p > 0) domPrices.push(p);
          }
          if (domPrices.length > 0) {
            return { prices: domPrices.slice(0, 30), finalUrl: currentUrl, loginRequired: false };
          }
        }
        return { prices: [], tuttiItems: [], finalUrl: currentUrl, loginRequired: false };
      }
      const extracted = extractPricesFromHtml(sourceId, html);
      if (extracted.length > 0) {
        return { prices: extracted, loginRequired: false };
      }
      const domPrices = [];
      for (const txt of priceNodes || []) {
        const p = parsePriceText(txt);
        if (p !== null) domPrices.push(p);
      }
      if (
        sourceId === "ebay_de_sold" &&
        domPrices.length === 0 &&
        html.includes("signin.ebay.de")
      ) {
        return { prices: [], loginRequired: true };
      }
      return { prices: domPrices.slice(0, 30), loginRequired: false };
    }
  } catch (err) {
    console.warn(`[OccAIsion] Tab fallback failed for ${sourceId}:`, err);
  } finally {
    if (!keepTabsOpen && tab && tab.id !== undefined) {
      try {
        await api.tabs.remove(tab.id);
      } catch (_) {}
    } else if (keepTabsOpen && tab && tab.id !== undefined) {
      console.log(`[OccAIsion] [Debug] Tab #${tab.id} für ${sourceId} bleibt geöffnet (${url})`);
    }
  }
  return { prices: [], loginRequired: false };
}

async function scrapeSourceHybrid(sourceConfig, query, eurToChfRate = 0.94, keepTabsOpen = false) {
  let url = sourceConfig.url;
  let prices = [];
  let method = "fetch";
  let loginRequired = false;
  let ebayItems = [];
  let kleinanzeigenItems = [];
  let idealoItems = [];
  let toppreiseItems = [];
  let digitecItems = [];
  let ricardoItems = [];
  let tuttiItems = [];

  const TAB_ONLY_SOURCES = new Set(["digitec", "ricardo", "tutti"]);
  console.log(`[OccAIsion] [${sourceConfig.id}] Starte Abfrage: ${url}`);

  // Step 1: Fast background fetch() with 5s timeout (skipped for client-rendered SPA sources like Idealo)
  if (!TAB_ONLY_SOURCES.has(sourceConfig.id)) {
    try {
      const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
      const timer = controller ? setTimeout(() => controller.abort(), 5000) : null;
      try {
        const resp = await fetch(url, {
          credentials: "include",
          signal: controller ? controller.signal : undefined,
          headers: {
            "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8",
          },
        });
        if (resp.ok) {
          const html = await resp.text();
          if (sourceConfig.id === "ebay_de_sold" && isEbayLoginRequired(html, resp.url)) {
            loginRequired = true;
            console.warn(
              `[OccAIsion] [${sourceConfig.id}] fetch() wurde auf eBay-Login umgeleitet (${resp.url}). Prüfe Tab-Fallback...`
            );
          } else {
            if (sourceConfig.id === "ebay_de_sold") {
              ebayItems = extractEbayItemsFromHtml(html);
              prices = ebayItems.map(it => it.price);
            } else if (sourceConfig.id === "kleinanzeigen") {
              kleinanzeigenItems = extractKleinanzeigenItems(html);
              prices = kleinanzeigenItems.map(it => it.price);
            } else if (sourceConfig.id === "idealo") {
              idealoItems = extractIdealoItems(html);
              prices = idealoItems.map(it => it.price);
            } else if (sourceConfig.id === "toppreise") {
              toppreiseItems = extractToppreiseItems(html);
              prices = toppreiseItems.map(it => it.price);
            } else {
              prices = extractPricesFromHtml(sourceConfig.id, html);
            }
            console.log(
              `[OccAIsion] [${sourceConfig.id}] fetch() HTTP ${resp.status} (${html.length} Zeichen) -> ${prices.length} Preise extrahiert`
            );
          }
        } else {
          console.warn(`[OccAIsion] [${sourceConfig.id}] fetch() lieferte HTTP ${resp.status}`);
        }
      } finally {
        if (timer) clearTimeout(timer);
      }
    } catch (err) {
      console.warn(`[OccAIsion] [${sourceConfig.id}] Direct fetch fehlgeschlagen (${err.message}), nutze Tab-Fallback...`);
    }
  } else {
    console.log(`[OccAIsion] [${sourceConfig.id}] Überspringe fetch() (Client-SPA / Tab-Only Modus) -> nutze Browser-Tab...`);
  }

  // Step 2: Fallback to inactive background tab if fetch returned 0 prices (or for tab-only sources)
  if (prices.length === 0) {
    method = "tab";
    console.log(`[OccAIsion] [${sourceConfig.id}] Starte Hintergrund-Tab Fallback...`);
    const tabRes = await scrapeViaBackgroundTab(url, sourceConfig.id, keepTabsOpen, query);
    prices = tabRes.prices || [];
    if (tabRes.ebayItems && tabRes.ebayItems.length > 0) {
      ebayItems = tabRes.ebayItems;
    }
    if (tabRes.kleinanzeigenItems && tabRes.kleinanzeigenItems.length > 0) {
      kleinanzeigenItems = tabRes.kleinanzeigenItems;
    }
    if (tabRes.idealoItems && tabRes.idealoItems.length > 0) {
      idealoItems = tabRes.idealoItems;
    }
    if (tabRes.toppreiseItems && tabRes.toppreiseItems.length > 0) {
      toppreiseItems = tabRes.toppreiseItems;
    }
    if (tabRes.digitecItems && tabRes.digitecItems.length > 0) {
      digitecItems = tabRes.digitecItems;
    }
    if (tabRes.ricardoItems && tabRes.ricardoItems.length > 0) {
      ricardoItems = tabRes.ricardoItems;
    }
    if (tabRes.tuttiItems && tabRes.tuttiItems.length > 0) {
      tuttiItems = tabRes.tuttiItems;
    }
    if (tabRes.finalUrl && (tabRes.finalUrl.includes("/q/") || tabRes.finalUrl.includes("tutti.ch"))) {
      url = tabRes.finalUrl;
    }
    if (tabRes.loginRequired) {
      loginRequired = true;
    }
    console.log(`[OccAIsion] [${sourceConfig.id}] Hintergrund-Tab Ergebnis -> ${prices.length} Preise extrahiert (loginRequired=${loginRequired})`);
  } else if (keepTabsOpen) {
    // If keepTabsOpen is active and fetch succeeded, open the tab for inspection
    const api = getBrowserApi();
    if (api && api.tabs && api.tabs.create) {
      try {
        const tab = await api.tabs.create({ url, active: false });
        console.log(`[OccAIsion] [Debug] Tab #${tab.id} für ${sourceConfig.id} geöffnet zur Inspektion (${url})`);
      } catch (e) {
        console.warn(`[OccAIsion] Konnte Debug-Tab für ${sourceConfig.id} nicht öffnen:`, e);
      }
    }
  }

  const extra = {};
  if (prices.length === 0 && loginRequired) {
    extra.login_required = true;
    extra.error = "Login auf ebay.de erforderlich (bitte in Firefox auf ebay.de einloggen)";
    console.warn(
      `⚠️ [OccAIsion] [${sourceConfig.id}] eBay erfordert einen Login für verkaufte Artikel! Bitte in Firefox auf https://www.ebay.de einloggen.`
    );
  }

  if (sourceConfig.id === "ebay_de_sold") {
    if (ebayItems && ebayItems.length > 0) {
      extra.items = ebayItems;
      logEbayExtractedItems(ebayItems);
    }
  } else if (sourceConfig.id === "kleinanzeigen") {
    if (kleinanzeigenItems && kleinanzeigenItems.length > 0) {
      extra.items = kleinanzeigenItems;
      logKleinanzeigenExtractedItems(kleinanzeigenItems);
    }
    extra.query = query || "";
  } else if (sourceConfig.id === "idealo") {
    if (idealoItems && idealoItems.length > 0) {
      extra.items = idealoItems;
      logIdealoExtractedItems(idealoItems);
      const matched = selectBestMatchingItem(idealoItems, query);
      extra.confidence = matched ? calculateTokenOverlap(query, matched.title || "") : 1.0;
      prices = matched ? [matched.price] : [idealoItems[0].price];
    }
  } else if (sourceConfig.id === "toppreise") {
    if (toppreiseItems && toppreiseItems.length > 0) {
      extra.items = toppreiseItems;
      logToppreiseExtractedItems(toppreiseItems);
      const matched = selectBestMatchingItem(toppreiseItems, query);
      extra.confidence = matched ? calculateTokenOverlap(query, matched.title || "") : 1.0;
      prices = matched ? [matched.price] : [toppreiseItems[0].price];
    }
  } else if (sourceConfig.id === "digitec") {
    if (digitecItems && digitecItems.length > 0) {
      extra.items = digitecItems;
      logDigitecExtractedItems(digitecItems);
      const matched = selectBestMatchingItem(digitecItems, query);
      extra.confidence = matched ? calculateTokenOverlap(query, matched.title || "") : 1.0;
      prices = matched ? [matched.price] : [digitecItems[0].price];
    }
  } else if (sourceConfig.id === "ricardo") {
    if (ricardoItems && ricardoItems.length > 0) {
      extra.items = ricardoItems;
      logRicardoExtractedItems(ricardoItems);
    }
  } else if (sourceConfig.id === "tutti") {
    if (tuttiItems && tuttiItems.length > 0) {
      extra.items = tuttiItems;
      logTuttiExtractedItems(tuttiItems);
    }
  }

  const stats = computeSourceStats(sourceConfig, prices, url, method, eurToChfRate, extra);
  console.log(
    `[OccAIsion] [${sourceConfig.id}] Fertig (${method}): ${stats.sample_count} Treffer, Median=${stats.median_price} ${stats.currency}` +
      (stats.login_required ? " [LOGIN ERFORDERLICH]" : "")
  );
  return stats;
}

const activeScrapePromises = new Map();

async function runDeduplicatedScrape(requestId, query, eurToChfRate = 0.94, enabledSources = null, keepTabsOpen = false) {
  const sourcesKey = Array.isArray(enabledSources) ? enabledSources.slice().sort().join(",") : "all";
  const key = requestId ? `${requestId}_${sourcesKey}_keep_${keepTabsOpen}` : `q_${query}_${sourcesKey}_keep_${keepTabsOpen}`;
  if (activeScrapePromises.has(key)) {
    return activeScrapePromises.get(key);
  }

  const p = (async () => {
    console.log(`[OccAIsion] === Starte Preisrecherche (${key}) für '${query}' (enabled: ${sourcesKey}, keepTabs: ${keepTabsOpen}) ===`);
    const result = await scrapeAllPriceSources(query, eurToChfRate, enabledSources, keepTabsOpen);
    console.log(`[OccAIsion] === Preisrecherche abgeschlossen (${key}) ===`, result);
    return result;
  })();

  activeScrapePromises.set(key, p);
  try {
    return await p;
  } finally {
    setTimeout(() => activeScrapePromises.delete(key), 15000);
  }
}

async function scrapeAllPriceSources(query, eurToChfRate = 0.94, enabledSources = null, keepTabsOpen = false) {
  const links = buildVerificationLinks(query);
  let sourceConfigs = [
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
    {
      id: "tutti",
      label: "Tutti.ch Suche",
      currency: "CHF",
      url: links.tutti_search_url || "https://www.tutti.ch/de",
    },
  ];

  if (Array.isArray(enabledSources)) {
    sourceConfigs = sourceConfigs.filter(cfg => enabledSources.includes(cfg.id));
  }

  const settled = await Promise.allSettled(
    sourceConfigs.map(cfg => scrapeSourceHybrid(cfg, query, eurToChfRate, keepTabsOpen))
  );

  const sourcesMap = {};
  for (let i = 0; i < sourceConfigs.length; i++) {
    const cfg = sourceConfigs[i];
    const outcome = settled[i];
    if (outcome.status === "fulfilled") {
      const r = outcome.value;
      sourcesMap[r.source_id || cfg.id] = r;
    } else {
      console.warn(`[OccAIsion] [${cfg.id}] Scraping fehlgeschlagen:`, outcome.reason);
      const errMsg =
        outcome.reason && outcome.reason.message
          ? outcome.reason.message
          : String(outcome.reason || "Unbekannter Fehler");
      sourcesMap[cfg.id] = {
        source_id: cfg.id,
        label: cfg.label,
        currency: cfg.currency,
        url: cfg.url,
        prices_raw: [],
        prices_chf: [],
        count: 0,
        stats: null,
        method: "error",
        error: errMsg,
      };
    }
  }

  if (sourcesMap.tutti && sourcesMap.tutti.url) {
    links.tutti_search_url = sourcesMap.tutti.url;
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
    if (request.action === "SET_AUTH_TOKEN") {
      cachedAuthToken = request.token || null;
      if (browserApi && browserApi.storage && browserApi.storage.local && request.token) {
        browserApi.storage.local.set({ occaision_auth_token: request.token });
      }
      sendResponse({ ok: true });
      return true;
    }

    if (request.action === "LIST_DRAFTS") {
      getAuthHeaders().then(headers => {
        fetch(`${BACKEND_BASE}/api/drafts`, { headers })
          .then(res => {
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return res.json();
          })
          .then(drafts => sendResponse({ ok: true, drafts }))
          .catch(err => {
            const isAuth = String(err.message).includes("401");
            sendResponse({ ok: false, error: err.message, unauthorized: isAuth });
          });
      });
      return true;
    }

    if (request.action === "GET_DRAFT") {
      getAuthHeaders().then(headers => {
        fetch(`${BACKEND_BASE}/api/drafts/${request.draftId}`, { headers })
          .then(res => {
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return res.json();
          })
          .then(draft => sendResponse({ ok: true, draft }))
          .catch(err => {
            const isAuth = String(err.message).includes("401");
            sendResponse({ ok: false, error: err.message, unauthorized: isAuth });
          });
      });
      return true;
    }

    if (request.action === "FETCH_DRAFT_IMAGES") {
      getAuthHeaders().then(headers => {
        fetch(`${BACKEND_BASE}/api/drafts/${request.draftId}`, { headers })
          .then(res => {
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return res.json();
          })
          .then(async draft => {
            const imagePayloads = [];
            for (const img of draft.images || []) {
              const imgUrl = `${BACKEND_BASE}/api/drafts/${draft.id}/images/${img.id}/active`;
              const imgRes = await fetch(imgUrl, { headers });
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
      });
      return true;
    }

    if (request.action === "SCRAPE_ALL_PRICE_SOURCES") {
      runDeduplicatedScrape(
        request.requestId || "",
        request.query || "",
        request.eurToChfRate || 0.94,
        request.enabledSources || null,
        Boolean(request.keepTabsOpen)
      )
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
    isEbayLoginRequired,
    extractPricesFromHtml,
    extractEbayItemsFromHtml,
    logEbayExtractedItems,
    extractKleinanzeigenItems,
    logKleinanzeigenExtractedItems,
    extractIdealoItems,
    logIdealoExtractedItems,
    extractToppreiseItems,
    logToppreiseExtractedItems,
    extractDigitecItems,
    logDigitecExtractedItems,
    extractRicardoItems,
    logRicardoExtractedItems,
    extractTuttiItems,
    logTuttiExtractedItems,
    calculateTokenOverlap,
    selectBestMatchingItem,
    computeSourceStats,
    scrapeViaBackgroundTab,
    scrapeSourceHybrid,
    scrapeAllPriceSources,
  };
}
