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
const offerTypeEl = document.getElementById("offer-type");
const btnAnalyze = document.getElementById("btn-analyze");
const analyzeSpinner = document.getElementById("analyze-spinner");

// Section 2: Analysis elements
const missingHintsBox = document.getElementById("missing-hints-box");
const missingHintsList = document.getElementById("missing-hints-list");
const priceEbayMedian = document.getElementById("price-ebay-median");
const priceEbayCount = document.getElementById("price-ebay-count");
const priceChNew = document.getElementById("price-ch-new");
const priceRecStart = document.getElementById("price-rec-start");
const priceRecBuyNow = document.getElementById("price-rec-buynow");
const priceRecTutti = document.getElementById("price-rec-tutti");
const priceReasoningText = document.getElementById("price-reasoning-text");
const linkEbay = document.getElementById("link-ebay");
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

async function init() {
  await loadSettings();
  await loadDrafts();
  setupEventListeners();
}

async function loadSettings() {
  try {
    const res = await fetch("/api/settings");
    if (res.ok) {
      settings = await res.json();
      shippingPresetEl.innerHTML = "";
      settings.shipping_presets.forEach(p => {
        const opt = document.createElement("option");
        opt.value = p.id;
        opt.textContent = p.label;
        shippingPresetEl.appendChild(opt);
      });
    }
  } catch (err) {
    console.error("Failed to load settings", err);
  }
}

async function loadDrafts() {
  try {
    const res = await fetch("/api/drafts");
    if (res.ok) {
      drafts = await res.json();
      renderDraftList();
      if (drafts.length > 0 && !currentDraft) {
        selectDraft(drafts[0].id);
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
  priceRecStart.textContent = `${pa.ricardo_start_chf || 1.0} CHF`;
  priceRecBuyNow.textContent = `${pa.ricardo_buynow_chf || 10.0} CHF`;
  priceRecTutti.textContent = `${pa.tutti_vhb_chf || 10.0} CHF`;
  priceReasoningText.textContent = pa.reasoning || "Noch keine Analyse.";

  // Verification links
  const vl = pa.verification_links;
  if (vl) {
    linkEbay.href = vl.ebay_sold_url || "#";
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
}

function renderGallery() {
  imageGalleryEl.innerHTML = "";
  if (!currentDraft || !currentDraft.images) return;

  currentDraft.images.forEach(img => {
    const card = document.createElement("div");
    card.className = "image-card";
    const cacheBuster = `?t=${Date.now()}`;
    const previewUrl = `/api/drafts/${currentDraft.id}/images/${img.id}/active${cacheBuster}`;

    card.innerHTML = `
      <img src="${previewUrl}" class="image-preview" alt="${img.original_filename}" />
      <div class="image-card-controls">
        <div class="mode-selectors">
          <button class="btn-mode ${img.active_mode === 'optimized' ? 'active' : ''}" onclick="changeImageMode('${img.id}', 'optimized')">Original</button>
          <button class="btn-mode ${img.active_mode === 'blurred' ? 'active' : ''}" onclick="changeImageMode('${img.id}', 'blurred')">Blur</button>
          <button class="btn-mode ${img.active_mode === 'cutout' ? 'active' : ''}" onclick="changeImageMode('${img.id}', 'cutout')">rembg</button>
        </div>
        <button class="btn-del-img" onclick="deleteImage('${img.id}')">Bild löschen 🗑️</button>
      </div>
    `;
    imageGalleryEl.appendChild(card);
  });
}

async function changeImageMode(imageId, mode) {
  if (!currentDraft) return;
  try {
    const res = await fetch(`/api/drafts/${currentDraft.id}/images/${imageId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ active_mode: mode })
    });
    if (res.ok) {
      currentDraft = await res.json();
      renderGallery();
    }
  } catch (err) {
    console.error("Failed to change mode", err);
  }
}

async function deleteImage(imageId) {
  if (!currentDraft) return;
  try {
    const res = await fetch(`/api/drafts/${currentDraft.id}/images/${imageId}`, {
      method: "DELETE"
    });
    if (res.ok) {
      currentDraft = await res.json();
      renderGallery();
    }
  } catch (err) {
    console.error("Failed to delete image", err);
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
  if (!currentDraft || !files || !files.length) return;
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
    }
  } catch (err) {
    console.error("Upload error", err);
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
        await loadDrafts();
        selectDraft(newD.id);
      }
    } catch (err) {
      console.error("Failed to create draft", err);
    }
  };

  fileInputEl.onchange = async () => {
    if (!currentDraft || !fileInputEl.files.length) return;
    await uploadFiles(fileInputEl.files);
    fileInputEl.value = "";
  };

  dropzoneEl.addEventListener("dragover", e => {
    e.preventDefault();
    dropzoneEl.style.borderColor = "var(--primary)";
  });

  dropzoneEl.addEventListener("dragleave", () => {
    dropzoneEl.style.borderColor = "";
  });

  dropzoneEl.addEventListener("drop", async e => {
    e.preventDefault();
    dropzoneEl.style.borderColor = "";
    if (!currentDraft || !e.dataTransfer || !e.dataTransfer.files.length) return;
    await uploadFiles(e.dataTransfer.files);
  });

  ricardoTitle.oninput = () => updateCharCounter(ricardoTitle, ricardoTitleCount, 60);
  tuttiTitle.oninput = () => updateCharCounter(tuttiTitle, tuttiTitleCount, 80);

  btnSaveDraft.onclick = async () => {
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
        const err = await res.json();
        alert(`Analyse fehlgeschlagen: ${err.detail || "Serverfehler"}`);
      }
    } catch (err) {
      console.error("Analysis error", err);
      alert("Fehler bei der Analyse.");
    } finally {
      btnAnalyze.disabled = false;
      analyzeSpinner.classList.add("hidden");
    }
  };
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
        window.location.reload();
      }
    }
  } catch (err) {
    console.error("Delete draft error", err);
  }
}

window.addEventListener("DOMContentLoaded", init);
