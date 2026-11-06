// OccAIsion Toast Notification Module
(function () {
  function showToast(message, type = "info", options = {}) {
    const toastContainer = document.getElementById("toast-container");
    if (!toastContainer) {
      if (type === "error" || type === "warning") {
        console.warn(`[${type}] ${message}`);
      }
      return null;
    }
    const {
      duration = (type === "error" || type === "warning" ? 7000 : 4000),
      actionText = null,
      onAction = null
    } = options;

    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;

    const content = document.createElement("div");
    content.className = "toast-content";
    content.textContent = message;
    toast.appendChild(content);

    if (actionText && typeof onAction === "function") {
      const actionBtn = document.createElement("button");
      actionBtn.className = "toast-action-btn";
      actionBtn.textContent = actionText;
      actionBtn.onclick = (e) => {
        e.stopPropagation();
        toast.remove();
        onAction();
      };
      toast.appendChild(actionBtn);
    }

    const closeBtn = document.createElement("button");
    closeBtn.className = "toast-close-btn";
    closeBtn.setAttribute("aria-label", "Schließen");
    closeBtn.textContent = "×";
    closeBtn.onclick = () => {
      toast.classList.add("toast-fade-out");
      setTimeout(() => toast.remove(), 200);
    };
    toast.appendChild(closeBtn);

    toastContainer.appendChild(toast);

    if (duration > 0) {
      setTimeout(() => {
        if (toast.isConnected) {
          toast.classList.add("toast-fade-out");
          setTimeout(() => toast.remove(), 200);
        }
      }, duration);
    }

    return toast;
  }

  if (typeof window !== "undefined") {
    window.showToast = showToast;
  }
  if (typeof module !== "undefined" && module.exports) {
    module.exports = { showToast };
  }
})();
