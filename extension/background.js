// Background Service Worker for Seller Assistant
// Bypasses CORS and CSP by executing HTTP calls and hybrid price scraping inside the WebExtension privileged context.

function getBrowserApi() {
  if (typeof browser !== "undefined") return browser;
  if (typeof chrome !== "undefined") return chrome;
  return null;
}

const browserApi = getBrowserApi();
const BACKEND_BASE = "http://127.0.0.1:8000";

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
    kleinanzeigen_search_url: `https://www.kleinanzeigen.de/anbieter:privat/s-${q}/k0+global.zustand:alright%2Clike_new%2Cok`,
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
      `[Seller Assistant] [ebay_de_sold] 'Ergebnisse für weniger Suchbegriffe' an Position ${fewerWordsMatch.index} erkannt – filtere alle nachfolgenden ungenauen Treffer heraus.`
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

function logEbayExtractedItems(items) {
  if (!items || items.length === 0) {
    console.log("[Seller Assistant] [ebay_de_sold] Keine verkauften Artikel extrahiert (0 Treffer).");
    return;
  }
  console.group(`[Seller Assistant] [ebay_de_sold] Extrahierte verkaufte Artikel (${items.length} Treffer):`);
  items.forEach((it, idx) => {
    console.log(
      `  #${idx + 1}: ${it.price} € | Zustand: [${it.condition}] | Titel: "${it.title}"`
    );
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
  if (!items || items.length === 0) {
    console.log("[Seller Assistant] [kleinanzeigen] Keine Kleinanzeigen-Artikel extrahiert (0 Treffer).");
    return;
  }
  console.group(`[Seller Assistant] [kleinanzeigen] Extrahierte Kleinanzeigen-Artikel (${items.length} Treffer):`);
  items.forEach((it, idx) => {
    console.log(
      `  #${idx + 1}: ${it.price} € | Zustand: [${it.condition || "Gebraucht"}] | Titel: "${it.title}"`
    );
  });
  console.groupEnd();

  if (typeof console.table === "function") {
    try {
      console.table(
        items.map((it, idx) => ({
          "#": idx + 1,
          "Preis (€)": it.price,
          "Zustand": it.condition || "Gebraucht",
          "Titel": it.title,
        }))
      );
    } catch (_) {}
  }
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

  // 2. HTML regex for .sr-resultList_* and .sr-detailedPriceInfo__price_*
  if (html && typeof html === "string") {
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
  if (!items || items.length === 0) {
    console.log("[Seller Assistant] [idealo] Kein Idealo-Neupreis extrahiert (0 Treffer).");
    return;
  }
  const top = items[0];
  console.group(`[Seller Assistant] [idealo] Idealo Neupreis (Bestpreis des ersten Produkts):`);
  console.log(`  Top-Treffer: ${top.price} € | Zustand: [${top.condition || "Neu"}] | Titel: "${top.title}"`);
  console.groupEnd();

  if (typeof console.table === "function") {
    try {
      console.table([
        {
          "Preis (€)": top.price,
          "Zustand": top.condition || "Neu",
          "Produktname": top.title,
        }
      ]);
    } catch (_) {}
  }
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
  if (!items || items.length === 0) {
    console.log("[Seller Assistant] [toppreise] Kein Toppreise-Neupreis extrahiert (0 Treffer).");
    return;
  }
  const top = items[0];
  console.group(`[Seller Assistant] [toppreise] Toppreise Neupreis (Bestpreis des ersten Produkts):`);
  console.log(`  Top-Treffer: ${top.price} CHF | Zustand: [${top.condition || "Neu"}] | Titel: "${top.title}"`);
  console.groupEnd();

  if (typeof console.table === "function") {
    try {
      console.table([
        {
          "Preis (CHF)": top.price,
          "Zustand": top.condition || "Neu",
          "Produktname": top.title,
        }
      ]);
    } catch (_) {}
  }
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
  };
}

async function scrapeViaBackgroundTab(url, sourceId, keepTabsOpen = false) {
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

    // Wait 1200ms (or 2000ms for Idealo SPA) for client-side hydration
    const waitTime = sourceId === "idealo" ? 2000 : 1200;
    await new Promise(r => setTimeout(r, waitTime));

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
          return { html, currentUrl, priceNodes, idealoCards, toppreiseCards };
        },
      });
      if (results && results[0] && results[0].result) {
        pageData = results[0].result;
      }
    } catch (scriptErr) {
      console.warn(`[Seller Assistant] Tab-Scripting fehlgeschlagen (${scriptErr.message}). Versuche content.js Message-Fallback...`);
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
    console.warn(`[Seller Assistant] Tab fallback failed for ${sourceId}:`, err);
  } finally {
    if (!keepTabsOpen && tab && tab.id !== undefined) {
      try {
        await api.tabs.remove(tab.id);
      } catch (_) {}
    } else if (keepTabsOpen && tab && tab.id !== undefined) {
      console.log(`[Seller Assistant] [Debug] Tab #${tab.id} für ${sourceId} bleibt geöffnet (${url})`);
    }
  }
  return { prices: [], loginRequired: false };
}

async function scrapeSourceHybrid(sourceConfig, query, eurToChfRate = 0.94, keepTabsOpen = false) {
  const url = sourceConfig.url;
  let prices = [];
  let method = "fetch";
  let loginRequired = false;
  let ebayItems = [];
  let kleinanzeigenItems = [];
  let idealoItems = [];
  let toppreiseItems = [];

  const TAB_ONLY_SOURCES = new Set(["idealo"]);
  console.log(`[Seller Assistant] [${sourceConfig.id}] Starte Abfrage: ${url}`);

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
              `[Seller Assistant] [${sourceConfig.id}] fetch() wurde auf eBay-Login umgeleitet (${resp.url}). Prüfe Tab-Fallback...`
            );
          } else {
            if (sourceConfig.id === "ebay_de_sold") {
              ebayItems = extractEbayItemsFromHtml(html);
              prices = ebayItems.map(it => it.price);
            } else if (sourceConfig.id === "kleinanzeigen") {
              kleinanzeigenItems = extractKleinanzeigenItems(html);
              prices = kleinanzeigenItems.map(it => it.price);
            } else if (sourceConfig.id === "toppreise") {
              toppreiseItems = extractToppreiseItems(html);
              prices = toppreiseItems.map(it => it.price);
            } else {
              prices = extractPricesFromHtml(sourceConfig.id, html);
            }
            console.log(
              `[Seller Assistant] [${sourceConfig.id}] fetch() HTTP ${resp.status} (${html.length} Zeichen) -> ${prices.length} Preise extrahiert`
            );
          }
        } else {
          console.warn(`[Seller Assistant] [${sourceConfig.id}] fetch() lieferte HTTP ${resp.status}`);
        }
      } finally {
        if (timer) clearTimeout(timer);
      }
    } catch (err) {
      console.warn(`[Seller Assistant] [${sourceConfig.id}] Direct fetch fehlgeschlagen (${err.message}), nutze Tab-Fallback...`);
    }
  } else {
    console.log(`[Seller Assistant] [${sourceConfig.id}] Überspringe fetch() (Client-SPA / Tab-Only Modus) -> nutze Browser-Tab...`);
  }

  // Step 2: Fallback to inactive background tab if fetch returned 0 prices (or for tab-only sources)
  if (prices.length === 0) {
    method = "tab";
    console.log(`[Seller Assistant] [${sourceConfig.id}] Starte Hintergrund-Tab Fallback...`);
    const tabRes = await scrapeViaBackgroundTab(url, sourceConfig.id, keepTabsOpen);
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
    if (tabRes.loginRequired) {
      loginRequired = true;
    }
    console.log(`[Seller Assistant] [${sourceConfig.id}] Hintergrund-Tab Ergebnis -> ${prices.length} Preise extrahiert (loginRequired=${loginRequired})`);
  } else if (keepTabsOpen) {
    // If keepTabsOpen is active and fetch succeeded, open the tab for inspection
    const api = getBrowserApi();
    if (api && api.tabs && api.tabs.create) {
      try {
        const tab = await api.tabs.create({ url, active: false });
        console.log(`[Seller Assistant] [Debug] Tab #${tab.id} für ${sourceConfig.id} geöffnet zur Inspektion (${url})`);
      } catch (e) {
        console.warn(`[Seller Assistant] Konnte Debug-Tab für ${sourceConfig.id} nicht öffnen:`, e);
      }
    }
  }

  const extra = {};
  if (prices.length === 0 && loginRequired) {
    extra.login_required = true;
    extra.error = "Login auf ebay.de erforderlich (bitte in Firefox auf ebay.de einloggen)";
    console.warn(
      `⚠️ [Seller Assistant] [${sourceConfig.id}] eBay erfordert einen Login für verkaufte Artikel! Bitte in Firefox auf https://www.ebay.de einloggen.`
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
  } else if (sourceConfig.id === "idealo") {
    if (idealoItems && idealoItems.length > 0) {
      extra.items = idealoItems;
      logIdealoExtractedItems(idealoItems);
      // For Idealo: The first card (.sr-resultList_* .sr-detailedPriceInfo__price_*) is the primary product's best new price!
      prices = [idealoItems[0].price];
    }
  } else if (sourceConfig.id === "toppreise") {
    if (toppreiseItems && toppreiseItems.length > 0) {
      extra.items = toppreiseItems;
      logToppreiseExtractedItems(toppreiseItems);
      // For Toppreise: The first product in the list or product page is the primary product's best new price!
      prices = [toppreiseItems[0].price];
    }
  }

  const stats = computeSourceStats(sourceConfig, prices, url, method, eurToChfRate, extra);
  console.log(
    `[Seller Assistant] [${sourceConfig.id}] Fertig (${method}): ${stats.sample_count} Treffer, Median=${stats.median_price} ${stats.currency}` +
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
    console.log(`[Seller Assistant] === Starte Preisrecherche (${key}) für '${query}' (enabled: ${sourcesKey}, keepTabs: ${keepTabsOpen}) ===`);
    const result = await scrapeAllPriceSources(query, eurToChfRate, enabledSources, keepTabsOpen);
    console.log(`[Seller Assistant] === Preisrecherche abgeschlossen (${key}) ===`, result);
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
  ];

  if (Array.isArray(enabledSources)) {
    sourceConfigs = sourceConfigs.filter(cfg => enabledSources.includes(cfg.id));
  }

  const results = await Promise.all(
    sourceConfigs.map(cfg => scrapeSourceHybrid(cfg, query, eurToChfRate, keepTabsOpen))
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
    computeSourceStats,
    scrapeViaBackgroundTab,
    scrapeSourceHybrid,
    scrapeAllPriceSources,
  };
}
