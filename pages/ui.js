/* 扩展模块共用的小工具：请求、转义、金额/时间格式化、轻提示。 */
window.UI = (() => {
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));

  class ApiError extends Error {
    constructor(status, payload) {
      super((payload && (payload.message || payload.error)) || ("HTTP " + status));
      this.status = status;
      this.payload = payload || {};
    }
  }

  async function api(path, options = {}) {
    const init = { method: options.method || "GET", headers: { "Content-Type": "application/json" } };
    if (options.body !== undefined) init.body = JSON.stringify(options.body);
    const response = await fetch(path, init);
    let payload = null;
    try { payload = await response.json(); } catch (err) { payload = { ok: false, error: "invalid_json" }; }
    if (!response.ok || payload.ok === false) throw new ApiError(response.status, payload);
    return payload;
  }

  const money = (cents) => "¥" + (Number(cents || 0) / 100).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const pct = (bps) => (Number(bps || 0) / 100).toFixed(bps % 100 === 0 ? 0 : 1) + "%";

  const time = (iso) => {
    if (!iso) return "—";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return iso;
    return date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
  };

  const tag = (label, tone = "") => `<span class="tag ${tone ? "tag-" + tone : ""}">${escapeHtml(label)}</span>`;

  const STATUS_TONES = {
    draft: "", open: "accent", funded: "green", in_production: "green", completed: "green", cancelled: "muted",
    created: "amber", dispatched: "accent", accepted: "accent", in_progress: "accent", qc_pending: "amber",
    qc_passed: "green", rework: "amber", shipped: "green", settled: "green", escalated: "red",
    offered: "amber", declined: "red", resolved: "green", rejected: "muted",
  };
  const statusTag = (status, label) => tag(label || status, STATUS_TONES[status] || "");

  let toastTimer = null;
  function toast(message, tone = "ok") {
    let node = document.getElementById("ui-toast");
    if (!node) {
      node = document.createElement("div");
      node.id = "ui-toast";
      node.className = "ui-toast";
      document.body.appendChild(node);
    }
    node.className = "ui-toast is-visible " + (tone === "error" ? "is-error" : "");
    node.textContent = message;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { node.className = "ui-toast"; }, 2800);
  }

  function busy(button, isBusy, label) {
    if (!button) return;
    if (isBusy) {
      button.dataset.original = button.innerHTML;
      button.disabled = true;
      button.innerHTML = label || "处理中…";
    } else {
      button.disabled = false;
      if (button.dataset.original) button.innerHTML = button.dataset.original;
    }
  }

  const role = () => localStorage.getItem("craftmesh-role") || "admin";
  const setRole = (value) => { localStorage.setItem("craftmesh-role", value); };

  function kv(rows) {
    return rows.map(([k, v]) => `<div class="kv-row"><span>${escapeHtml(k)}</span><strong>${v}</strong></div>`).join("");
  }

  return { $, $$, api, ApiError, escapeHtml, money, pct, time, tag, statusTag, toast, busy, role, setRole, kv };
})();
