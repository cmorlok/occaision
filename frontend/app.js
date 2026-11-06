if (typeof document === "undefined") {
  // Support headless Node.js environments / automated tests
  global.document = {
    getElementById: () => null,
    createElement: () => ({ setAttribute: () => {}, appendChild: () => {}, style: {}, classList: { add: () => {}, remove: () => {} } }),
    addEventListener: () => {},
  };
}

const api = (typeof window !== "undefined" && window.api) ? window.api : (typeof require !== "undefined" ? require("./api.js") : {});

let currentDraft = null;
let drafts = [];
let settings = null;

// DOM Elements
const draftListEl = document.getElementById("draft-list");
const btnNewDraft = document.getElementById("btn-new-draft");
const activeDraftTitleEl = document.getElementById("active-draft-title");
const draftStatusSelect = document.getElementById("draft-status-select");
const btnSaveDraft = document.getElementById("btn-save-draft");
const dropzoneEl = document.getElementById("dropzone");
const fileInputEl = document.getElementById("file-input");
const imageGalleryEl = document.getElementById("image-gallery");
const productNameEl = document.getElementById("product-name");
const userNotesEl = document.getElementById("user-notes");
const shippingPresetEl = document.getElementById("shipping-preset");
const deShippingPresetEl = document.getElementById("de-shipping-preset");
const offerTypeEl = document.getElementById("offer-type");
const btnScrapeExtension = document.getElementById("btn-scrape-extension");
const btnAnalyze = document.getElementById("btn-analyze");
const analyzeSpinner = document.getElementById("analyze-spinner");
const extensionScrapeStatus = document.getElementById("extension-scrape-status");

// Section 2: Analysis elements
const missingHintsBox = document.getElementById("missing-hints-box");
const missingHintsList = document.getElementById("missing-hints-list");
const priceEbayMedian = document.getElementById("price-ebay-median");
const priceEbayCount = document.getElementById("price-ebay-count");
const priceKleinanzeigenMedian = document.getElementById("price-kleinanzeigen-median");
const priceKleinanzeigenCount = document.getElementById("price-kleinanzeigen-count");
const priceIdealoMedian = document.getElementById("price-idealo-median");
const priceIdealoCount = document.getElementById("price-idealo-count");
const priceRicardoMedian = document.getElementById("price-ricardo-median");
const priceRicardoCount = document.getElementById("price-ricardo-count");
const priceToppreiseMedian = document.getElementById("price-toppreise-median");
const priceToppreiseCount = document.getElementById("price-toppreise-count");
const priceDigitecMedian = document.getElementById("price-digitec-median");
const priceDigitecCount = document.getElementById("price-digitec-count");
const priceTuttiMedian = document.getElementById("price-tutti-median");
const priceTuttiCount = document.getElementById("price-tutti-count");
const priceChNew = document.getElementById("price-ch-new");
const priceDeNew = document.getElementById("price-de-new");
const priceRecStart = document.getElementById("price-rec-start");
const priceRecBuyNow = document.getElementById("price-rec-buynow");
const priceRecTutti = document.getElementById("price-rec-tutti");
const priceRecEbayStart = document.getElementById("price-rec-ebay-start");
const priceRecEbayBuyNow = document.getElementById("price-rec-ebay-buynow");
const priceRecKleinanzeigen = document.getElementById("price-rec-kleinanzeigen");
const priceReasoningText = document.getElementById("price-reasoning-text");
const linkEbay = document.getElementById("link-ebay");
const linkKleinanzeigen = document.getElementById("link-kleinanzeigen");
const linkIdealo = document.getElementById("link-idealo");
const linkRicardo = document.getElementById("link-ricardo");
const linkToppreise = document.getElementById("link-toppreise");
const linkDigitec = document.getElementById("link-digitec");
const linkTutti = document.getElementById("link-tutti");

// Section 3: Platform elements
const ricardoTitle = document.getElementById("ricardo-title");
const ricardoTitleCount = document.getElementById("ricardo-title-count");
const ricardoCondition = document.getElementById("ricardo-condition");
const ricardoStartPrice = document.getElementById("ricardo-start-price");
const ricardoBuyNowPrice = document.getElementById("ricardo-buynow-price");
const ricardoDescription = document.getElementById("ricardo-description");

const tuttiTitle = document.getElementById("tutti-title");
const tuttiTitleCount = document.getElementById("tutti-title-count");
const tuttiCategory = document.getElementById("tutti-category");
const tuttiCondition = document.getElementById("tutti-condition");
const tuttiPrice = document.getElementById("tutti-price");
const tuttiDescription = document.getElementById("tutti-description");
const tuttiDescriptionCount = document.getElementById("tutti-description-count");

const ebayDeTitle = document.getElementById("ebay-de-title");
const ebayDeTitleCount = document.getElementById("ebay-de-title-count");
const ebayDeCategory = document.getElementById("ebay-de-category");
const ebayDeCondition = document.getElementById("ebay-de-condition");
const ebayDeOfferType = document.getElementById("ebay-de-offer-type");
const ebayDeStartPrice = document.getElementById("ebay-de-start-price");
const ebayDeBuyNowPrice = document.getElementById("ebay-de-buynow-price");
const ebayDeDescription = document.getElementById("ebay-de-description");

const kleinanzeigenTitle = document.getElementById("kleinanzeigen-title");
const kleinanzeigenTitleCount = document.getElementById("kleinanzeigen-title-count");
const kleinanzeigenCategory = document.getElementById("kleinanzeigen-category");
const kleinanzeigenCondition = document.getElementById("kleinanzeigen-condition");
const kleinanzeigenPrice = document.getElementById("kleinanzeigen-price");
const kleinanzeigenPriceType = document.getElementById("kleinanzeigen-price-type");
const kleinanzeigenDescription = document.getElementById("kleinanzeigen-description");

// Settings Modal DOM Elements
const btnSettings = document.getElementById("btn-settings");
const settingsModal = document.getElementById("settings-modal");
const btnCloseSettings = document.getElementById("btn-close-settings");
const btnCancelSettings = document.getElementById("btn-cancel-settings");
const btnSaveSettings = document.getElementById("btn-save-settings");
const modalBackdrop = document.getElementById("modal-backdrop");
const cfgGeminiKey = document.getElementById("cfg-gemini-key");
const btnToggleKey = document.getElementById("btn-toggle-key");
const cfgGeminiModel = document.getElementById("cfg-gemini-model");
const cfgSearchGrounding = document.getElementById("cfg-search-grounding");
const cfgEurRate = document.getElementById("cfg-eur-rate");
const cfgKeyStatus = document.getElementById("cfg-key-status");
const btnCreatePairingPin = document.getElementById("btn-create-pairing-pin");
const pairingPinDisplay = document.getElementById("pairing-pin-display");
const pairingPinHint = document.getElementById("pairing-pin-hint");
const btnExportBackup = document.getElementById("btn-export-backup");
const backupFileInput = document.getElementById("backup-file-input");
const toastContainer = document.getElementById("toast-container");

const showToast = (typeof window !== "undefined" && typeof window.showToast === "function")
  ? (...args) => window.showToast(...args)
  : (message, type = "info", options = {}) => {
      if (typeof require !== "undefined") {
        try {
          return require("./toast.js").showToast(message, type, options);
        } catch (_) {}
      }
      console.log(`[${type}] ${message}`);
      return null;
    };

let systemConfig = null;

async function init() {
  try {
    let pairData = await api.pairAuth().catch(() => null);
    if (!pairData || !pairData.token) {
      const codeResp = await api.createPairingCode().catch(() => null);
      if (codeResp && codeResp.pairing_code) {
        pairData = await api.pairAuth(codeResp.pairing_code).catch(() => null);
      }
    }
    if (pairData && pairData.token && typeof window !== "undefined") {
      window.postMessage(JSON.stringify({ type: "OCCAISION_SET_TOKEN", token: pairData.token }), window.location.origin);
    }
  } catch (_) {}
  await loadSettings();
  await loadSystemConfig();
  await loadDrafts();
  setupEventListeners();
}

async function loadSystemConfig() {
  try {
    systemConfig = await api.getConfig();
    
    // Dynamically populate available models from server
    if (cfgGeminiModel && systemConfig.available_models && systemConfig.available_models.length > 0) {
        cfgGeminiModel.innerHTML = "";
        systemConfig.available_models.forEach(m => {
          const opt = document.createElement("option");
          opt.value = m.id;
          opt.textContent = m.label;
          cfgGeminiModel.appendChild(opt);
        });
      }
      
      if (cfgGeminiModel) {
        cfgGeminiModel.value = systemConfig.gemini_model || "gemini-3.8-flash";
      }
      if (cfgSearchGrounding) {
        cfgSearchGrounding.checked = systemConfig.enable_search_grounding !== false;
      }
      if (cfgEurRate && systemConfig.eur_to_chf_rate !== undefined) {
        cfgEurRate.value = systemConfig.eur_to_chf_rate;
      }
      updateKeyStatusUI();
  } catch (err) {
    console.error("Failed to load system config", err);
  }
}

function updateKeyStatusUI() {
  if (!cfgKeyStatus || !systemConfig) return;
  if (systemConfig.gemini_api_key_configured) {
    cfgKeyStatus.textContent = `✓ API-Key aktiv (${systemConfig.masked_key})`;
    cfgKeyStatus.className = "key-status-indicator ok";
  } else {
    cfgKeyStatus.textContent = "⚠️ Kein gültiger API-Key hinterlegt (KI-Analyse benötigt einen Key)";
    cfgKeyStatus.className = "key-status-indicator warn";
  }
}

const ALL_PRICE_SOURCES = [
  { id: "ebay_de_sold", boxId: "source-box-ebay_de_sold", linkId: "link-ebay" },
  { id: "kleinanzeigen", boxId: "source-box-kleinanzeigen", linkId: "link-kleinanzeigen" },
  { id: "idealo", boxId: "source-box-idealo", linkId: "link-idealo" },
  { id: "ricardo", boxId: "source-box-ricardo", linkId: "link-ricardo" },
  { id: "toppreise", boxId: "source-box-toppreise", linkId: "link-toppreise" },
  { id: "digitec", boxId: "source-box-digitec", linkId: "link-digitec" },
  { id: "tutti", boxId: "source-box-tutti", linkId: "link-tutti" },
];

function getEnabledPriceSources() {
  if (settings && Array.isArray(settings.enabled_price_sources)) {
    return settings.enabled_price_sources;
  }
  return ["ebay_de_sold", "kleinanzeigen", "idealo", "ricardo", "toppreise", "digitec", "tutti"];
}

function updatePriceSourcesVisibility() {
  const enabled = getEnabledPriceSources();
  ALL_PRICE_SOURCES.forEach(src => {
    const isEnabled = enabled.includes(src.id);
    const box = document.getElementById(src.boxId);
    if (box) {
      if (isEnabled) box.classList.remove("hidden");
      else box.classList.add("hidden");
    }
    const link = document.getElementById(src.linkId);
    if (link) {
      if (isEnabled) link.classList.remove("hidden");
      else link.classList.add("hidden");
    }
  });
}

function openSettingsModal() {
  if (!settingsModal) return;
  loadSystemConfig();
  if (cfgGeminiKey) cfgGeminiKey.value = "";
  const enabled = getEnabledPriceSources();
  ALL_PRICE_SOURCES.forEach(src => {
    const cb = document.getElementById(`cfg-src-${src.id}`);
    if (cb) {
      cb.checked = enabled.includes(src.id);
    }
  });
  const cfgKeepTabsOpen = document.getElementById("cfg-keep-tabs-open");
  if (cfgKeepTabsOpen) {
    cfgKeepTabsOpen.checked = Boolean(settings && settings.keep_tabs_open_after_search);
  }
  settingsModal.classList.remove("hidden");
}

function closeSettingsModal() {
  if (!settingsModal) return;
  settingsModal.classList.add("hidden");
}

async function saveSystemConfig() {
  const newKey = cfgGeminiKey.value.trim();
  const newModel = cfgGeminiModel.value;

  const payload = {
    gemini_model: newModel,
    enable_search_grounding: cfgSearchGrounding ? cfgSearchGrounding.checked : true,
  };
  if (cfgEurRate) {
    const rateVal = parseFloat(cfgEurRate.value);
    if (!isNaN(rateVal) && rateVal > 0) {
      payload.eur_to_chf_rate = rateVal;
    }
  }
  if (newKey) {
    payload.gemini_api_key = newKey;
  }

  // Collect enabled sources from checkboxes
  const enabledSources = [];
  ALL_PRICE_SOURCES.forEach(src => {
    const cb = document.getElementById(`cfg-src-${src.id}`);
    if (cb && cb.checked) {
      enabledSources.push(src.id);
    }
  });

  const cfgKeepTabsOpen = document.getElementById("cfg-keep-tabs-open");
  const keepTabsOpen = cfgKeepTabsOpen ? cfgKeepTabsOpen.checked : false;

  try {
    btnSaveSettings.disabled = true;
    systemConfig = await api.updateConfig(payload);
    updateKeyStatusUI();

    // Also persist settings (enabled_price_sources, keep_tabs_open_after_search) in /api/settings
    if (settings) {
      const updatedSettings = Object.assign({}, settings, {
        enabled_price_sources: enabledSources,
        keep_tabs_open_after_search: keepTabsOpen,
      });
      settings = await api.updateSettings(updatedSettings);
    }
    updatePriceSourcesVisibility();

    closeSettingsModal();
    showToast("Einstellungen erfolgreich gespeichert!", "success");
  } catch (err) {
    showToast(`Fehler beim Speichern: ${err.message}`, "error");
  } finally {
    btnSaveSettings.disabled = false;
  }
}

async function loadSettings() {
  try {
    settings = await api.getSettings();
    updatePriceSourcesVisibility();
    shippingPresetEl.innerHTML = "";
    if (deShippingPresetEl) deShippingPresetEl.innerHTML = "";
    settings.shipping_presets.forEach(p => {
      const opt = document.createElement("option");
      opt.value = p.id;
      opt.textContent = p.label;
      if (p.country === "DE") {
        if (deShippingPresetEl) deShippingPresetEl.appendChild(opt);
      } else {
        shippingPresetEl.appendChild(opt);
      }
    });
  } catch (err) {
    console.error("Failed to load settings", err);
  }
}

async function ensureDraft() {
  if (currentDraft) return currentDraft;
  try {
    currentDraft = await api.createDraft({ user_notes: "" });
    drafts = [currentDraft, ...drafts.filter(d => d.id !== currentDraft.id)];
    renderDraftList();
    populateForm();
    return currentDraft;
  } catch (err) {
    console.error("Failed to auto-create draft", err);
  }
  return null;
}

async function loadDrafts() {
  try {
    drafts = await api.listDrafts();
    renderDraftList();
    if (drafts.length > 0) {
      if (!currentDraft || !drafts.some(d => d.id === currentDraft.id)) {
        await selectDraft(drafts[0].id);
      }
    } else if (!currentDraft) {
      await ensureDraft();
    }
  } catch (err) {
    console.error("Failed to load drafts", err);
    if (err.data && err.data.error_code === "STORAGE_CORRUPTED") {
      showToast(
        "Datenbank-Datei beschädigt. Ein automatisches Backup wurde angelegt. Nutze die Wiederherstellung in den Einstellungen.",
        "error",
        {
          duration: 15000,
          actionText: "Einstellungen",
          onAction: openSettingsModal,
        }
      );
    }
  }
}

function renderDraftList() {
  draftListEl.replaceChildren();
  drafts.forEach(d => {
    const item = document.createElement("div");
    item.className = `draft-item ${currentDraft && currentDraft.id === d.id ? "active" : ""}`;
    item.addEventListener("click", () => selectDraft(d.id));

    const title = d.identified_product || d.user_notes || d.ricardo.title || "Neuer Entwurf";
    const statusClass = `status-${d.status}`;
    const dateStr = new Date(d.updated_at).toLocaleDateString("de-CH", { hour: "2-digit", minute: "2-digit" });

    const header = document.createElement("div");
    header.className = "draft-item-header";

    const titleSpan = document.createElement("span");
    titleSpan.className = "draft-item-title";
    titleSpan.title = title;
    titleSpan.textContent = title;

    const statusBadge = document.createElement("span");
    statusBadge.className = `status-badge ${statusClass}`;
    statusBadge.textContent = d.status;

    header.appendChild(titleSpan);
    header.appendChild(statusBadge);

    const footer = document.createElement("div");
    footer.className = "draft-item-footer";

    const dateSpan = document.createElement("span");
    dateSpan.textContent = dateStr;

    const deleteBtn = document.createElement("button");
    deleteBtn.className = "btn-delete-draft";
    deleteBtn.title = "Löschen";
    deleteBtn.textContent = "🗑️";
    deleteBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      deleteDraft(d.id);
    });

    footer.appendChild(dateSpan);
    footer.appendChild(deleteBtn);

    item.appendChild(header);
    item.appendChild(footer);
    draftListEl.appendChild(item);
  });
}

async function selectDraft(draftId) {
  try {
    currentDraft = await api.getDraft(draftId);
    populateForm();
    renderDraftList();
  } catch (err) {
    console.error("Failed to fetch draft", err);
  }
}

function populateForm() {
  if (!currentDraft) return;

  activeDraftTitleEl.textContent = currentDraft.identified_product || currentDraft.user_notes || "Entwurf bearbeiten";
  draftStatusSelect.value = currentDraft.status;
  if (productNameEl) {
    productNameEl.value = currentDraft.identified_product || "";
  }
  userNotesEl.value = currentDraft.user_notes || "";
  offerTypeEl.value = currentDraft.ricardo.offer_type || "auction";
  shippingPresetEl.value = currentDraft.ricardo.shipping_preset_id || (settings ? settings.default_shipping_preset_id : "b_post_2kg");
  if (deShippingPresetEl) {
    deShippingPresetEl.value = (currentDraft.ebay_de && currentDraft.ebay_de.shipping_preset_id) || (settings ? settings.default_de_shipping_preset_id : "dhl_2kg");
  }

  // Photos
  renderGallery();

  // Analysis / hints
  if (currentDraft.missing_photo_hints && currentDraft.missing_photo_hints.length > 0) {
    missingHintsList.replaceChildren();
    currentDraft.missing_photo_hints.forEach(h => {
      const li = document.createElement("li");
      li.textContent = h;
      missingHintsList.appendChild(li);
    });
    missingHintsBox.classList.remove("hidden");
  } else {
    missingHintsList.replaceChildren();
    missingHintsBox.classList.add("hidden");
  }

  // Prices
  const pa = currentDraft.price_analysis || {};
  const ms = pa.market_sources || {};

  function renderSourceBox(srcKey, medianEl, countEl, fallbackStats) {
    if (!medianEl || !countEl) return;
    const src = ms[srcKey];
    medianEl.style.color = "";
    if (src && src.login_required) {
      medianEl.textContent = "🔒 Login nötig";
      medianEl.style.color = "var(--danger, #dc2626)";
      countEl.innerHTML = `<a href="https://signin.ebay.de" target="_blank" rel="noopener" style="color: var(--danger, #dc2626); text-decoration: underline;">Bitte in Firefox auf ebay.de einloggen ↗</a>`;
      return;
    }
    if (src && src.sample_count > 0 && src.median_price !== null && src.median_price !== undefined) {
      const unit = src.currency === "CHF" ? "CHF" : "€";
      const chfHint = src.currency !== "CHF" && src.median_chf ? ` (~${src.median_chf} CHF)` : "";
      medianEl.textContent = `${src.median_price} ${unit}${chfHint}`;
      if ((srcKey === "idealo" || srcKey === "toppreise" || srcKey === "digitec") && src.items && src.items[0] && src.items[0].title) {
        const prodTitle = src.items[0].title;
        countEl.textContent = prodTitle.length > 35 ? prodTitle.slice(0, 32) + "..." : prodTitle;
        countEl.title = prodTitle;
        countEl.style.cursor = "help";
      } else {
        const spanHint = src.min_price !== null && src.max_price !== null && src.min_price !== src.max_price
          ? ` (${src.min_price}–${src.max_price} ${unit})`
          : "";
        countEl.textContent = `${src.sample_count} Treffer${spanHint}`;
        countEl.title = "";
        countEl.style.cursor = "";
      }
    } else if (fallbackStats && fallbackStats.median_eur) {
      medianEl.textContent = `${fallbackStats.median_eur} € (~${fallbackStats.median_chf} CHF)`;
      countEl.textContent = `${fallbackStats.sample_count} verkaufte Artikel`;
    } else if (src && src.error) {
      medianEl.textContent = "⚠️ Fehler";
      countEl.textContent = src.error;
    } else {
      medianEl.textContent = "-";
      countEl.textContent = "Keine Daten";
    }
  }

  renderSourceBox("ebay_de_sold", priceEbayMedian, priceEbayCount, pa.ebay_stats);
  renderSourceBox("kleinanzeigen", priceKleinanzeigenMedian, priceKleinanzeigenCount, null);
  renderSourceBox("idealo", priceIdealoMedian, priceIdealoCount, null);
  renderSourceBox("ricardo", priceRicardoMedian, priceRicardoCount, null);
  renderSourceBox("toppreise", priceToppreiseMedian, priceToppreiseCount, null);
  renderSourceBox("digitec", priceDigitecMedian, priceDigitecCount, null);
  renderSourceBox("tutti", priceTuttiMedian, priceTuttiCount, null);
  updatePriceSourcesVisibility();

  if (extensionScrapeStatus) {
    if (pa.prices_fetched_via_extension) {
      const totalHits = Object.values(ms).reduce((acc, s) => acc + (s.sample_count || 0), 0);
      const ebayLoginNeeded = ms.ebay_de_sold && ms.ebay_de_sold.login_required;
      if (ebayLoginNeeded) {
        extensionScrapeStatus.innerHTML =
          `⚠️ <strong>eBay DE erfordert einen Login für verkaufte Artikel!</strong> Bitte in Firefox auf <a href="https://signin.ebay.de" target="_blank" rel="noopener">ebay.de einloggen</a> und die Preisrecherche erneut starten. (Übrige Quellen: ${totalHits} Treffer)`;
        extensionScrapeStatus.style.color = "var(--danger, #dc2626)";
      } else {
        extensionScrapeStatus.textContent = `✓ Extension-Preise aktiv (${totalHits} Treffer über ${Object.keys(ms).length} Quellen) – wird bei KI-Analyse direkt übergeben.`;
        extensionScrapeStatus.style.color = "";
      }
    } else {
      extensionScrapeStatus.textContent = "";
      extensionScrapeStatus.style.color = "";
    }
  }

  priceChNew.textContent = pa.ch_new_price_chf ? `${pa.ch_new_price_chf.toFixed(2)} CHF` : "-";
  if (priceDeNew) {
    priceDeNew.textContent = pa.de_new_price_eur ? `${pa.de_new_price_eur.toFixed(2)} €` : "-";
  }
  priceRecStart.textContent = `${pa.ricardo_start_chf || 1.0} CHF`;
  priceRecBuyNow.textContent = `${pa.ricardo_buynow_chf || 10.0} CHF`;
  priceRecTutti.textContent = `${pa.tutti_vhb_chf || 10.0} CHF`;
  if (priceRecEbayStart) {
    priceRecEbayStart.textContent = `${pa.ebay_start_eur || 1.0} €`;
  }
  if (priceRecEbayBuyNow) {
    priceRecEbayBuyNow.textContent = `${pa.ebay_buynow_eur || 10.0} €`;
  }
  if (priceRecKleinanzeigen) {
    priceRecKleinanzeigen.textContent = `${pa.kleinanzeigen_vb_eur || 10.0} €`;
  }
  priceReasoningText.textContent = pa.reasoning || "Noch keine Analyse.";

  // Verification links
  const vl = pa.verification_links;
  if (vl) {
    linkEbay.href = vl.ebay_sold_url || "#";
    if (linkKleinanzeigen) linkKleinanzeigen.href = vl.kleinanzeigen_search_url || "#";
    if (linkIdealo) linkIdealo.href = vl.idealo_url || "#";
    linkRicardo.href = vl.ricardo_search_url || "#";
    linkToppreise.href = vl.toppreise_url || "#";
    linkDigitec.href = vl.digitec_url || "#";
    if (linkTutti) linkTutti.href = vl.tutti_search_url || "#";
  }

  // Ricardo
  ricardoTitle.value = currentDraft.ricardo.title || "";
  updateCharCounter(ricardoTitle, ricardoTitleCount, 60);
  ricardoCondition.value = currentDraft.ricardo.condition || "gebraucht";
  ricardoStartPrice.value = currentDraft.ricardo.start_price_chf || 1.0;
  ricardoBuyNowPrice.value = currentDraft.ricardo.buynow_price_chf || 10.0;
  ricardoDescription.value = currentDraft.ricardo.description || "";

  // Tutti
  tuttiTitle.value = currentDraft.tutti.title || "";
  updateCharCounter(tuttiTitle, tuttiTitleCount, 60);
  tuttiCategory.value = currentDraft.tutti.category_suggestion || "";
  tuttiCondition.value = currentDraft.tutti.condition || "gebraucht";
  tuttiPrice.value = currentDraft.tutti.price_vhb_chf || 10.0;
  tuttiDescription.value = currentDraft.tutti.description || "";
  if (tuttiDescriptionCount) {
    updateCharCounter(tuttiDescription, tuttiDescriptionCount, 4000);
  }

  // eBay.de
  if (currentDraft.ebay_de && ebayDeTitle) {
    ebayDeTitle.value = currentDraft.ebay_de.title || "";
    updateCharCounter(ebayDeTitle, ebayDeTitleCount, 80);
    ebayDeCategory.value = currentDraft.ebay_de.category_suggestion || "";
    ebayDeCondition.value = currentDraft.ebay_de.condition || "gebraucht";
    ebayDeOfferType.value = currentDraft.ebay_de.offer_type || "auction";
    ebayDeStartPrice.value = currentDraft.ebay_de.start_price_eur || 1.0;
    ebayDeBuyNowPrice.value = currentDraft.ebay_de.buynow_price_eur || 10.0;
    ebayDeDescription.value = currentDraft.ebay_de.description || "";
  }

  // Kleinanzeigen
  if (currentDraft.kleinanzeigen && kleinanzeigenTitle) {
    kleinanzeigenTitle.value = currentDraft.kleinanzeigen.title || "";
    updateCharCounter(kleinanzeigenTitle, kleinanzeigenTitleCount, 65);
    kleinanzeigenCategory.value = currentDraft.kleinanzeigen.category_suggestion || "";
    kleinanzeigenCondition.value = currentDraft.kleinanzeigen.condition || "gebraucht";
    kleinanzeigenPrice.value = currentDraft.kleinanzeigen.price_eur || 10.0;
    kleinanzeigenPriceType.value = currentDraft.kleinanzeigen.price_type || "vb";
    kleinanzeigenDescription.value = currentDraft.kleinanzeigen.description || "";
  }
}

function renderGallery() {
  imageGalleryEl.replaceChildren();
  if (!currentDraft || !currentDraft.images) return;

  currentDraft.images.forEach(img => {
    const card = document.createElement("div");
    card.className = "image-card";
    card.id = `image-card-${img.id}`;
    const cacheBuster = `?t=${Date.now()}`;
    const previewUrl = `/api/drafts/${currentDraft.id}/images/${img.id}/active${cacheBuster}`;

    const previewImg = document.createElement("img");
    previewImg.src = previewUrl;
    previewImg.className = "image-preview";
    previewImg.alt = img.original_filename || "Draft Image";

    const controls = document.createElement("div");
    controls.className = "image-card-controls";

    const modeSelectors = document.createElement("div");
    modeSelectors.className = "mode-selectors";

    const modes = [
      { mode: "optimized", label: "Original" },
      { mode: "blurred", label: "Weichzeichnen" },
      { mode: "cutout", label: "Hintergrund entfernen" },
    ];

    modes.forEach(m => {
      const btn = document.createElement("button");
      btn.className = `btn-mode ${img.active_mode === m.mode ? "active" : ""}`;
      btn.textContent = m.label;
      btn.addEventListener("click", () => changeImageMode(img.id, m.mode));
      modeSelectors.appendChild(btn);
    });

    const delBtn = document.createElement("button");
    delBtn.className = "btn-del-img";
    delBtn.textContent = "Bild löschen 🗑️";
    delBtn.addEventListener("click", () => deleteImage(img.id));

    controls.appendChild(modeSelectors);
    controls.appendChild(delBtn);

    card.appendChild(previewImg);
    card.appendChild(controls);
    imageGalleryEl.appendChild(card);
  });
}

async function changeImageMode(imageId, mode) {
  if (!currentDraft) return;
  const currentImg = (currentDraft.images || []).find(i => i.id === imageId);
  if (currentImg && currentImg.active_mode === mode) return;

  const card = document.getElementById(`image-card-${imageId}`);
  let overlay = null;
  if (card) {
    overlay = document.createElement("div");
    overlay.className = "image-loading-overlay";
    let text = "Wird verarbeitet...";
    let subtext = "Bitte kurz warten...";
    if (mode === "cutout") {
      text = "Hintergrund entfernen...";
      subtext = "KI-Segmentierung läuft...";
    } else if (mode === "blurred") {
      text = "Hintergrund weichzeichnen...";
      subtext = "Berechne Tiefenschärfe...";
    } else if (mode === "optimized") {
      text = "Original laden...";
      subtext = "Bereite Ansicht vor...";
    }
    overlay.innerHTML = `
      <div class="spinner"></div>
      <div class="overlay-text">${text}</div>
      <div class="overlay-subtext">${subtext}</div>
    `;
    card.appendChild(overlay);
    card.querySelectorAll("button").forEach(b => b.disabled = true);
  }

  try {
    const res = await api.setVariant(currentDraft.id, imageId, mode);
    if (res.ok) {
      currentDraft = await res.json();
      renderGallery();
    } else {
      const err = await res.json().catch(() => ({}));
      showToast(`Fehler bei der Bildbearbeitung: ${err.detail || res.statusText || "Serverfehler"}`, "error");
      if (overlay) overlay.remove();
      if (card) card.querySelectorAll("button").forEach(b => b.disabled = false);
    }
  } catch (err) {
    console.error("Failed to change mode", err);
    showToast(`Fehler bei der Bildbearbeitung: ${err.message}`, "error");
    if (overlay) overlay.remove();
    if (card) card.querySelectorAll("button").forEach(b => b.disabled = false);
  }
}

async function deleteImage(imageId) {
  if (!currentDraft) return;
  if (!confirm("Foto wirklich löschen?")) return;
  const card = document.getElementById(`image-card-${imageId}`);
  if (card) {
    card.querySelectorAll("button").forEach(b => b.disabled = true);
    card.style.opacity = "0.5";
  }
  try {
    const res = await api.deleteImage(currentDraft.id, imageId);
    if (res.ok) {
      currentDraft = await res.json();
      renderGallery();
      showToast("Foto gelöscht.", "info");
    } else {
      showToast("Fehler beim Löschen des Fotos.", "error");
      if (card) {
        card.style.opacity = "1";
        card.querySelectorAll("button").forEach(b => b.disabled = false);
      }
    }
  } catch (err) {
    console.error("Failed to delete image", err);
    showToast(`Fehler beim Löschen des Fotos: ${err.message}`, "error");
    if (card) {
      card.style.opacity = "1";
      card.querySelectorAll("button").forEach(b => b.disabled = false);
    }
  }
}

function updateCharCounter(inputEl, counterEl, max) {
  const len = inputEl.value.length;
  counterEl.textContent = `${len}/${max}`;
  if (len > max) {
    counterEl.style.color = "var(--danger)";
  } else {
    counterEl.style.color = "var(--text-muted)";
  }
}

const MAX_UPLOAD_FILES = 15;
const MAX_FILE_BYTES = 25 * 1024 * 1024;
const ALLOWED_IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"];

function validateUploadFiles(files) {
  if (!files || !files.length) {
    return { valid: false, error: "Keine Dateien ausgewählt." };
  }
  if (files.length > MAX_UPLOAD_FILES) {
    return {
      valid: false,
      error: `Maximal ${MAX_UPLOAD_FILES} Bilder pro Upload erlaubt (ausgewählt: ${files.length}).`,
    };
  }
  for (const f of files) {
    const name = f.name || "";
    const ext = name.includes(".") ? name.slice(name.lastIndexOf(".")).toLowerCase() : "";
    const isAllowedExt = ALLOWED_IMAGE_EXTENSIONS.includes(ext);
    const isImageMime = f.type && (f.type.startsWith("image/") || f.type === "image/heic" || f.type === "image/heif");
    if (!isAllowedExt && !isImageMime) {
      return {
        valid: false,
        error: `Ungültiges Dateiformat für '${name || "Datei"}'. Erlaubt sind JPG, PNG, WEBP und HEIC/HEIF.`,
      };
    }
    if (f.size && f.size > MAX_FILE_BYTES) {
      return {
        valid: false,
        error: `Datei '${name || "Datei"}' überschreitet das Limit von 25 MB.`,
      };
    }
  }
  return { valid: true };
}

async function uploadFiles(files) {
  if (!files || !files.length) return;

  const validation = validateUploadFiles(files);
  if (!validation.valid) {
    showToast(validation.error, "warning");
    return;
  }

  if (!currentDraft) {
    await ensureDraft();
  }
  if (!currentDraft) {
    showToast("Konnte keinen Entwurf für den Foto-Upload erstellen.", "error");
    return;
  }

  const dropzoneP = dropzoneEl.querySelector("p");
  const originalText = dropzoneP ? dropzoneP.textContent : "";
  if (dropzoneP) dropzoneP.textContent = "⏳ Fotos werden hochgeladen & verarbeitet...";
  dropzoneEl.style.opacity = "0.7";
  dropzoneEl.style.pointerEvents = "none";

  const formData = new FormData();
  for (const f of files) {
    formData.append("files", f);
  }
  try {
    const res = await api.uploadImages(currentDraft.id, formData);
    if (res.ok) {
      currentDraft = await res.json();
      renderGallery();
      await loadDrafts();
      showToast("Fotos erfolgreich hochgeladen & verarbeitet.", "success");
    } else {
      const errData = await res.json().catch(() => ({}));
      if (res.status === 413) {
        showToast("Upload abgelehnt: Dateigröße überschreitet maximales Limit (25 MB).", "error");
      } else {
        showToast(`Upload fehlgeschlagen: ${errData.detail || res.statusText || "Serverfehler"}`, "error");
      }
    }
  } catch (err) {
    console.error("Upload error", err);
    showToast(`Fehler beim Upload: ${err.message}`, "error");
  } finally {
    if (dropzoneP) dropzoneP.textContent = originalText;
    dropzoneEl.style.opacity = "1";
    dropzoneEl.style.pointerEvents = "auto";
  }
}

function setupEventListeners() {
  btnNewDraft.onclick = async () => {
    try {
      const newD = await api.createDraft({ user_notes: "" });
      currentDraft = newD;
      await loadDrafts();
      selectDraft(newD.id);
    } catch (err) {
      console.error("Failed to create draft", err);
    }
  };

  dropzoneEl.onclick = (e) => {
    if (e.target !== fileInputEl) {
      fileInputEl.click();
    }
  };

  fileInputEl.onchange = async () => {
    if (!fileInputEl.files || !fileInputEl.files.length) return;
    const files = Array.from(fileInputEl.files);
    fileInputEl.value = "";
    await uploadFiles(files);
  };

  dropzoneEl.addEventListener("dragover", e => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
    dropzoneEl.style.borderColor = "var(--primary)";
    dropzoneEl.style.background = "#eff6ff";
  });

  dropzoneEl.addEventListener("dragleave", () => {
    dropzoneEl.style.borderColor = "";
    dropzoneEl.style.background = "";
  });

  dropzoneEl.addEventListener("drop", async e => {
    e.preventDefault();
    dropzoneEl.style.borderColor = "";
    dropzoneEl.style.background = "";
    if (!e.dataTransfer || !e.dataTransfer.files || !e.dataTransfer.files.length) return;
    await uploadFiles(e.dataTransfer.files);
  });

  window.addEventListener("dragover", e => e.preventDefault());
  window.addEventListener("drop", e => e.preventDefault());

  ricardoTitle.oninput = () => updateCharCounter(ricardoTitle, ricardoTitleCount, 60);
  tuttiTitle.oninput = () => updateCharCounter(tuttiTitle, tuttiTitleCount, 60);
  if (tuttiDescription && tuttiDescriptionCount) {
    tuttiDescription.oninput = () => updateCharCounter(tuttiDescription, tuttiDescriptionCount, 4000);
  }
  if (ebayDeTitle) {
    ebayDeTitle.oninput = () => updateCharCounter(ebayDeTitle, ebayDeTitleCount, 80);
  }
  if (kleinanzeigenTitle) {
    kleinanzeigenTitle.oninput = () => updateCharCounter(kleinanzeigenTitle, kleinanzeigenTitleCount, 65);
  }

  btnSaveDraft.onclick = async () => {
    if (!currentDraft) {
      await ensureDraft();
    }
    if (!currentDraft) return;
    syncDraftFromForm();
    try {
      const res = await api.updateDraft(currentDraft);
      if (res.ok) {
        currentDraft = await res.json();
        await loadDrafts();
        populateForm();
        showToast("Entwurf erfolgreich gespeichert!", "success");
      } else if (res.status === 409) {
        showToast(
          "Entwurf wurde anderweitig aktualisiert (Konflikt). Änderungen wurden nicht überschrieben.",
          "warning",
          {
            duration: 12000,
            actionText: "Neu laden",
            onAction: async () => {
              if (currentDraft && currentDraft.id) {
                await selectDraft(currentDraft.id);
                showToast("Entwurf neu geladen.", "info");
              }
            }
          }
        );
      } else {
        const err = await res.json().catch(() => ({}));
        showToast(`Fehler beim Speichern: ${err.detail || res.statusText || "Serverfehler"}`, "error");
      }
    } catch (err) {
      console.error("Failed to save draft", err);
      showToast(`Fehler beim Speichern: ${err.message}`, "error");
    }
  };

  if (btnScrapeExtension) {
    btnScrapeExtension.onclick = scrapePricesViaExtension;
  }

  btnAnalyze.onclick = async () => {
    if (!currentDraft) {
      await ensureDraft();
    }
    if (!currentDraft) return;
    syncDraftFromForm();
    // Save draft first
    await api.updateDraft(currentDraft);

    btnAnalyze.disabled = true;
    analyzeSpinner.classList.remove("hidden");
    try {
      const res = await api.analyzeDraft(currentDraft.id);
      if (res.ok) {
        currentDraft = await res.json();
        await loadDrafts();
        populateForm();
        showToast("KI-Analyse abgeschlossen!", "success");
      } else {
        const err = await res.json().catch(() => ({}));
        showToast(`Analyse fehlgeschlagen: ${err.detail || "Serverfehler"}`, "error");
        if (err.detail && (err.detail.includes("API-Key") || err.detail.includes("Gemini"))) {
          openSettingsModal();
        }
      }
    } catch (err) {
      console.error("Analysis error", err);
      showToast("Fehler bei der Analyse.", "error");
    } finally {
      btnAnalyze.disabled = false;
      analyzeSpinner.classList.add("hidden");
    }
  };

  if (btnSettings) btnSettings.onclick = openSettingsModal;
  if (btnCloseSettings) btnCloseSettings.onclick = closeSettingsModal;
  if (btnCancelSettings) btnCancelSettings.onclick = closeSettingsModal;
  if (modalBackdrop) modalBackdrop.onclick = closeSettingsModal;
  if (btnSaveSettings) btnSaveSettings.onclick = saveSystemConfig;
  if (btnToggleKey) {
    btnToggleKey.onclick = () => {
      cfgGeminiKey.type = cfgGeminiKey.type === "password" ? "text" : "password";
    };
  }

  if (btnCreatePairingPin) {
    btnCreatePairingPin.onclick = async () => {
      try {
        btnCreatePairingPin.disabled = true;
        const res = await api.createPairingCode();
        if (res && res.pairing_code) {
          if (pairingPinDisplay) {
            pairingPinDisplay.textContent = `PIN: ${res.pairing_code}`;
            pairingPinDisplay.style.display = "inline-block";
          }
          if (pairingPinHint) {
            pairingPinHint.textContent = `PIN ${res.pairing_code} aktiv (gültig 60s). Autorisierung wird an Extension übertragen...`;
          }
          const pairRes = await api.pairAuth(res.pairing_code).catch(() => null);
          if (pairRes && pairRes.token && typeof window !== "undefined") {
            window.postMessage(JSON.stringify({ type: "OCCAISION_SET_TOKEN", token: pairRes.token }), window.location.origin);
            showToast("Extension erfolgreich autorisiert!", "success");
            if (pairingPinHint) {
              pairingPinHint.textContent = "Browser-Extension erfolgreich autorisiert.";
            }
          } else {
            showToast(`PIN ${res.pairing_code} generiert.`, "info");
          }
        }
      } catch (err) {
        showToast(`Kopplung fehlgeschlagen: ${err.message}`, "error");
      } finally {
        btnCreatePairingPin.disabled = false;
      }
    };
  }

  if (btnExportBackup) {
    btnExportBackup.onclick = async () => {
      try {
        const res = await api.exportBackup();
        if (!res.ok) throw new Error(`Export fehlgeschlagen (${res.status})`);
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        const disp = res.headers.get("content-disposition") || "";
        const match = disp.match(/filename="?([^"]+)"?/);
        a.download = match ? match[1] : `occaision_backup_${Date.now()}.zip`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        showToast("Vollständiges Backup (.zip) erfolgreich heruntergeladen.", "success");
      } catch (err) {
        showToast(`Export fehlgeschlagen: ${err.message}`, "error");
      }
    };
  }

  if (backupFileInput) {
    backupFileInput.onchange = async (e) => {
      const file = e.target.files && e.target.files[0];
      if (!file) return;
      const isZip = file.name.toLowerCase().endsWith(".zip");
      const formData = new FormData();
      formData.append("file", file);
      try {
        const res = isZip ? await api.restoreBackup(formData) : await api.importDrafts(formData);
        if (res.ok) {
          const result = await res.json();
          await loadDrafts();
          await loadSettings();
          const count = result.restored_drafts ?? result.imported_count ?? 0;
          showToast(`Backup erfolgreich wiederhergestellt (${count} Entwürfe geladen).`, "success");
        } else {
          const err = await res.json().catch(() => ({}));
          showToast(`Wiederherstellung fehlgeschlagen: ${err.detail || res.statusText}`, "error");
        }
      } catch (err) {
        showToast(`Wiederherstellung fehlgeschlagen: ${err.message}`, "error");
      } finally {
        backupFileInput.value = "";
      }
    };
  }
}

function syncDraftFromForm() {
  if (!currentDraft) return;
  currentDraft.status = draftStatusSelect.value;
  if (productNameEl) {
    currentDraft.identified_product = productNameEl.value.trim();
  }
  currentDraft.user_notes = userNotesEl.value;

  currentDraft.ricardo.offer_type = offerTypeEl.value;
  currentDraft.ricardo.shipping_preset_id = shippingPresetEl.value;
  currentDraft.ricardo.title = ricardoTitle.value;
  currentDraft.ricardo.condition = ricardoCondition.value;
  currentDraft.ricardo.start_price_chf = parseFloat(ricardoStartPrice.value) || 1.0;
  currentDraft.ricardo.buynow_price_chf = parseFloat(ricardoBuyNowPrice.value) || 10.0;
  currentDraft.ricardo.description = ricardoDescription.value;

  currentDraft.tutti.title = tuttiTitle.value;
  currentDraft.tutti.category_suggestion = tuttiCategory.value;
  currentDraft.tutti.condition = tuttiCondition.value;
  currentDraft.tutti.price_vhb_chf = parseFloat(tuttiPrice.value) || 10.0;
  currentDraft.tutti.description = tuttiDescription.value;

  if (!currentDraft.ebay_de) currentDraft.ebay_de = {};
  if (ebayDeTitle) currentDraft.ebay_de.title = ebayDeTitle.value;
  if (ebayDeCategory) currentDraft.ebay_de.category_suggestion = ebayDeCategory.value;
  if (ebayDeCondition) currentDraft.ebay_de.condition = ebayDeCondition.value;
  if (ebayDeOfferType) currentDraft.ebay_de.offer_type = ebayDeOfferType.value;
  if (ebayDeStartPrice) currentDraft.ebay_de.start_price_eur = parseFloat(ebayDeStartPrice.value) || 1.0;
  if (ebayDeBuyNowPrice) currentDraft.ebay_de.buynow_price_eur = parseFloat(ebayDeBuyNowPrice.value) || 10.0;
  if (ebayDeDescription) currentDraft.ebay_de.description = ebayDeDescription.value;
  if (deShippingPresetEl) currentDraft.ebay_de.shipping_preset_id = deShippingPresetEl.value;

  if (!currentDraft.kleinanzeigen) currentDraft.kleinanzeigen = {};
  if (kleinanzeigenTitle) currentDraft.kleinanzeigen.title = kleinanzeigenTitle.value;
  if (kleinanzeigenCategory) currentDraft.kleinanzeigen.category_suggestion = kleinanzeigenCategory.value;
  if (kleinanzeigenCondition) currentDraft.kleinanzeigen.condition = kleinanzeigenCondition.value;
  if (kleinanzeigenPrice) currentDraft.kleinanzeigen.price_eur = parseFloat(kleinanzeigenPrice.value) || 10.0;
  if (kleinanzeigenPriceType) currentDraft.kleinanzeigen.price_type = kleinanzeigenPriceType.value;
  if (kleinanzeigenDescription) currentDraft.kleinanzeigen.description = kleinanzeigenDescription.value;
  if (deShippingPresetEl) currentDraft.kleinanzeigen.shipping_preset_id = deShippingPresetEl.value;
}

async function scrapePricesViaExtension() {
  if (!currentDraft) {
    await ensureDraft();
  }
  if (!currentDraft) return;
  syncDraftFromForm();

  const query = (
    (productNameEl && productNameEl.value.trim()) ||
    currentDraft.identified_product ||
    userNotesEl.value.trim() ||
    ""
  ).trim();

  if (!query) {
    showToast("Bitte gib zuerst oben einen Produktnamen / Modell für die Preisrecherche ein.", "warning");
    if (productNameEl) productNameEl.focus();
    return;
  }

  const rate = (systemConfig && systemConfig.eur_to_chf_rate) || 0.94;
  const reqId = `scrape_${Date.now()}`;

  if (btnScrapeExtension) btnScrapeExtension.disabled = true;
  if (analyzeSpinner) {
    analyzeSpinner.textContent = `🔍 Frage 6 Preisquellen über Firefox-Extension ab für '${query}'...`;
    analyzeSpinner.classList.remove("hidden");
  }

  try {
    const extResult = await new Promise((resolve, reject) => {
      let settled = false;

      function finish(ok, dataOrErr) {
        if (settled) return;
        settled = true;
        clearTimeout(timeout);
        window.removeEventListener("message", onMsg);
        if (ok) resolve(dataOrErr);
        else reject(dataOrErr);
      }

      const timeout = setTimeout(() => {
        finish(
          false,
          new Error(
            "Keine Antwort von der OccAIsion Firefox-Extension erhalten. " +
              "Bitte stelle sicher, dass die Extension in Firefox geladen ist, klicke einmal auf das OccAIsion Icon in der Firefox-Toolbar (um die Berechtigungen freizugeben) und lade das Dashboard neu (F5)."
          )
        );
      }, 35000);

      function onMsg(event) {
        if (!event || !event.data) return;
        let msg = event.data;
        if (typeof msg === "string") {
          try {
            msg = JSON.parse(msg);
          } catch (_) {
            return;
          }
        }
        if (
          msg &&
          msg.type === "OCCAISION_SCRAPE_PRICES_RESULT" &&
          msg.requestId === reqId
        ) {
          if (msg.ok) {
            finish(true, msg);
          } else {
            finish(false, new Error(msg.error || "Extension-Fehler bei der Preisrecherche"));
          }
        }
      }

      const enabledSources = getEnabledPriceSources();
      const keepTabsOpen = Boolean(settings && settings.keep_tabs_open_after_search);
      window.addEventListener("message", onMsg);
      window.postMessage(
        JSON.stringify({
          type: "OCCAISION_SCRAPE_PRICES",
          requestId: reqId,
          query: query,
          eurToChfRate: rate,
          enabledSources: enabledSources,
          keepTabsOpen: keepTabsOpen,
        }),
        "*"
      );
    });

    if (!currentDraft.price_analysis) {
      currentDraft.price_analysis = {};
    }
    const sources = extResult.sources || {};
    currentDraft.price_analysis.market_sources = sources;
    currentDraft.price_analysis.prices_fetched_via_extension = true;

    if (sources.ebay_de_sold) {
      const eb = sources.ebay_de_sold;
      currentDraft.price_analysis.ebay_stats = {
        query: query,
        sample_count: eb.sample_count || 0,
        min_eur: eb.min_price ?? null,
        max_eur: eb.max_price ?? null,
        median_eur: eb.median_price ?? null,
        median_chf: eb.median_chf ?? null,
        exchange_rate: rate,
      };

      if (eb.items && eb.items.length > 0) {
        console.group(`[OccAIsion] [Dashboard] eBay DE extrahierte Artikel (${eb.items.length} Treffer):`);
        eb.items.forEach((it, idx) => {
          console.log(`  #${idx + 1}: ${it.price} € | [${it.condition}] | "${it.title}"`);
        });
        console.groupEnd();
        if (typeof console.table === "function") {
          try {
            console.table(
              eb.items.map((it, idx) => ({
                "#": idx + 1,
                "Preis (€)": it.price,
                "Zustand": it.condition,
                "Titel": it.title,
              }))
            );
          } catch (_) {}
        }
      }
    } else {
      currentDraft.price_analysis.ebay_stats = null;
    }

    if (sources.kleinanzeigen && sources.kleinanzeigen.items && sources.kleinanzeigen.items.length > 0) {
      const ka = sources.kleinanzeigen;
      console.group(`[OccAIsion] [Dashboard] Kleinanzeigen extrahierte Artikel (${ka.items.length} Treffer):`);
      ka.items.forEach((it, idx) => {
        console.log(`  #${idx + 1}: ${it.price} € | Zustand: [${it.condition || "Gebraucht"}] | "${it.title}"`);
      });
      console.groupEnd();
      if (typeof console.table === "function") {
        try {
          console.table(
            ka.items.map((it, idx) => ({
              "#": idx + 1,
              "Preis (€)": it.price,
              "Zustand": it.condition || "Gebraucht",
              "Titel": it.title,
            }))
          );
        } catch (_) {}
      }
    }

    if (sources.idealo && sources.idealo.items && sources.idealo.items.length > 0) {
      const idl = sources.idealo;
      console.group(`[OccAIsion] [Dashboard] Idealo extrahierte Neupreise (${idl.items.length} Treffer):`);
      idl.items.forEach((it, idx) => {
        console.log(`  #${idx + 1}: ${it.price} € | Zustand: [${it.condition || "Neu"}] | "${it.title}"`);
      });
      console.groupEnd();
      if (typeof console.table === "function") {
        try {
          console.table(
            idl.items.map((it, idx) => ({
              "#": idx + 1,
              "Preis (€)": it.price,
              "Zustand": it.condition || "Neu",
              "Titel": it.title,
            }))
          );
        } catch (_) {}
      }
    }

    if (sources.toppreise && sources.toppreise.items && sources.toppreise.items.length > 0) {
      const tp = sources.toppreise;
      console.group(`[OccAIsion] [Dashboard] Toppreise extrahierte Neupreise (${tp.items.length} Treffer):`);
      tp.items.forEach((it, idx) => {
        console.log(`  #${idx + 1}: ${it.price} CHF | Zustand: [${it.condition || "Neu"}] | "${it.title}"`);
      });
      console.groupEnd();
      if (typeof console.table === "function") {
        try {
          console.table(
            tp.items.map((it, idx) => ({
              "#": idx + 1,
              "Preis (CHF)": it.price,
              "Zustand": it.condition || "Neu",
              "Titel": it.title,
            }))
          );
        } catch (_) {}
      }
    }

    if (sources.digitec && sources.digitec.items && sources.digitec.items.length > 0) {
      const dg = sources.digitec;
      console.group(`[OccAIsion] [Dashboard] Galaxus/Digitec extrahierte Neupreise (${dg.items.length} Treffer):`);
      dg.items.forEach((it, idx) => {
        console.log(`  #${idx + 1}: ${it.price} CHF | Zustand: [${it.condition || "Neu"}] | "${it.title}"`);
      });
      console.groupEnd();
      if (typeof console.table === "function") {
        try {
          console.table(
            dg.items.map((it, idx) => ({
              "#": idx + 1,
              "Preis (CHF)": it.price,
              "Zustand": it.condition || "Neu",
              "Titel": it.title,
            }))
          );
        } catch (_) {}
      }
    }

    if (sources.tutti && sources.tutti.items && sources.tutti.items.length > 0) {
      const tut = sources.tutti;
      console.group(`[OccAIsion] [Dashboard] Tutti.ch extrahierte Inserate (${tut.items.length} Treffer):`);
      tut.items.forEach((it, idx) => {
        console.log(`  #${idx + 1}: ${it.price} CHF | "${it.title}"`);
      });
      console.groupEnd();
      if (typeof console.table === "function") {
        try {
          console.table(
            tut.items.map((it, idx) => ({
              "#": idx + 1,
              "Preis (CHF)": it.price,
              "Titel": it.title,
              "URL": it.url,
            }))
          );
        } catch (_) {}
      }
    }

    if (sources.toppreise && sources.toppreise.median_price) {
      currentDraft.price_analysis.ch_new_price_chf = sources.toppreise.median_price;
    } else if (sources.digitec && sources.digitec.median_price) {
      currentDraft.price_analysis.ch_new_price_chf = sources.digitec.median_price;
    }

    if (sources.idealo && sources.idealo.median_price) {
      currentDraft.price_analysis.de_new_price_eur = sources.idealo.median_price;
    }

    if (extResult.verification_links) {
      currentDraft.price_analysis.verification_links = extResult.verification_links;
    }

    const res = await api.updateDraft(currentDraft);
    if (res.ok) {
      currentDraft = await res.json();
      await loadDrafts();
      populateForm();
    }
  } catch (err) {
    console.error("Extension price scrape failed", err);
    showToast(`Preisrecherche fehlgeschlagen: ${err.message}`, "error");
  } finally {
    if (btnScrapeExtension) btnScrapeExtension.disabled = false;
    if (analyzeSpinner) {
      analyzeSpinner.textContent = "Analysiere Bilder & Marktdaten...";
      analyzeSpinner.classList.add("hidden");
    }
  }
}

async function deleteDraft(draftId) {
  if (!confirm("Entwurf wirklich löschen?")) return;
  try {
    await api.deleteDraft(draftId);
    if (currentDraft && currentDraft.id === draftId) {
      currentDraft = null;
    }
    await loadDrafts();
    if (!currentDraft && drafts.length > 0) {
      selectDraft(drafts[0].id);
    } else if (drafts.length === 0) {
      await ensureDraft();
    }
  } catch (err) {
    console.error("Delete draft error", err);
  }
}

if (typeof window !== "undefined") {
  window.addEventListener("DOMContentLoaded", init);
}
if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    validateUploadFiles,
    MAX_UPLOAD_FILES,
    MAX_FILE_BYTES,
    ALLOWED_IMAGE_EXTENSIONS,
  };
}
