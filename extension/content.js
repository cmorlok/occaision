// Content Script for OccAIsion Smart-Panel
// Injected into ricardo.ch and tutti.ch listing creation wizards.

const browserApi = typeof browser !== "undefined" ? browser : (typeof chrome !== "undefined" ? chrome : null);

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
  const win = typeof window !== "undefined" ? (window.wrappedJSObject || window) : null;

  let prototype = Object.getPrototypeOf(target);
  let descriptor = Object.getOwnPropertyDescriptor(prototype, "value");

  while (prototype && !descriptor) {
    prototype = Object.getPrototypeOf(prototype);
    if (prototype) {
      descriptor = Object.getOwnPropertyDescriptor(prototype, "value");
    }
  }

  const strVal = value !== null && value !== undefined ? String(value) : "";

  try {
    target.dispatchEvent(new Event("focus", { bubbles: true }));
  } catch (e) {}

  if (descriptor && descriptor.set) {
    descriptor.set.call(target, strVal);
  } else {
    target.value = strVal;
  }

  target.dispatchEvent(new Event("input", { bubbles: true }));
  target.dispatchEvent(new Event("change", { bubbles: true }));
  try {
    target.dispatchEvent(new Event("blur", { bubbles: true }));
  } catch (e) {}
}

// Helper: Fill Ricardo prices (Startpreis & Sofort-Kaufpreis)
async function fillRicardoPrices(draft, data) {
  function formatPrice(val) {
    if (val === null || val === undefined || val === "") return "";
    const n = Number(val);
    if (isNaN(n)) return String(val);
    return Number.isInteger(n) ? String(n) : n.toFixed(2);
  }

  // 1. Startpreis (Auktion)
  let startPriceInput = document.getElementById("SellingUI.start_price");
  if (!startPriceInput) {
    startPriceInput = document.querySelector(
      'input[id="SellingUI.start_price"], input[id*="start_price" i], input[id*="start-price" i], input[id*="startprice" i], input[name*="start_price" i], input[name*="startPrice" i], input[name*="start-price" i], input[aria-describedby*="start_price" i], input[aria-label*="Startpreis" i], input[data-testid*="start-price" i], input[data-testid*="start_price" i]'
    );
  }
  if (!startPriceInput) {
    const startLabel = Array.from(document.querySelectorAll("label")).find(l =>
      /startpreis|startgebot/i.test(l.textContent || "")
    );
    if (startLabel) {
      if (startLabel.htmlFor) startPriceInput = document.getElementById(startLabel.htmlFor);
      if (!startPriceInput) {
        startPriceInput = startLabel.closest(".MuiFormControl-root, .MuiTextField-root, div")?.querySelector('input[type="number"], input[type="text"]');
      }
    }
  }
  if (!startPriceInput) {
    const formControl = Array.from(document.querySelectorAll(".MuiFormControl-root, .MuiTextField-root")).find(fc =>
      /startpreis|startgebot/i.test(fc.textContent || "")
    );
    if (formControl) {
      startPriceInput = formControl.querySelector('input[type="number"], input[type="text"]');
    }
  }

  if (startPriceInput && data.startPrice !== null && data.startPrice !== undefined) {
    setNativeValue(startPriceInput, formatPrice(data.startPrice));
  }

  // 2. Sofort-Kaufpreis (Fixed Price / Buy Now)
  // Check if Sofort-Kauf toggle is present
  const fixedPriceSwitch = document.querySelector('input[type="checkbox"][value="FixedPrice"]');
  const isSwitchChecked = Boolean(
    fixedPriceSwitch && (
      fixedPriceSwitch.checked ||
      (fixedPriceSwitch.closest && fixedPriceSwitch.closest('.MuiSwitch-switchBase')?.classList?.contains('Mui-checked')) ||
      fixedPriceSwitch.parentElement?.classList?.contains('Mui-checked')
    )
  );

  // If Sofort-Kauf is desired and switch is not checked, activate the toggle
  if (fixedPriceSwitch && !isSwitchChecked && data.buyNowPrice && Number(data.buyNowPrice) > 0) {
    fixedPriceSwitch.click();
    await new Promise(r => setTimeout(r, 200));
  }

  // Find Sofort-Kaufpreis input: on Ricardo this has id="price"
  let buynowPriceInput = document.getElementById("price")
    || document.querySelector('input[id="price"], input[aria-describedby*="price-helper-text"]')
    || document.getElementById("SellingUI.buy_now_price")
    || document.getElementById("SellingUI.fixed_price")
    || document.getElementById("SellingUI.buy_now")
    || document.getElementById("SellingUI.buynow_price")
    || document.getElementById("SellingUI.buyItNowPrice");

  if (!buynowPriceInput) {
    const buyNowLabel = Array.from(document.querySelectorAll("label")).find(l =>
      /sofort-?kauf/i.test(l.textContent || "")
    );
    if (buyNowLabel) {
      if (buyNowLabel.htmlFor) buynowPriceInput = document.getElementById(buyNowLabel.htmlFor);
      if (!buynowPriceInput) {
        buynowPriceInput = buyNowLabel.closest(".MuiFormControl-root, .MuiTextField-root, div")?.querySelector('input[type="number"], input[type="text"]');
      }
    }
  }

  if (!buynowPriceInput) {
    buynowPriceInput = document.querySelector(
      'input[id="SellingUI.buy_now_price"], input[id="SellingUI.fixed_price"], input[id*="buy_now" i], input[id*="buynow" i], input[id*="fixed_price" i], input[id*="buy-now" i], input[name*="buyNow" i], input[name*="buy_now" i], input[name*="fixed_price" i], input[name*="buyItNow" i], input[aria-describedby*="buy_now" i], input[aria-describedby*="fixed_price" i], input[aria-label*="sofort" i], input[data-testid*="buy-now" i], input[data-testid*="fixed-price" i]'
    );
  }

  if (buynowPriceInput && data.buyNowPrice !== null && data.buyNowPrice !== undefined) {
    setNativeValue(buynowPriceInput, formatPrice(data.buyNowPrice));
  }
}

// Helper: Configure Ricardo shipping options (Versand & Abholung)
async function fillRicardoShipping(draft) {
  function formatPrice(val) {
    if (val === null || val === undefined || val === "") return "";
    const n = Number(val);
    if (isNaN(n)) return String(val);
    return Number.isInteger(n) ? String(n) : n.toFixed(2);
  }

  const presetId = draft?.ricardo?.shipping_preset_id || "b_post_2kg";
  const isPickupOnly = presetId === "pickup_only";

  const shippingSwitch = document.querySelector('input[type="checkbox"][value="Shipping"]');
  const pickupSwitch = document.querySelector('input[type="checkbox"][value="Pickup"]');

  const isShippingChecked = () => Boolean(
    shippingSwitch && (
      shippingSwitch.checked ||
      (shippingSwitch.closest && shippingSwitch.closest('.MuiSwitch-switchBase')?.classList?.contains('Mui-checked')) ||
      shippingSwitch.parentElement?.classList?.contains('Mui-checked')
    )
  );

  const isPickupChecked = () => Boolean(
    pickupSwitch && (
      pickupSwitch.checked ||
      (pickupSwitch.closest && pickupSwitch.closest('.MuiSwitch-switchBase')?.classList?.contains('Mui-checked')) ||
      pickupSwitch.parentElement?.classList?.contains('Mui-checked')
    )
  );

  // 1. Handle Pickup Only
  if (isPickupOnly) {
    if (shippingSwitch && isShippingChecked()) {
      shippingSwitch.click();
      await new Promise(r => setTimeout(r, 150));
    }
    if (pickupSwitch && !isPickupChecked()) {
      pickupSwitch.click();
      await new Promise(r => setTimeout(r, 150));
    }
    return true;
  }

  // 2. Enable Shipping switch if not enabled
  if (shippingSwitch && !isShippingChecked()) {
    shippingSwitch.click();
    await new Promise(r => setTimeout(r, 250));
  }

  // Ensure Pickup is also enabled if pickup is allowed (standard for Ricardo)
  if (pickupSwitch && !isPickupChecked()) {
    pickupSwitch.click();
    await new Promise(r => setTimeout(r, 100));
  }

  // 3. Check if standard default (Paket bis 2kg, Economy, 9.00 CHF) is what we need
  const needsNonDefault = presetId !== "b_post_2kg";
  if (!needsNonDefault) {
    // Ricardo's default shipping package is already "Paket, 2kg, Economy, CHF 9.00"
    return true;
  }

  // 4. If we need a non-default preset (e.g. b_post_10kg, b_post_30kg, kleinsendung_100g, kleinsendung_500g):
  // Find and click the "Bearbeiten" button in the shipping section
  const deliverySection = (document.querySelector('.forBloomreach_DeliverySectionTitle')?.closest ? document.querySelector('.forBloomreach_DeliverySectionTitle').closest('.MuiBox-root') : null)
    || (shippingSwitch?.closest ? shippingSwitch.closest('.MuiBox-root')?.parentElement : null);

  const editBtn = Array.from((deliverySection || document).querySelectorAll("button")).find(b =>
    /bearbeiten/i.test(b.textContent || "")
  );

  if (!editBtn) {
    return false;
  }

  editBtn.click();
  await new Promise(r => setTimeout(r, 300));

  // 5. In Dialog 1 ("Versand"): choose "Brief" or "Paket"
  let dialog = document.querySelector('[role="dialog"]');
  if (!dialog) return false;

  const isBrief = presetId.includes("100g") || presetId.includes("500g") || presetId.includes("brief");

  const categoryBtn = Array.from(dialog.querySelectorAll('button[role="checkbox"], button')).find(b => {
    const txt = (b.textContent || "").toLowerCase();
    return isBrief ? txt.includes("brief") : txt.includes("paket");
  });

  if (categoryBtn) {
    categoryBtn.click();
    await new Promise(r => setTimeout(r, 300));
  }

  // 6. In Dialog 2 ("Paket" or "Brief"): choose weight chip & verify cost
  dialog = document.querySelector('[role="dialog"]');
  if (dialog) {
    let targetWeightRegex = null;
    let targetCost = null;

    if (presetId.includes("10kg")) {
      targetWeightRegex = /10\s*kg/i;
      targetCost = 12.00;
    } else if (presetId.includes("30kg")) {
      targetWeightRegex = /30\s*kg/i;
      targetCost = 21.00;
    } else if (presetId.includes("100g")) {
      targetWeightRegex = /100\s*g/i;
      targetCost = 3.00;
    } else if (presetId.includes("500g")) {
      targetWeightRegex = /500\s*g/i;
      targetCost = 3.40;
    } else {
      targetWeightRegex = /2\s*kg/i;
      targetCost = 9.00;
    }

    if (targetWeightRegex) {
      const weightChip = Array.from(dialog.querySelectorAll('[role="radio"], .MuiChip-root')).find(c =>
        targetWeightRegex.test(c.textContent || "")
      );
      if (weightChip) {
        weightChip.click();
        await new Promise(r => setTimeout(r, 150));
      }
    }

    // Ensure Economy is selected
    const economyChip = Array.from(dialog.querySelectorAll('[role="radio"], .MuiChip-root')).find(c =>
      /economy/i.test(c.textContent || "")
    );
    if (economyChip && economyChip.getAttribute('aria-checked') === 'false') {
      economyChip.click();
      await new Promise(r => setTimeout(r, 100));
    }

    // Set cost input if present
    const costInput = dialog.querySelector('input#shipping-cost-input, input[id*="shipping-cost" i]');
    if (costInput && targetCost !== null) {
      setNativeValue(costInput, formatPrice(targetCost));
    }

    // Click "Speichern" button
    const saveBtn = Array.from(dialog.querySelectorAll("button")).find(b =>
      /speichern/i.test(b.textContent || "") && !b.disabled
    );
    if (saveBtn) {
      saveBtn.click();
      await new Promise(r => setTimeout(r, 250));
    }
  }

  return true;
}

// Helper: Select an option in a Material-UI Select (combobox + popover)
async function fillMuiSelect(comboboxEl, matchFn) {
  if (!comboboxEl) return false;
  try {
    comboboxEl.focus();
    comboboxEl.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true }));
    comboboxEl.click();

    for (let attempt = 0; attempt < 15; attempt++) {
      await new Promise(r => setTimeout(r, 60));
      const options = Array.from(
        document.querySelectorAll(
          '[role="listbox"] [role="option"], .MuiPopover-root [role="option"], .MuiPopover-root li[role="menuitem"], .MuiMenu-list li, .MuiMenuItem-root'
        )
      );
      if (options.length > 0) {
        const match = options.find(matchFn);
        if (match) {
          match.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true }));
          match.click();
          return true;
        }
      }
    }

    // Fallback: close popover if not selected
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", code: "Escape", bubbles: true }));
  } catch (e) {
    console.warn("[OccAIsion] Error in fillMuiSelect:", e);
  }
  return false;
}

// Helper: Navigate and auto-select category on Tutti if match exists, otherwise keep dropdown open for user
async function autoSelectTuttiCategory(suggestion, productTitle) {
  const listingTypeInput = document.querySelector('input[name="listingType"]');
  if (listingTypeInput && listingTypeInput.value && listingTypeInput.value.trim() !== "") {
    return { ok: true, status: "already_selected" };
  }

  // 1. Open category picker if not open
  let popover = document.querySelector('.MuiPopover-root:not(.MuiModal-hidden)');
  if (!popover) {
    const catBtn = Array.from(document.querySelectorAll("button")).find(b =>
      /kategorie\s*wählen/i.test(b.textContent || "")
    );
    if (!catBtn) return { ok: false, status: "button_not_found" };
    catBtn.click();
    await new Promise(r => setTimeout(r, 220));
    popover = document.querySelector('.MuiPopover-root');
  }

  if (!popover) return { ok: false, status: "popover_not_found" };

  const searchText = `${suggestion || ""} ${productTitle || ""}`.toLowerCase();

  function getMenuItems() {
    return Array.from(
      document.querySelectorAll(
        '.MuiPopover-root [role="menuitem"], .MuiPopover-root li, .MuiMenuItem-root'
      )
    ).filter(el => {
      const t = (el.textContent || "").trim();
      return t && t !== "Zurück";
    });
  }

  const TOP_CAT_KEYWORDS = [
    { name: "Elektronik", words: ["elektronik", "computer", "drucker", "scanner", "handy", "telefon", "tv", "audio", "hifi", "foto", "kamera", "tablet", "software", "laserjet"] },
    { name: "Fahrzeuge", words: ["fahrzeug", "auto", "motorrad", "roller", "nutzfahrzeug", "wohnmobil", "boot", "autozubehör", "pkw"] },
    { name: "Immobilien", words: ["immobilie", "wohnung", "haus", "grundstück", "wg", "parkplatz"] },
    { name: "Mode", words: ["mode", "kleidung", "damen", "herren", "schuhe", "uhr", "schmuck", "tasche"] },
    { name: "Zuhause", words: ["zuhause", "haushalt", "möbel", "beleuchtung", "lampe", "deko", "küche", "garten", "handwerk", "werkzeug", "baumaterial"] },
    { name: "Hobbys", words: ["hobby", "tier", "hund", "katze", "sport", "velo", "fahrrad", "ski", "buch", "spiel", "game", "konsole", "musik", "instrument", "film", "sammeln"] },
    { name: "Dienstleistungen", words: ["dienstleistung", "service", "reparatur", "unterricht", "reinigung", "umzug", "job", "stelle"] },
    { name: "Familie", words: ["familie", "baby", "kind", "kinderwagen", "kinderzimmer"] }
  ];

  for (let step = 0; step < 3; step++) {
    if (listingTypeInput && listingTypeInput.value && listingTypeInput.value.trim() !== "") {
      return { ok: true, status: "selected" };
    }

    const items = getMenuItems();
    if (items.length === 0) break;

    const itemTexts = items.map(i => (i.textContent || "").trim());
    const isTopLevel = itemTexts.includes("Elektronik") || itemTexts.includes("Fahrzeuge") || itemTexts.includes("Mode");

    let matchedItem = null;

    if (isTopLevel) {
      for (const cat of TOP_CAT_KEYWORDS) {
        if (cat.words.some(w => searchText.includes(w))) {
          matchedItem = items.find(i => (i.textContent || "").trim() === cat.name);
          if (matchedItem) break;
        }
      }
    } else {
      const parts = (suggestion || "")
        .split(/[>/,]/)
        .map(p => p.trim().toLowerCase())
        .filter(Boolean);

      for (const part of parts) {
        matchedItem = items.find(i => {
          const t = (i.textContent || "").trim().toLowerCase();
          return t === part || t.includes(part) || part.includes(t);
        });
        if (matchedItem) break;
      }

      if (!matchedItem) {
        if (/drucker|scanner|laserjet|toner|patrone|tintenstrahl/i.test(searchText)) {
          matchedItem = items.find(i => /komponenten|zubehör|drucker/i.test(i.textContent || ""));
        } else if (/computer|pc|laptop/i.test(searchText)) {
          matchedItem = items.find(i => /^computer$/i.test((i.textContent || "").trim()));
        }
      }
    }

    if (matchedItem) {
      console.log("[OccAIsion] Tutti Kategorie-Klick:", matchedItem.textContent.trim());
      matchedItem.click();
      await new Promise(r => setTimeout(r, 220));
    } else {
      // Recommended category does not exist at this level: keep dropdown open for user!
      console.log("[OccAIsion] Empfohlene Kategorie nicht gefunden, Dropdown bleibt offen für manuelle Auswahl.");
      return { ok: false, status: "manual_selection_required" };
    }
  }

  const finalCheck = listingTypeInput && listingTypeInput.value && listingTypeInput.value.trim() !== "";
  return { ok: finalCheck, status: finalCheck ? "selected" : "manual_selection_required" };
}

// Firefox Xray-Safe File Injector for HTMLInputElement and react-dropzone
function injectFilesIntoInput(fileInput, imagePayloads) {
  if (!fileInput || !imagePayloads || imagePayloads.length === 0) return;

  try {
    const dt = new DataTransfer();

    for (const img of imagePayloads) {
      const bytes = dataUrlToUint8Array(img.dataUrl);
      const file = new File([bytes], img.filename || "image.jpg", {
        type: img.mimeType || "image/jpeg",
        lastModified: Date.now()
      });
      dt.items.add(file);
    }

    const targetInput = fileInput.wrappedJSObject || fileInput;
    try {
      fileInput.files = dt.files;
    } catch (e1) {
      try {
        targetInput.files = dt.files;
      } catch (e2) {
        console.warn("[OccAIsion] Direct fileInput.files assignment failed:", e2);
      }
    }

    fileInput.dispatchEvent(new Event("input", { bubbles: true }));
    fileInput.dispatchEvent(new Event("change", { bubbles: true }));
    if (targetInput !== fileInput) {
      try {
        targetInput.dispatchEvent(new Event("input", { bubbles: true }));
        targetInput.dispatchEvent(new Event("change", { bubbles: true }));
      } catch (_) {}
    }

    // Also dispatch synthetic drop event on dropzone container if available
    const dropzone = fileInput.closest("[class*='dropzone'], [class*='upload'], [data-testid*='upload'], [role='presentation']") || fileInput.parentElement;
    if (dropzone && typeof DragEvent !== "undefined") {
      try {
        const dropEvent = new DragEvent("drop", {
          bubbles: true,
          cancelable: true,
          dataTransfer: dt
        });
        dropzone.dispatchEvent(dropEvent);
      } catch (e) {
        console.warn("[OccAIsion] Drop event trigger warning:", e);
      }
    }
    console.log(`[OccAIsion] Injected ${imagePayloads.length} files successfully.`);
  } catch (err) {
    console.error("[OccAIsion] Error injecting files:", err);
  }
}

// Platform detection
function isRicardo(hostname) {
  const h = (hostname || (typeof location !== "undefined" ? location.hostname : "")).toLowerCase();
  return h === "ricardo.ch" || h.endsWith(".ricardo.ch");
}

function isTutti(hostname) {
  const h = (hostname || (typeof location !== "undefined" ? location.hostname : "")).toLowerCase();
  return h === "tutti.ch" || h.endsWith(".tutti.ch");
}

function isEbayDE(hostname) {
  const h = (hostname || (typeof location !== "undefined" ? location.hostname : "")).toLowerCase();
  return h === "ebay.de" || h.endsWith(".ebay.de");
}

function isKleinanzeigen(hostname) {
  const h = (hostname || (typeof location !== "undefined" ? location.hostname : "")).toLowerCase();
  return h === "kleinanzeigen.de" || h.endsWith(".kleinanzeigen.de");
}

function isLocalDashboard(hostname) {
  const h = (hostname || (typeof location !== "undefined" ? location.hostname : "")).toLowerCase();
  return h === "127.0.0.1" || h === "localhost";
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
      category: draft.tutti ? draft.tutti.category_suggestion : "",
      description: draft.tutti ? draft.tutti.description : "",
      condition: draft.tutti ? draft.tutti.condition : "gebraucht",
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
          if (typeof editable.replaceChildren === "function") {
            editable.replaceChildren();
          } else {
            while (editable.firstChild) editable.removeChild(editable.firstChild);
          }
          const lines = String(value || "").split("\n");
          lines.forEach((line, idx) => {
            editable.appendChild(iframeDoc.createTextNode(line));
            if (idx < lines.length - 1) {
              editable.appendChild(iframeDoc.createElement("br"));
            }
          });
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

  const platform = detectPlatform();
  const step1BtnText = platform === "tutti" ? "▶ Schritt 1: Kategorie & Bilder" : "▶ Schritt 1: Bilder & Titel einfügen";
  const step2BtnText = platform === "tutti" ? "▶ Schritt 2: Alle Textfelder einfügen" : "▶ Schritt 2: Beschreibung, Zustand & Preis";

  panelElement = document.createElement("div");
  panelElement.id = "ai-listing-smart-panel";
  panelElement.className = "ai-smart-panel";

  panelElement.innerHTML = `
    <div class="ai-panel-header">
      <span class="ai-panel-title">🤖 OccAIsion</span>
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
          ${step1BtnText}
        </button>
        <button id="ai-ext-step2-btn" class="ai-btn ai-btn-secondary">
          ${step2BtnText}
        </button>
      </div>

      <div class="ai-copy-fallbacks">
        <span class="ai-fallback-title">📋 1-Klick-Kopieren (Fallback):</span>
        <div class="ai-fallback-row">
          <span>Kategorie:</span>
          <button id="ai-copy-cat-btn" class="ai-btn-copy">Kopieren</button>
        </div>
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

  // Step 1: Category & Images
  const step1Btn = document.getElementById("ai-ext-step1-btn");
  step1Btn.onclick = async () => {
    if (!activeDraft) {
      alert("Bitte wähle zuerst einen Entwurf aus.");
      return;
    }
    const platform = detectPlatform();
    step1Btn.disabled = true;
    step1Btn.textContent = platform === "tutti" ? "⏳ Wähle Kategorie & lade Bilder..." : "⏳ Lade Bilder & fülle Titel...";
    try {
      await executeStep1(activeDraft);
      if (platform === "tutti") {
        const listingTypeInput = document.querySelector('input[name="listingType"]');
        if (listingTypeInput && listingTypeInput.value && listingTypeInput.value.trim() !== "") {
          step1Btn.textContent = "✓ Kategorie & Bilder eingefügt";
        } else {
          step1Btn.textContent = "⚠ Bitte Kategorie manuell wählen";
        }
      } else {
        step1Btn.textContent = "✓ Bilder & Titel eingefügt";
      }
    } finally {
      step1Btn.disabled = false;
      setTimeout(() => {
        step1Btn.textContent = platform === "tutti" ? "▶ Schritt 1: Kategorie & Bilder" : "▶ Schritt 1: Bilder & Titel einfügen";
      }, 4000);
    }
  };

  // Step 2: Description & Price & all other fields
  const step2Btn = document.getElementById("ai-ext-step2-btn");
  step2Btn.onclick = async () => {
    if (!activeDraft) {
      alert("Bitte wähle zuerst einen Entwurf aus.");
      return;
    }
    const platform = detectPlatform();
    step2Btn.disabled = true;
    step2Btn.textContent = "⏳ Fülle Textfelder aus...";
    try {
      await executeStep2(activeDraft);
      step2Btn.textContent = "✓ Textfelder eingefügt";
    } finally {
      step2Btn.disabled = false;
      setTimeout(() => {
        step2Btn.textContent = platform === "tutti" ? "▶ Schritt 2: Alle Textfelder einfügen" : "▶ Schritt 2: Beschreibung, Zustand & Preis";
      }, 4000);
    }
  };

  // 1-Click Copy fallbacks (navigator.clipboard)
  const copyCatBtn = document.getElementById("ai-copy-cat-btn");
  if (copyCatBtn) {
    copyCatBtn.onclick = () => {
      if (!activeDraft) return;
      const data = getPlatformData(activeDraft);
      navigator.clipboard.writeText(data.category || "");
    };
  }

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
  const platform = detectPlatform();
  const data = getPlatformData(draft);

  // 1. Fetch images through background worker (bypassing CORS)
  try {
    const imagesResponse = await new Promise(resolve => {
      browserApi.runtime.sendMessage({ action: "FETCH_DRAFT_IMAGES", draftId: draft.id }, resolve);
    });

    if (imagesResponse && imagesResponse.ok && imagesResponse.images && imagesResponse.images.length > 0) {
      const fileInput = document.querySelector('input[type="file"]');
      if (fileInput) {
        injectFilesIntoInput(fileInput, imagesResponse.images);
      }
    }
  } catch (err) {
    console.warn("[OccAIsion] Error fetching/injecting images in Step 1:", err);
  }

  // 2. Platform specific assistance in Step 1: Category on Tutti
  if (platform === "tutti") {
    try {
      await autoSelectTuttiCategory(data.category, draft.identified_product || data.title);
    } catch (err) {
      console.warn("[OccAIsion] Tutti category selection error:", err);
    }
  }

  // 3. Inject Title (if present in DOM)
  const titleInput = document.querySelector(
    'input[name="subject"], #postad-title, #pstad-title, input[name="title"], input[name="pstad-title"], input[name*="title" i], input[id*="title" i], input[aria-label*="Titel" i], input[placeholder*="titel" i], input[data-testid*="title" i]'
  );
  if (titleInput && data.title) {
    setNativeValue(titleInput, data.title);
  }

  // 4. On Ricardo, if price/shipping fields are already present in DOM during Step 1, fill them as well
  if (platform === "ricardo") {
    try {
      await fillRicardoPrices(draft, data);
      await fillRicardoShipping(draft);
    } catch (e) {
      console.warn("[OccAIsion] Step 1 Ricardo price/shipping fill warning:", e);
    }
  }
}

async function executeStep2(draft) {
  const data = getPlatformData(draft);
  const platform = detectPlatform();

  // 1. Photos: If file input is present and has no files, inject images automatically
  const fileInput = document.querySelector('input[type="file"]');
  if (fileInput && (!fileInput.files || fileInput.files.length === 0)) {
    try {
      const imagesResponse = await new Promise(resolve => {
        browserApi.runtime.sendMessage({ action: "FETCH_DRAFT_IMAGES", draftId: draft.id }, resolve);
      });
      if (imagesResponse && imagesResponse.ok && imagesResponse.images && imagesResponse.images.length > 0) {
        injectFilesIntoInput(fileInput, imagesResponse.images);
      }
    } catch (e) {
      console.warn("[OccAIsion] Step 2 image injection warning:", e);
    }
  }

  // 2. Title: Fill if title input exists and is empty (crucial for Tutti where title is revealed after category selection)
  const titleInput = document.querySelector(
    'input[name="subject"], #postad-title, #pstad-title, input[name="title"], input[name="pstad-title"], input[name*="title" i], input[id*="title" i], input[aria-label*="Titel" i], input[placeholder*="titel" i], input[data-testid*="title" i]'
  );
  if (titleInput && data.title && (!titleInput.value || titleInput.value.trim() === "")) {
    setNativeValue(titleInput, data.title);
  }

  // 3. Description
  if (data.description) {
    setDescriptionValue(data.description);
  }

  // 4. Condition (Zustand)
  if (platform === "tutti") {
    const condInput = document.querySelector('input[name="field:itemCondition"], input[name*="itemCondition" i]');
    let condCombobox = condInput ? (condInput.parentElement?.querySelector('[role="combobox"]') || condInput.previousElementSibling) : null;
    if (!condCombobox) {
      const condLabel = Array.from(document.querySelectorAll("label")).find(l => /zustand/i.test(l.textContent || ""));
      if (condLabel && condLabel.htmlFor) condCombobox = document.getElementById(condLabel.htmlFor);
      if (!condCombobox && condLabel) condCombobox = condLabel.closest(".MuiFormControl-root")?.querySelector('[role="combobox"]');
    }
    if (condCombobox) {
      const condVal = (data.condition || "gebraucht").toLowerCase();
      await fillMuiSelect(condCombobox, opt => {
        const txt = (opt.textContent || "").toLowerCase().trim();
        if (condVal.includes("neu") && !condVal.includes("neuwertig")) {
          return txt === "neu" || /neu\b/i.test(txt);
        } else if (condVal.includes("neuwertig")) {
          return /neuwertig|wie neu/i.test(txt);
        } else if (condVal.includes("defekt")) {
          return /defekt/i.test(txt);
        } else {
          return /gebraucht/i.test(txt);
        }
      });
      await new Promise(r => setTimeout(r, 120));
    }
  } else {
    const condEl = document.querySelector(
      'select[name*="condition" i], select[id*="condition" i], select[data-testid*="condition" i], input[name*="condition" i]'
    );
    if (condEl && data.condition) {
      setNativeValue(condEl, data.condition);
    }
  }

  // 5. Shipping (Versand)
  if (platform === "tutti") {
    const shipInput = document.querySelector('input[name="field:shippingAvailable"], input[name*="shipping" i]');
    let shipCombobox = shipInput ? (shipInput.parentElement?.querySelector('[role="combobox"]') || shipInput.previousElementSibling) : null;
    if (!shipCombobox) {
      const shipLabel = Array.from(document.querySelectorAll("label")).find(l => /versand/i.test(l.textContent || ""));
      if (shipLabel && shipLabel.htmlFor) shipCombobox = document.getElementById(shipLabel.htmlFor);
      if (!shipCombobox && shipLabel) shipCombobox = shipLabel.closest(".MuiFormControl-root")?.querySelector('[role="combobox"]');
    }
    if (shipCombobox) {
      const isPickupOnly = draft.ricardo?.shipping_preset_id === "pickup_only";
      await fillMuiSelect(shipCombobox, opt => {
        const txt = (opt.textContent || "").toLowerCase().trim();
        if (isPickupOnly) {
          return /^(nein|nur\s*abholung|abholung)$/i.test(txt) || /nein/i.test(txt);
        } else {
          return /^(ja|versand\s*möglich|versand)$/i.test(txt) || /ja/i.test(txt);
        }
      });
      await new Promise(r => setTimeout(r, 120));
    }
  } else if (platform === "ricardo") {
    try {
      await fillRicardoShipping(draft);
    } catch (e) {
      console.warn("[OccAIsion] Ricardo shipping config warning:", e);
    }
  }

  // 6. Prices
  if (platform === "ricardo") {
    await fillRicardoPrices(draft, data);
  } else if (platform === "ebay_de") {
    const startPriceInput = document.querySelector(
      'input[name*="startPrice" i], input[id*="start-price" i], input[id*="start_price" i], input[aria-label*="Startpreis" i], input[data-testid*="start-price" i]'
    );
    if (startPriceInput && data.startPrice !== null && data.startPrice !== undefined) {
      setNativeValue(startPriceInput, data.startPrice);
    }
    const buynowPriceInput = document.querySelector(
      'input[name*="buyNowPrice" i], input[name*="buyItNowPrice" i], input[id*="buy-now-price" i], input[id*="buy_now" i], input[aria-label*="Sofort-Kaufen" i], input[data-testid*="buy-now-price" i], input[name="price"]'
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

  // 7. Postal Code (PLZ) on Tutti if currently empty
  if (platform === "tutti") {
    const postalCodeInput = document.querySelector('input[name="postalCode"], input[id*="postalCode" i]');
    if (postalCodeInput && (!postalCodeInput.value || postalCodeInput.value.trim() === "")) {
      const m = (draft.user_notes || "").match(/\b([1-9]\d{3})\b/);
      if (m) {
        setNativeValue(postalCodeInput, m[1]);
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
    console.warn("[OccAIsion] postMessage warning:", e);
  }
}

function setupDashboardBridge() {
  if (typeof document !== "undefined" && document.documentElement) {
    document.documentElement.dataset.occaisionExtension = "installed";
  }
  if (typeof window === "undefined") return;

  console.log("[OccAIsion] Dashboard Content-Script Bridge aktiv auf", location.href);

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

    if (msg.type === "OCCAISION_PING") {
      sendToPage({ type: "OCCAISION_PONG" });
      return;
    }

    if (msg.type === "OCCAISION_SET_TOKEN" && msg.token) {
      if (browserApi && browserApi.runtime && browserApi.runtime.sendMessage) {
        browserApi.runtime.sendMessage({ action: "SET_AUTH_TOKEN", token: msg.token });
      }
      return;
    }

    if (msg.type === "OCCAISION_SCRAPE_PRICES") {
      const reqId = msg.requestId;
      const query = msg.query || "";
      const eurToChfRate = msg.eurToChfRate || 0.94;
      const enabledSources = Array.isArray(msg.enabledSources) ? msg.enabledSources : null;
      const keepTabsOpen = Boolean(msg.keepTabsOpen);

      console.log(`[OccAIsion] Content-Script empfängt Scrape-Anfrage (${reqId}) für '${query}' (enabled: ${enabledSources ? enabledSources.join(',') : 'all'}, keepTabsOpen: ${keepTabsOpen})`);

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
            console.group(`[OccAIsion] [Content-Bridge] eBay DE verkaufte Artikel (${items.length} Treffer):`);
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
            console.group(`[OccAIsion] [Content-Bridge] Kleinanzeigen Artikel (${kaItems.length} Treffer):`);
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
            console.group(`[OccAIsion] [Content-Bridge] Idealo Neupreise (${idealoItems.length} Treffer):`);
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
            console.group(`[OccAIsion] [Content-Bridge] Toppreise Neupreise (${toppreiseItems.length} Treffer):`);
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
            console.group(`[OccAIsion] [Content-Bridge] Galaxus/Digitec Neupreise (${digitecItems.length} Treffer):`);
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
              type: "OCCAISION_SCRAPE_PRICES_RESULT",
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
if (typeof browserApi !== "undefined" && browserApi && browserApi.runtime && browserApi.runtime.onMessage) {
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

      sendResponse({ html, currentUrl, priceNodes, idealoCards, toppreiseCards, digitecCards, ricardoCards, tuttiCards });
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
    fillRicardoPrices,
    fillRicardoShipping,
  };
}
