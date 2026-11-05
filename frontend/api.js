// OccAIsion Frontend API Client
async function parseResponse(res, defaultErrorMsg) {
  if (!res.ok) {
    const errData = typeof res.json === "function" ? await res.json().catch(() => ({})) : {};
    const err = new Error(errData.detail || `${defaultErrorMsg}: ${res.status}`);
    err.status = res.status;
    err.data = errData;
    throw err;
  }
  return typeof res.json === "function" ? res.json() : {};
}

const api = {
  async pairAuth() {
    const res = await fetch("/api/auth/pair", { method: "POST" });
    return parseResponse(res, "Pairing failed");
  },

  async getConfig() {
    const res = await fetch("/api/config");
    return parseResponse(res, "Failed to load config");
  },

  async updateConfig(payload) {
    const res = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return parseResponse(res, "Failed to update config");
  },

  async getSettings() {
    const res = await fetch("/api/settings");
    return parseResponse(res, "Failed to load settings");
  },

  async updateSettings(settings) {
    const res = await fetch("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settings),
    });
    return parseResponse(res, "Failed to update settings");
  },

  async listDrafts() {
    const res = await fetch("/api/drafts");
    return parseResponse(res, "Failed to load drafts");
  },

  async getDraft(id) {
    const res = await fetch(`/api/drafts/${encodeURIComponent(id)}`);
    return parseResponse(res, "Draft not found");
  },

  async createDraft(payload = {}) {
    const res = await fetch("/api/drafts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return parseResponse(res, "Failed to create draft");
  },

  async updateDraft(draft) {
    return fetch(`/api/drafts/${encodeURIComponent(draft.id)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(draft),
    });
  },

  async deleteDraft(id) {
    const res = await fetch(`/api/drafts/${encodeURIComponent(id)}`, { method: "DELETE" });
    return parseResponse(res, "Failed to delete draft");
  },

  async analyzeDraft(id) {
    return fetch(`/api/drafts/${encodeURIComponent(id)}/analyze`, { method: "POST" });
  },

  async uploadImages(draftId, formData) {
    return fetch(`/api/drafts/${encodeURIComponent(draftId)}/images`, {
      method: "POST",
      body: formData,
    });
  },

  async deleteImage(draftId, imageId) {
    return fetch(`/api/drafts/${encodeURIComponent(draftId)}/images/${encodeURIComponent(imageId)}`, {
      method: "DELETE",
    });
  },

  async setVariant(draftId, imageId, mode) {
    return fetch(`/api/drafts/${encodeURIComponent(draftId)}/images/${encodeURIComponent(imageId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ active_mode: mode }),
    });
  },

  async exportDrafts() {
    return fetch("/api/drafts/export");
  },

  async importDrafts(formData) {
    return fetch("/api/drafts/import", {
      method: "POST",
      body: formData,
    });
  },
};

if (typeof window !== "undefined") {
  window.api = api;
}
if (typeof module !== "undefined" && module.exports) {
  module.exports = api;
}
