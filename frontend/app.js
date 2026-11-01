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
const userNotesEl = document.getElementById("user-notes");
const shippingPresetEl = document.getElementById("shipping-preset");
const deShippingPresetEl = document.getElementById("de-shipping-preset");
const offerTypeEl = document.getElementById("offer-type");
const btnAnalyze = document.getElementById("btn-analyze");
const analyzeSpinner = document.getElementById("analyze-spinner");

// Section 2: Analysis elements
const missingHintsBox = document.getElementById("missing-hints-box");
const missingHintsList = document.getElementById("missing-hints-list");
const priceEbayMedian = document.getElementById("price-ebay-median");
const priceEbayCount = document.getElementById("price-ebay-count");
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
const cfgKeyStatus = document.getElementById("cfg-key-status");

let systemConfig = null;

async function init() {
  await loadSettings();
  await loadSystemConfig();
  await loadDrafts();
  setupEventListeners();
}

async function loadSystemConfig() {
  try {
    const res = await fetch("/api/config");
    if (res.ok) {
      systemConfig = await res.json();
      
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
      updateKeyStatusUI();
    }
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

function openSettingsModal() {
  if (!settingsModal) return;
  loadSystemConfig();
  if (cfgGeminiKey) cfgGeminiKey.value = "";
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
  if (newKey) {
    payload.gemini_api_key = newKey;
  }

  try {
    btnSaveSettings.disabled = true;
    const res = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (res.ok) {
      systemConfig = await res.json();
      updateKeyStatusUI();
      closeSettingsModal();
      alert("Einstellungen erfolgreich gespeichert!");
    } else {
      const err = await res.json().catch(() => ({}));
      alert(`Fehler beim Speichern: ${err.detail || "Serverfehler"}`);
    }
  } catch (err) {
    alert(`Fehler: ${err.message}`);
  } finally {
    btnSaveSettings.disabled = false;
  }
}

async function loadSettings() {
  try {
    const res = await fetch("/api/settings");
    if (res.ok) {
      settings = await res.json();
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
    }
  } catch (err) {
    console.error("Failed to load settings", err);
  }
}

async function ensureDraft() {
  if (currentDraft) return currentDraft;
  try {
    const res = await fetch("/api/drafts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_notes: "" })
    });
    if (res.ok) {
      currentDraft = await res.json();
      drafts = [currentDraft, ...drafts.filter(d => d.id !== currentDraft.id)];
      renderDraftList();
      populateForm();
      return currentDraft;
    }
  } catch (err) {
    console.error("Failed to auto-create draft", err);
  }
  return null;
}

async function loadDrafts() {
  try {
    const res = await fetch("/api/drafts");
    if (res.ok) {
      drafts = await res.json();
      renderDraftList();
      if (drafts.length > 0) {
        if (!currentDraft || !drafts.some(d => d.id === currentDraft.id)) {
          await selectDraft(drafts[0].id);
        }
      } else if (!currentDraft) {
        await ensureDraft();
      }
    }
  } catch (err) {
    console.error("Failed to load drafts", err);
  }
}

function renderDraftList() {
  draftListEl.innerHTML = "";
  drafts.forEach(d => {
    const item = document.createElement("div");
    item.className = `draft-item ${currentDraft && currentDraft.id === d.id ? "active" : ""}`;
    item.onclick = () => selectDraft(d.id);

    const title = d.identified_product || d.user_notes || d.ricardo.title || "Neuer Entwurf";
    const statusClass = `status-${d.status}`;
    const dateStr = new Date(d.updated_at).toLocaleDateString("de-CH", { hour: "2-digit", minute: "2-digit" });

    item.innerHTML = `
      <div class="draft-item-header">
        <span class="draft-item-title" title="${title}">${title}</span>
        <span class="status-badge ${statusClass}">${d.status}</span>
      </div>
      <div class="draft-item-footer">
        <span>${dateStr}</span>
        <button class="btn-delete-draft" title="Löschen" onclick="event.stopPropagation(); deleteDraft('${d.id}')">🗑️</button>
      </div>
    `;
    draftListEl.appendChild(item);
  });
}

async function selectDraft(draftId) {
  try {
    const res = await fetch(`/api/drafts/${draftId}`);
    if (res.ok) {
      currentDraft = await res.json();
      populateForm();
      renderDraftList();
    }
  } catch (err) {
    console.error("Failed to fetch draft", err);
  }
}

function populateForm() {
  if (!currentDraft) return;

  activeDraftTitleEl.textContent = currentDraft.identified_product || currentDraft.user_notes || "Entwurf bearbeiten";
  draftStatusSelect.value = currentDraft.status;
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
    missingHintsList.innerHTML = currentDraft.missing_photo_hints.map(h => `<li>${h}</li>`).join("");
    missingHintsBox.classList.remove("hidden");
  } else {
    missingHintsBox.classList.add("hidden");
  }

  // Prices
  const pa = currentDraft.price_analysis || {};
  if (pa.ebay_stats && pa.ebay_stats.median_eur) {
    priceEbayMedian.textContent = `${pa.ebay_stats.median_eur} € (~${pa.ebay_stats.median_chf} CHF)`;
    priceEbayCount.textContent = `${pa.ebay_stats.sample_count} verkaufte Artikel`;
  } else {
    priceEbayMedian.textContent = "-";
    priceEbayCount.textContent = "Keine Daten";
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
  updateCharCounter(tuttiTitle, tuttiTitleCount, 80);
  tuttiCategory.value = currentDraft.tutti.category_suggestion || "";
  tuttiCondition.value = currentDraft.tutti.condition || "gebraucht";
  tuttiPrice.value = currentDraft.tutti.price_vhb_chf || 10.0;
  tuttiDescription.value = currentDraft.tutti.description || "";

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
  imageGalleryEl.innerHTML = "";
  if (!currentDraft || !currentDraft.images) return;

  currentDraft.images.forEach(img => {
    const card = document.createElement("div");
    card.className = "image-card";
    card.id = `image-card-${img.id}`;
    const cacheBuster = `?t=${Date.now()}`;
    const previewUrl = `/api/drafts/${currentDraft.id}/images/${img.id}/active${cacheBuster}`;

    card.innerHTML = `
      <img src="${previewUrl}" class="image-preview" alt="${img.original_filename}" />
      <div class="image-card-controls">
        <div class="mode-selectors">
          <button class="btn-mode ${img.active_mode === 'optimized' ? 'active' : ''}" onclick="changeImageMode('${img.id}', 'optimized')">Original</button>
          <button class="btn-mode ${img.active_mode === 'blurred' ? 'active' : ''}" onclick="changeImageMode('${img.id}', 'blurred')">Weichzeichnen</button>
          <button class="btn-mode ${img.active_mode === 'cutout' ? 'active' : ''}" onclick="changeImageMode('${img.id}', 'cutout')">Hintergrund entfernen</button>
        </div>
        <button class="btn-del-img" onclick="deleteImage('${img.id}')">Bild löschen 🗑️</button>
      </div>
    `;
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
    const res = await fetch(`/api/drafts/${currentDraft.id}/images/${imageId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ active_mode: mode })
    });
    if (res.ok) {
      currentDraft = await res.json();
      renderGallery();
    } else {
      const err = await res.json().catch(() => ({}));
      alert(`Fehler bei der Bildbearbeitung: ${err.detail || res.statusText || "Serverfehler"}`);
      if (overlay) overlay.remove();
      if (card) card.querySelectorAll("button").forEach(b => b.disabled = false);
    }
  } catch (err) {
    console.error("Failed to change mode", err);
    alert(`Fehler bei der Bildbearbeitung: ${err.message}`);
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
    const res = await fetch(`/api/drafts/${currentDraft.id}/images/${imageId}`, {
      method: "DELETE"
    });
    if (res.ok) {
      currentDraft = await res.json();
      renderGallery();
    } else {
      alert("Fehler beim Löschen des Fotos.");
      if (card) {
        card.style.opacity = "1";
        card.querySelectorAll("button").forEach(b => b.disabled = false);
      }
    }
  } catch (err) {
    console.error("Failed to delete image", err);
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

async function uploadFiles(files) {
  if (!files || !files.length) return;

  if (!currentDraft) {
    await ensureDraft();
  }
  if (!currentDraft) {
    alert("Konnte keinen Entwurf für den Foto-Upload erstellen.");
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
    const res = await fetch(`/api/drafts/${currentDraft.id}/images`, {
      method: "POST",
      body: formData
    });
    if (res.ok) {
      currentDraft = await res.json();
      renderGallery();
      await loadDrafts();
    } else {
      const errData = await res.json().catch(() => ({}));
      alert(`Upload fehlgeschlagen: ${errData.detail || res.statusText || "Serverfehler"}`);
    }
  } catch (err) {
    console.error("Upload error", err);
    alert(`Fehler beim Upload: ${err.message}`);
  } finally {
    if (dropzoneP) dropzoneP.textContent = originalText;
    dropzoneEl.style.opacity = "1";
    dropzoneEl.style.pointerEvents = "auto";
  }
}

function setupEventListeners() {
  btnNewDraft.onclick = async () => {
    try {
      const res = await fetch("/api/drafts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_notes: "" })
      });
      if (res.ok) {
        const newD = await res.json();
        currentDraft = newD;
        await loadDrafts();
        selectDraft(newD.id);
      }
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
  tuttiTitle.oninput = () => updateCharCounter(tuttiTitle, tuttiTitleCount, 80);
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
      const res = await fetch(`/api/drafts/${currentDraft.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(currentDraft)
      });
      if (res.ok) {
        currentDraft = await res.json();
        await loadDrafts();
        populateForm();
        alert("Entwurf erfolgreich gespeichert!");
      }
    } catch (err) {
      console.error("Failed to save draft", err);
    }
  };

  btnAnalyze.onclick = async () => {
    if (!currentDraft) {
      await ensureDraft();
    }
    if (!currentDraft) return;
    syncDraftFromForm();
    // Save draft first
    await fetch(`/api/drafts/${currentDraft.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(currentDraft)
    });

    btnAnalyze.disabled = true;
    analyzeSpinner.classList.remove("hidden");
    try {
      const res = await fetch(`/api/drafts/${currentDraft.id}/analyze`, {
        method: "POST"
      });
      if (res.ok) {
        currentDraft = await res.json();
        await loadDrafts();
        populateForm();
      } else {
        const err = await res.json().catch(() => ({}));
        alert(`Analyse fehlgeschlagen: ${err.detail || "Serverfehler"}`);
        if (err.detail && (err.detail.includes("API-Key") || err.detail.includes("Gemini"))) {
          openSettingsModal();
        }
      }
    } catch (err) {
      console.error("Analysis error", err);
      alert("Fehler bei der Analyse.");
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
}

function syncDraftFromForm() {
  if (!currentDraft) return;
  currentDraft.status = draftStatusSelect.value;
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

async function deleteDraft(draftId) {
  if (!confirm("Entwurf wirklich löschen?")) return;
  try {
    const res = await fetch(`/api/drafts/${draftId}`, { method: "DELETE" });
    if (res.ok) {
      if (currentDraft && currentDraft.id === draftId) {
        currentDraft = null;
      }
      await loadDrafts();
      if (!currentDraft && drafts.length > 0) {
        selectDraft(drafts[0].id);
      } else if (drafts.length === 0) {
        await ensureDraft();
      }
    }
  } catch (err) {
    console.error("Delete draft error", err);
  }
}

window.addEventListener("DOMContentLoaded", init);
