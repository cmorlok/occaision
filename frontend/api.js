// OccAIsion Frontend API Client
const api = {
  async pairAuth() {
    const res = await fetch("/api/auth/pair", { method: "POST" });
    if (!res.ok) throw new Error(`Pairing failed: ${res.status}`);
    return res.json();
  },

  async getConfig() {
    const res = await fetch("/api/config");
    if (!res.ok) throw new Error(`Failed to load config: ${res.status}`);
    return res.json();
  },

  async updateConfig(payload) {
    const res = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(`Failed to update config: ${res.status}`);
    return res.json();
  },

  async getSettings() {
    const res = await fetch("/api/settings");
    if (!res.ok) throw new Error(`Failed to load settings: ${res.status}`);
    return res.json();
  },

  async updateSettings(settings) {
    const res = await fetch("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settings),
    });
    if (!res.ok) throw new Error(`Failed to update settings: ${res.status}`);
    return res.json();
  },

  async listDrafts() {
    const res = await fetch("/api/drafts");
    if (!res.ok) throw new Error(`Failed to load drafts: ${res.status}`);
    return res.json();
  },

  async getDraft(id) {
    const res = await fetch(`/api/drafts/${encodeURIComponent(id)}`);
    if (!res.ok) throw new Error(`Draft not found: ${res.status}`);
    return res.json();
  },

  async createDraft(payload = {}) {
    const res = await fetch("/api/drafts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(`Failed to create draft: ${res.status}`);
    return res.json();
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
    if (!res.ok) throw new Error(`Failed to delete draft: ${res.status}`);
    return res.json();
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
};

if (typeof window !== "undefined") {
  window.api = api;
}
if (typeof module !== "undefined" && module.exports) {
  module.exports = api;
}
