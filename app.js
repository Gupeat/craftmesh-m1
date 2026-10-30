(() => {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  const SOURCE_LABELS = { original: "原创", licensed: "授权", "public-domain": "公版" };
  const VERDICT_META = {
    pass: { label: "可制造", tag: "通过", cls: "green" },
    review: { label: "需工艺复核", tag: "复核", cls: "amber" },
    blocked: { label: "不可制造", tag: "阻断", cls: "red" }
  };
  const STATUS_FALLBACK = {
    draft: "草稿", submitted: "待评审", accepted: "已接单", rework: "退回修改",
    in_production: "生产中", qc: "质检中", shipped: "已发货", settled: "已结算", cancelled: "已取消"
  };

  const state = {
    boot: null, health: null, patterns: [], orders: [],
    stats: { orders: 0, open: 0, passed: 0, audit: 0, byStatus: {}, recentAudit: [] },
    role: "designer", patternId: "moon-gate", process: "casting", material: "brass",
    finish: "polished", mode: "copy", quantity: 10, params: {}, check: null,
    selectedOrder: null, view: "dashboard", filterStatus: "", search: "", busy: false, toastTimer: null
  };

  class ApiError extends Error {
    constructor(message, status, payload) {
      super(message);
      this.name = "ApiError";
      this.status = status;
      this.payload = payload;
    }
  }

  function esc(value) {
    const map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
    return String(value === undefined || value === null ? "" : value).replace(/[&<>"']/g, (ch) => map[ch]);
  }

  function formatMoney(cents) {
    const value = Number(cents || 0) / 100;
    return "$" + value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function formatTime(value, short) {
    if (!value) return "—";
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return String(value);
    if (short) return d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
    return d.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
  }

  function processLabel(id) { return state.boot && state.boot.processes ? state.boot.processes[id] || id || "—" : id || "—"; }
  function materialLabel(id) { return state.boot && state.boot.materials ? state.boot.materials[id] || id || "—" : id || "—"; }
  function finishLabel(id) { return state.boot && state.boot.finishes ? state.boot.finishes[id] || id || "—" : id || "—"; }
  function modeLabel(id) { return state.boot && state.boot.modes ? state.boot.modes[id] || id || "—" : id || "—"; }
  function statusLabel(id) { return (state.boot && state.boot.statuses && state.boot.statuses[id]) || STATUS_FALLBACK[id] || id || "—"; }
  function roleName(id) { return state.boot && state.boot.actors && state.boot.actors[id] ? state.boot.actors[id].name : id; }

  function currentPattern() {
    return state.patterns.find((p) => p.id === state.patternId) || state.patterns[0] || null;
  }

  function patternSvg(pattern) {
    if (!pattern) return "";
    const palette = pattern.palette || ["#2a2118", "#d8b36a", "#f0d39a"];
    const bg = palette[0], mid = palette[1], light = palette[2];
    if (pattern.motif === "wave") {
      return '<svg viewBox="0 0 120 46" preserveAspectRatio="none" aria-hidden="true"><rect width="120" height="46" fill="' + bg + '"/><path d="M-8 32 Q 0 19 8 32 T 24 32 T 40 32 T 56 32 T 72 32 T 88 32 T 104 32 T 120 32 T 136 32" fill="none" stroke="' + mid + '" stroke-width="2"/><path d="M-8 38 Q 0 25 8 38 T 24 38 T 40 38 T 56 38 T 72 38 T 88 38 T 104 38 T 120 38 T 136 38" fill="none" stroke="' + light + '" stroke-width="1" opacity=".65"/><circle cx="91" cy="14" r="5" fill="none" stroke="' + light + '" stroke-width="1" opacity=".6"/></svg>';
    }
    if (pattern.motif === "scroll") {
      return '<svg viewBox="0 0 120 46" preserveAspectRatio="none" aria-hidden="true"><rect width="120" height="46" fill="' + bg + '"/><path d="M12 34c0-9 9-13 15-8 5 4 2 11-4 10-5-1-5-8 1-10 9-3 17 3 17 12" fill="none" stroke="' + mid + '" stroke-width="2"/><path d="M69 15c8-4 15 2 13 9-1 5-8 7-11 2-2-4 2-7 5-6 7 2 8 13 1 17-6 3-12-2-11-7" fill="none" stroke="' + light + '" stroke-width="1.5" opacity=".8"/><path d="M0 37h120" stroke="' + mid + '" stroke-width=".7" opacity=".45"/></svg>';
    }
    return '<svg viewBox="0 0 120 46" preserveAspectRatio="none" aria-hidden="true"><rect width="120" height="46" fill="' + bg + '"/><path d="M35 43V27a25 25 0 0 1 50 0v16" fill="none" stroke="' + mid + '" stroke-width="2"/><path d="M44 43V28a16 16 0 0 1 32 0v15" fill="none" stroke="' + light + '" stroke-width="1" opacity=".7"/><circle cx="60" cy="15" r="4" fill="' + light + '"/><path d="M0 41h120" stroke="' + mid + '" stroke-width=".7" opacity=".5"/></svg>';
  }

  async function api(path, options) {
    const opts = options || {};
    const headers = Object.assign({}, opts.headers || {});
    const init = { method: opts.method || "GET", headers: headers, cache: "no-store" };
    if (opts.body !== undefined) {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.body);
    }
    let response;
    try { response = await fetch(path, init); }
    catch (error) { throw new ApiError("无法连接本地 API，请确认 server.py 已启动。", 0, null); }
    let payload = null;
    try { payload = await response.json(); } catch (error) { payload = null; }
    if (!response.ok) {
      const errors = payload && payload.errors ? payload.errors.join("；") : "";
      const detail = errors || (payload && (payload.error || payload.detail)) || ("HTTP " + response.status);
      throw new ApiError(detail, response.status, payload);
    }
    return payload;
  }

  function toast(message, type) {
    const node = $("#toast");
    if (!node) return;
    window.clearTimeout(state.toastTimer);
    node.textContent = message;
    node.className = "toast is-visible" + (type === "error" ? " is-error" : type === "success" ? " is-success" : "");
    state.toastTimer = window.setTimeout(() => { node.className = "toast"; }, 4200);
  }

  function setApiOnline(online) {
    const badge = $("#apiBadge");
    const stateNode = $("#apiState");
    if (badge) {
      badge.classList.toggle("is-offline", !online);
      badge.innerHTML = '<span class="live-dot"></span><span>' + (online ? "API 在线" : "API 离线") + "</span>";
    }
    if (stateNode) {
      stateNode.textContent = online ? "在线" : "离线";
      stateNode.style.color = online ? "" : "var(--red)";
    }
  }

  function fillSelect(select, options, selected) {
    if (!select) return;
    const entries = Object.entries(options || {});
    select.innerHTML = entries.map((entry) => '<option value="' + esc(entry[0]) + '">' + esc(entry[1]) + "</option>").join("");
    if (selected && options && Object.prototype.hasOwnProperty.call(options, selected)) select.value = selected;
  }

  function renderRoles() {
    const select = $("#roleSelect");
    if (!select || !state.boot) return;
    select.innerHTML = Object.entries(state.boot.actors || {}).map((entry) => {
      const actor = entry[1];
      return '<option value="' + esc(entry[0]) + '">' + esc(actor.name) + " · " + esc(actor.title) + "</option>";
    }).join("");
    select.value = state.role;
    const reset = $("#resetButton");
    if (reset) {
      reset.disabled = state.role !== "admin";
      reset.title = state.role === "admin" ? "清空本地演示订单" : "仅管理员可重置数据";
    }
  }

  function renderPatternGrid() {
    const container = $("#patternGrid");
    if (!container) return;
    container.innerHTML = state.patterns.map((pattern) => {
      const selected = pattern.id === state.patternId;
      const source = SOURCE_LABELS[pattern.source] || pattern.source || "—";
      return '<button type="button" class="pattern-card ' + (selected ? "is-selected" : "") + '" data-pattern="' + esc(pattern.id) + '" aria-pressed="' + selected + '">' +
        '<div class="pattern-preview" style="background:' + esc((pattern.palette || [])[0] || "#2a2118") + '">' + patternSvg(pattern) + "</div>" +
        '<div class="pattern-name"><span>' + esc(pattern.name) + '</span><span class="pattern-source">' + esc(source) + "</span></div>" +
        '<div class="mini-license">' + esc(pattern.licenseId || "—") + " · " + esc((pattern.useScope || []).join(" / ")) + "</div>" +
        "</button>";
    }).join("");
  }

  function renderSelectOptions() {
    if (!state.boot) return;
    fillSelect($("#processSelect"), state.boot.processes, state.process);
    fillSelect($("#materialSelect"), state.boot.materials, state.material);
    fillSelect($("#finishSelect"), state.boot.finishes, state.finish);
    fillSelect($("#modeSelect"), state.boot.modes, state.mode);
    const qty = $("#quantityInput");
    if (qty) qty.value = state.quantity;
  }

  function renderParams() {
    const container = $("#paramGrid");
    if (!container || !state.boot) return;
    container.innerHTML = (state.boot.params || []).map((def) => {
      const value = state.params[def.key] === undefined ? def.default : state.params[def.key];
      const unit = def.unit ? '<em>' + esc(def.unit) + "</em>" : "<em>—</em>";
      return '<div class="param-field"><label for="param-' + esc(def.key) + '"><span>' + esc(def.label) + "</span>" + unit + "</label>" +
        '<input id="param-' + esc(def.key) + '" data-param="' + esc(def.key) + '" type="number" step="' + esc(def.step || "any") + '" value="' + esc(value) + '">' +
        "</div>";
    }).join("");
  }

  function renderKpis() {
    const container = $("#kpiGrid");
    if (!container) return;
    const stats = state.stats || {};
    const total = Number(stats.orders || 0);
    const open = Number(stats.open || 0);
    const passed = Number(stats.passed || 0);
    const audit = Number(stats.audit || 0);
    const rate = total ? Math.round((passed / total) * 100) : 0;
    const cards = [
      ["订单总数", total, "SQLite 持久化", "i-orders"],
      ["在途订单", open, "草稿 / 评审 / 生产 / 质检", "i-layers"],
      ["判定通过率", rate + "%", passed + " 张订单判定通过", "i-check"],
      ["审计事件", audit, "创建与状态迁移全量记录", "i-db"]
    ];
    container.innerHTML = cards.map((card) => {
      return '<div class="kpi-card"><div class="kpi-top"><span>' + esc(card[0]) + '</span><span class="kpi-icon"><svg class="icon"><use href="#' + card[3] + '"></use></svg></span></div>' +
        '<div class="kpi-value">' + esc(card[1]) + '</div><div class="kpi-foot">' + esc(card[2]) + "</div></div>";
    }).join("");
  }

  function renderSidebarCounts() {
    const count = $("#navOrderCount");
    if (count) count.textContent = String((state.stats && state.stats.orders) || 0);
    const summary = $("#orderSummaryTag");
    if (summary) summary.textContent = String((state.stats && state.stats.orders) || 0) + " 单 · " + String((state.stats && state.stats.open) || 0) + " 在途";
  }

  function renderRecentOrders() {
    const container = $("#recentOrders");
    if (!container) return;
    const orders = state.orders.slice(0, 5);
    if (!orders.length) {
      container.innerHTML = '<div class="empty-list">还没有订单。运行一次检查，创建第一张草稿。</div>';
      return;
    }
    container.innerHTML = orders.map((order) => {
      const status = order.status || "draft";
      return '<button type="button" class="compact-row" data-order-id="' + esc(order.id) + '">' +
        '<div class="row-main"><div class="row-title"><span class="row-status ' + esc(status) + '">' + esc(statusLabel(status)) + "</span><span>" + esc((order.pattern || {}).name || "—") + "</span></div>" +
        '<div class="row-meta">' + esc(order.id) + " · " + esc(order.processLabel || processLabel(order.process)) + " · " + esc(formatTime(order.createdAt)) + "</div></div>" +
        '<div class="row-amount">' + esc(formatMoney((order.quote || {}).amountCents)) + "</div>" +
        '<svg class="icon" style="width:13px;height:13px;color:var(--muted-2)"><use href="#i-arrow"></use></svg></button>';
    }).join("");
  }

  function renderRecentAudit() {
    const container = $("#recentAudit");
    if (!container) return;
    const events = (state.stats && state.stats.recentAudit) || [];
    if (!events.length) {
      container.innerHTML = '<div class="empty-list">创建订单或迁移状态后，审计事件会出现在这里。</div>';
      return;
    }
    container.innerHTML = events.map((event) => {
      const cls = event.action === "created" ? "created" : event.action === "settle" ? "settled" : "";
      return '<div class="timeline-item ' + cls + '" data-order-id="' + esc(event.orderId || "") + '"><span class="timeline-dot"></span><div class="timeline-content">' +
        '<div class="timeline-title"><span>' + esc(event.label || event.action || "事件") + '</span><span class="timeline-time">' + esc(formatTime(event.at, true)) + "</span></div>" +
        '<div class="timeline-note">' + esc(event.actor || "—") + " · " + esc(event.orderId || "") + (event.note ? " · " + esc(event.note) : "") + "</div></div></div>";
    }).join("");
  }

  const ACCEPTANCE = [
    { id: "A01", item: "洁净机 README / 一条命令启动 / 至少四条可点流程", scope: "Demo / M1", state: "已演示", cls: "pass" },
    { id: "A02", item: "授权来源、使用范围字段校验 + 正反例", scope: "Demo / M1", state: "已演示", cls: "pass" },
    { id: "A03", item: "10 条可制造性规则，其中 3 条不可制造", scope: "Demo / M1", state: "已演示", cls: "pass" },
    { id: "A04", item: "C2M 订单生命周期、退款与争议状态", scope: "M2", state: "未开始", cls: "na" },
    { id: "A05", item: "两个行业组件按配置接入 + FDE 手册", scope: "M3", state: "未开始", cls: "na" },
    { id: "A06", item: "多语言站点 / SEO / 询盘进入 CRM 的 E2E", scope: "M3", state: "未开始", cls: "na" },
    { id: "A07", item: "文化 IP 管线、1 支样片与授权模板", scope: "M4", state: "未开始", cls: "na" },
    { id: "A08", item: "授权、规则、状态机、分账的单元测试，一条命令全绿", scope: "Demo / M1", state: "27/27", cls: "pass" },
    { id: "A09", item: "文档、命令、界面真实对应，不靠 PPT 演示", scope: "Demo / M1", state: "已交付", cls: "pass" },
    { id: "A10", item: "合成数据；不接真实客户 / 工厂；不主张独占传统文化", scope: "Demo / M1", state: "已声明", cls: "pass" }
  ];

  const TEST_GROUPS = [
    { group: "规则引擎", count: "10 条 + 3 硬约束", covers: "硬约束阻断、软约束复核、非法输入", result: "PASS" },
    { group: "授权校验", count: "4 条负例 + 1 条正例", covers: "来源、范围、编号、二创", result: "PASS" },
    { group: "订单快照", count: "2 条", covers: "授权与报价固化、硬约束拒绝", result: "PASS" },
    { group: "状态机", count: "4 条", covers: "全链路、越权、非法迁移、备注必填", result: "PASS" },
    { group: "HTTP API", count: "5 条", covers: "health / bootstrap / check / 生命周期", result: "PASS" },
    { group: "权限与重置", count: "2 条", covers: "角色 403、管理员 reset", result: "PASS" },
    { group: "静态白名单", count: "1 条", covers: "页面/JS 可访问，源码与 DB 返回 404", result: "PASS" },
    { group: "持久化", count: "1 条", covers: "临时 SQLite 关闭与清理", result: "PASS" }
  ];

  function renderVerdict() {
    const body = $("#verdictBody");
    const tag = $("#verdictTag");
    if (!body || !tag) return;
    const result = state.check;
    if (!result) {
      tag.className = "tag tag-muted";
      tag.textContent = "待运行";
      body.innerHTML = '<p class="empty-copy">运行检查后，这里会显示逐条规则结果、授权校验与报价。结果由 /api/check 返回，不是前端预置文案。</p>';
      return;
    }
    const verdict = (result.checks && result.checks.verdict) || "review";
    const meta = VERDICT_META[verdict] || VERDICT_META.review;
    const blocked = result.license && !result.license.ok;
    const label = blocked ? "授权阻断" : meta.label;
    const cls = blocked ? "red" : meta.cls;
    tag.className = "tag tag-" + cls;
    tag.textContent = blocked ? "授权失败" : meta.tag;
    const checks = (result.checks && result.checks.checks) || [];
    const counts = { pass: 0, fail: 0, na: 0 };
    checks.forEach((rule) => { counts[rule.status] = (counts[rule.status] || 0) + 1; });
    const errors = Array.from(new Set([].concat(result.errors || [], (result.license && result.license.errors) || [])));
    body.innerHTML = '<div class="verdict-hero"><div><div class="verdict-label ' + esc(verdict) + '">' + esc(label) + "</div>" +
      '<div class="verdict-sub">' + esc(processLabel(state.process)) + " · " + esc(materialLabel(state.material)) + " · " + esc(modeLabel(state.mode)) + " · " + esc(state.quantity) + " 件</div></div>" +
      '<div class="verdict-count">' + esc(counts.pass) + " pass<br>" + esc(counts.fail) + " fail</div></div>" +
      '<div class="rule-result-list">' + checks.map((rule) => {
        const status = rule.status === "pass" ? "pass" : rule.status === "fail" ? "fail" : "na";
        const value = status === "na" ? "不适用" : status === "pass" ? "通过" : "未通过";
        return '<div class="rule-result ' + status + '"><span class="rule-status"></span><span class="rule-result-name">' + esc(rule.name) +
          (rule.hard ? '<span class="hard-mark">HARD</span>' : "") + '</span><span class="rule-result-value">' + esc(value) + (rule.detail ? " · " + esc(rule.detail) : "") + "</span></div>";
      }).join("") + "</div>" +
      (errors.length ? '<div class="verdict-error">' + errors.map(esc).join("<br>") + "</div>" : "");
  }

  function renderLicense() {
    const container = $("#licensePanel");
    if (!container) return;
    const pattern = (state.check && state.check.pattern) || currentPattern();
    if (!pattern) {
      container.innerHTML = '<p class="empty-copy">选择纹样后显示授权字段。</p>';
      return;
    }
    const snapshot = state.check && state.check.license ? state.check.license.snapshot : null;
    const licenseResult = state.check && state.check.license ? state.check.license : null;
    const source = snapshot ? snapshot.source : pattern.source;
    const scope = snapshot ? snapshot.useScope : (pattern.useScope || []);
    const checkedAt = snapshot && snapshot.checkedAt ? formatTime(snapshot.checkedAt) : "运行检查后固化";
    const ok = !licenseResult || licenseResult.ok;
    container.innerHTML =
      '<div class="license-row"><span>纹样</span><strong>' + esc(pattern.name) + "</strong></div>" +
      '<div class="license-row"><span>来源</span><strong>' + esc(SOURCE_LABELS[source] || source) + "</strong></div>" +
      '<div class="license-row"><span>授权编号</span><strong>' + esc((snapshot && snapshot.licenseId) || pattern.licenseId || "—") + "</strong></div>" +
      '<div class="license-row"><span>来源编号</span><strong>' + esc((snapshot && snapshot.sourceId) || pattern.sourceId || "—") + "</strong></div>" +
      '<div class="license-row"><span>使用范围</span><strong>' + esc((scope || []).join(" / ") || "—") + "</strong></div>" +
      '<div class="license-row"><span>二创</span><strong>' + (((snapshot ? snapshot.derivativeAllowed : pattern.derivativeAllowed)) ? "允许" : "不允许") + "</strong></div>" +
      '<div class="license-state ' + (ok ? "ok" : "bad") + '"><span class="status-dot"></span>' + (ok ? "授权校验通过" : "授权校验失败") + " · 快照 " + esc(checkedAt) + "</div>";
  }

  function renderQuote() {
    const container = $("#quotePanel");
    if (!container) return;
    const quote = state.check && state.check.quote;
    if (!quote) {
      container.innerHTML = '<p class="empty-copy">运行检查后生成报价。报价按工艺单价乘以数量计算，平台费在创建订单时固化。</p>';
      return;
    }
    container.innerHTML =
      '<div class="quote-line"><span>工艺单价</span><strong>' + esc(formatMoney(quote.unitCents)) + "</strong></div>" +
      '<div class="quote-line"><span>数量</span><strong>' + esc(state.quantity) + "</strong></div>" +
      '<div class="quote-line"><span>小计</span><strong>' + esc(formatMoney(quote.amountCents)) + "</strong></div>" +
      '<div class="quote-line"><span>平台费（25%）</span><strong>-' + esc(formatMoney(quote.platformFeeCents)) + "</strong></div>" +
      '<div class="quote-line is-total"><span>工艺方应收</span><strong>' + esc(formatMoney(quote.netCents)) + "</strong></div>" +
      '<div class="quote-note">M1 参考报价，用于演示授权、判定和订单快照；不代表真实工厂结算价。</div>';
  }

  function updateCreateButton() {
    const button = $("#createButton");
    const hint = $("#createHint");
    if (!button) return;
    const roleCanCreate = state.role === "designer" || state.role === "admin";
    const ready = Boolean(state.check && state.check.ok && roleCanCreate);
    button.disabled = !ready || state.busy;
    if (hint) {
      if (!roleCanCreate) hint.textContent = "当前角色不能创建订单";
      else if (!state.check) hint.textContent = "先运行检查";
      else if (!state.check.ok) hint.textContent = "检查未通过，不能创建";
      else if (state.check.checks && state.check.checks.verdict === "review") hint.textContent = "软约束未通过，将标记需复核";
      else hint.textContent = "将保存授权 / 参数 / 报价快照";
    }
  }

  function invalidateCheck() {
    state.check = null;
    renderVerdict();
    renderLicense();
    renderQuote();
    updateCreateButton();
    const checkState = $("#checkState");
    if (checkState) {
      checkState.className = "check-state";
      checkState.textContent = "参数已修改，请重新运行检查。";
    }
  }

  function currentPayload() {
    return {
      patternId: state.patternId,
      process: state.process,
      material: state.material,
      finish: state.finish,
      quantity: Number(state.quantity) || 1,
      params: state.params,
      mode: state.mode
    };
  }

  async function runCheck(showToast) {
    if (state.busy) return;
    state.busy = true;
    updateCreateButton();
    const button = $("#checkButton");
    const checkState = $("#checkState");
    if (button) button.disabled = true;
    if (checkState) {
      checkState.className = "check-state is-busy";
      checkState.textContent = "POST /api/check · 正在服务端判定…";
    }
    try {
      const data = await api("/api/check", { method: "POST", body: currentPayload() });
      state.check = data.result;
      renderVerdict();
      renderLicense();
      renderQuote();
      updateCreateButton();
      const verdict = (data.result && data.result.checks && data.result.checks.verdict) || "review";
      if (checkState) {
        checkState.className = "check-state" + ((data.result && data.result.ok) ? "" : " is-error");
        checkState.textContent = (data.result && data.result.ok)
          ? "检查完成 · " + (verdict === "pass" ? "可制造" : "需工艺复核") + " · 可创建订单草稿"
          : "检查完成 · 存在阻断项，不能创建订单";
      }
      if (showToast) toast((data.result && data.result.ok) ? "服务端检查通过。" : "服务端返回阻断项，请查看判定摘要。", (data.result && data.result.ok) ? "success" : "error");
    } catch (error) {
      state.check = null;
      renderVerdict();
      renderLicense();
      renderQuote();
      updateCreateButton();
      if (checkState) {
        checkState.className = "check-state is-error";
        checkState.textContent = "检查失败：" + error.message;
      }
      toast("检查失败：" + error.message, "error");
    } finally {
      state.busy = false;
      if (button) button.disabled = false;
      updateCreateButton();
    }
  }

  async function createOrder() {
    if (!state.check || !state.check.ok) {
      toast("先运行一次通过的检查。", "error");
      return;
    }
    if (state.role !== "designer" && state.role !== "admin") {
      toast("当前角色不能创建订单，请切换到设计或管理员。", "error");
      return;
    }
    const button = $("#createButton");
    if (button) button.disabled = true;
    try {
      const data = await api("/api/orders", { method: "POST", body: Object.assign({}, currentPayload(), { role: state.role }) });
      state.selectedOrder = data.order;
      await refreshData(true);
      const fresh = state.orders.find((order) => order.id === data.order.id);
      if (fresh) state.selectedOrder = fresh;
      renderOrderDetail();
      renderOrdersTable();
      navigate("orders", true, data.order.id);
      toast("订单 " + data.order.id + " 已创建，授权 / 参数 / 报价已固化。", "success");
      window.setTimeout(() => {
        const panel = $("#orderDetailPanel");
        if (panel) panel.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 80);
    } catch (error) {
      toast("创建失败：" + error.message, "error");
    } finally {
      if (button) button.disabled = !(state.check && state.check.ok);
    }
  }

  function filteredOrders() {
    const q = state.search.trim().toLowerCase();
    return state.orders.filter((order) => {
      if (state.filterStatus && order.status !== state.filterStatus) return false;
      if (!q) return true;
      const haystack = [order.id, order.pattern ? order.pattern.name : "", order.processLabel, order.materialLabel].filter(Boolean).join(" ").toLowerCase();
      return haystack.indexOf(q) >= 0;
    });
  }

  function renderOrdersTable() {
    const container = $("#ordersTable");
    if (!container) return;
    const rows = filteredOrders();
    if (!rows.length) {
      container.innerHTML = '<div class="empty-list">没有匹配的订单。修改筛选，或先在工作台创建一张草稿。</div>';
      return;
    }
    container.innerHTML = '<table class="data-table"><thead><tr><th>订单</th><th>纹样 / 工艺</th><th>数量</th><th>报价</th><th>状态</th><th>创建时间</th><th></th></tr></thead><tbody>' +
      rows.map((order) => {
        const status = order.status || "draft";
        return "<tr><td><button class=\"row-button mono\" data-order-id=\"" + esc(order.id) + "\">" + esc(order.id) + "</button></td>" +
          "<td>" + esc((order.pattern || {}).name || "—") + '<span class="muted"> · ' + esc(order.processLabel || "—") + "</span></td>" +
          '<td class="mono">' + esc(order.quantity) + "</td>" +
          '<td class="mono">' + esc(formatMoney((order.quote || {}).amountCents)) + "</td>" +
          '<td><span class="row-status ' + esc(status) + '">' + esc(statusLabel(status)) + "</span></td>" +
          '<td class="muted mono">' + esc(formatTime(order.createdAt)) + "</td>" +
          '<td><button class="row-button" data-order-id="' + esc(order.id) + '">查看 →</button></td></tr>';
      }).join("") + "</tbody></table>";
  }

  function renderRules() {
    const container = $("#rulesTable");
    if (!container || !state.boot) return;
    const rules = state.boot.rules || [];
    container.innerHTML = '<table class="data-table"><thead><tr><th>规则</th><th>适用工艺</th><th>条件</th><th>类型</th><th>实现</th></tr></thead><tbody>' +
      rules.map((rule) => {
        return "<tr><td><span class=\"rule-id\">" + esc(rule.id) + '</span><span class="rule-name">' + esc(rule.name) + "</span></td>" +
          '<td class="muted">' + esc((rule.processes || []).map(processLabel).join(" / ")) + "</td>" +
          "<td>" + esc(rule.condition) + "</td>" +
          "<td>" + (rule.hard ? '<span class="hard-badge">HARD</span>' : '<span class="tag tag-muted">SOFT</span>') + "</td>" +
          '<td><span class="status-pill pass"><span class="status-dot"></span>可执行</span></td></tr>';
      }).join("") + "</tbody></table>";
  }

  function renderLicenseTable() {
    const container = $("#licenseTable");
    if (!container) return;
    container.innerHTML = state.patterns.map((pattern) => {
      return '<div class="ledger-card"><div class="ledger-title"><strong>' + esc(pattern.name) + "</strong><span>" + esc(SOURCE_LABELS[pattern.source] || pattern.source) + "</span></div>" +
        '<div class="ledger-fields">' +
        '<div class="ledger-field"><span>授权编号</span><b>' + esc(pattern.licenseId || "—") + "</b></div>" +
        '<div class="ledger-field"><span>来源编号</span><b>' + esc(pattern.sourceId || "—") + "</b></div>" +
        '<div class="ledger-field"><span>使用范围</span><b>' + esc((pattern.useScope || []).join(" / ")) + "</b></div>" +
        '<div class="ledger-field"><span>二创</span><b>' + (pattern.derivativeAllowed ? "允许" : "不允许") + "</b></div>" +
        "</div></div>";
    }).join("");
  }

  function renderAcceptance() {
    const container = $("#acceptanceTable");
    if (!container) return;
    container.innerHTML = '<table class="data-table"><thead><tr><th>编号</th><th>验收项</th><th>阶段</th><th>当前状态</th></tr></thead><tbody>' +
      ACCEPTANCE.map((item) => {
        return '<tr><td class="mono">' + esc(item.id) + "</td><td>" + esc(item.item) + "</td>" +
          '<td class="muted">' + esc(item.scope) + "</td>" +
          '<td><span class="status-pill ' + esc(item.cls) + '"><span class="status-dot"></span>' + esc(item.state) + "</span></td></tr>";
      }).join("") + "</tbody></table>";
  }

  function renderTestCases() {
    const container = $("#testCasesTable");
    if (!container) return;
    container.innerHTML = '<table class="data-table"><thead><tr><th>测试组</th><th>覆盖</th><th>用例</th><th>结果</th></tr></thead><tbody>' +
      TEST_GROUPS.map((item) => {
        return "<tr><td>" + esc(item.group) + '</td><td class="muted">' + esc(item.covers) + '</td><td class="mono">' + esc(item.count) + "</td>" +
          '<td><span class="status-pill pass"><span class="status-dot"></span>' + esc(item.result) + "</span></td></tr>";
      }).join("") + "</tbody></table>";
  }

  async function refreshData(keepCheck) {
    try {
      const data = await api("/api/bootstrap");
      state.boot = Object.assign({}, state.boot, data);
      state.orders = data.orders || [];
      state.stats = data.stats || state.stats;
      state.patterns = data.patterns || state.patterns;
      renderKpis();
      renderSidebarCounts();
      renderRecentOrders();
      renderRecentAudit();
      renderOrdersTable();
      renderLicenseTable();
      renderRules();
      renderRoles();
      if (state.selectedOrder) {
        const fresh = state.orders.find((order) => order.id === state.selectedOrder.id);
        if (fresh) state.selectedOrder = fresh;
      }
      renderOrderDetail();
      if (!keepCheck) renderLicense();
      setApiOnline(true);
    } catch (error) {
      setApiOnline(false);
      toast("刷新失败：" + error.message, "error");
    }
  }

  async function selectOrder(orderId) {
    if (!orderId) return;
    try {
      const data = await api("/api/orders/" + encodeURIComponent(orderId));
      state.selectedOrder = data.order;
      renderOrderDetail();
      renderOrdersTable();
      navigate("orders", true, orderId);
      window.setTimeout(() => {
        const panel = $("#orderDetailPanel");
        if (panel) panel.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 80);
    } catch (error) {
      toast("加载订单失败：" + error.message, "error");
    }
  }

  function renderOrderDetail() {
    const container = $("#orderDetail");
    if (!container) return;
    const order = state.selectedOrder;
    if (!order) {
      container.innerHTML = '<div class="detail-placeholder">从上方订单列表选择一张订单，查看状态机、授权快照与审计记录。</div>';
      return;
    }
    const path = ["draft", "submitted", "accepted", "in_production", "qc", "shipped", "settled"];
    let currentIndex = path.indexOf(order.status);
    if (currentIndex < 0 && order.status === "rework") currentIndex = 1;
    if (currentIndex < 0) currentIndex = 0;
    const stepper = path.map((status, index) => {
      let cls = "";
      if (index < currentIndex) cls = "is-done";
      if (index === currentIndex) cls = order.status === "cancelled" ? "is-cancelled" : "is-current";
      return '<div class="step ' + cls + '"><span class="step-dot"></span><span>' + esc(statusLabel(status)) + "</span></div>";
    }).join("");
    const transitions = (state.boot && state.boot.transitions ? state.boot.transitions : []).filter((transition) => {
      return (transition.from || []).indexOf(order.status) >= 0;
    });
    const allowedTransitions = transitions.filter((transition) => (transition.roles || []).indexOf(state.role) >= 0);
    const actionButtons = transitions.map((transition) => {
      const allowed = allowedTransitions.indexOf(transition) >= 0;
      const noteHint = transition.action === "request_rework" || transition.action === "reject_qc" ? "（需备注）" : "";
      return '<button type="button" class="btn btn-ghost" data-transition="' + esc(transition.action) + '"' +
        (allowed ? "" : ' disabled title="当前角色无权执行"') + ">" + esc(transition.label) + esc(noteHint) + "</button>";
    }).join("");
    let actionText = actionButtons || '<span class="action-hint">当前状态下没有可执行动作。</span>';
    if (transitions.length && !allowedTransitions.length) {
      actionText += '<span class="action-hint">当前角色「' + esc(roleName(state.role)) + '」不能执行这里的动作；切换右上角角色后再试。</span>';
    }
    const checkRows = (order.checks || []).map((rule) => {
      const status = rule.status === "pass" ? "pass" : rule.status === "fail" ? "fail" : "na";
      return '<div class="rule-result ' + status + '"><span class="rule-status"></span><span class="rule-result-name">' + esc(rule.name) +
        (rule.hard ? '<span class="hard-mark">HARD</span>' : "") + '</span><span class="rule-result-value">' +
        (status === "na" ? "不适用" : status === "pass" ? "通过" : "未通过") + (rule.detail ? " · " + esc(rule.detail) : "") + "</span></div>";
    }).join("");
    const auditRows = (order.audit || []).map((event) => {
      const cls = event.action === "created" ? "created" : event.action === "settle" ? "settled" : (event.action === "request_rework" || event.action === "reject_qc") ? "rework" : "";
      return '<div class="audit-row ' + cls + '"><span class="audit-dot"></span><div class="audit-main"><div class="audit-head">' +
        "<span>" + esc(event.label || event.action) + '</span><span class="audit-time">' + esc(formatTime(event.at, true)) + "</span></div>" +
        '<div class="audit-meta">' + esc(event.actor || "—") + " · " + esc(event.from || "新建") + " → " + esc(event.to || "—") +
        (event.note ? " · " + esc(event.note) : "") + "</div></div></div>";
    }).join("");
    const license = order.license || {};
    container.innerHTML =
      '<div class="order-detail-head"><div><div class="panel-kicker">ORDER DETAIL · v' + esc(order.version || 1) + "</div><h2>" + esc(order.id) + "</h2>" +
      '<div class="order-detail-sub">' + esc((order.pattern || {}).name || "—") + " · " + esc(order.processLabel || "—") + " · " + esc(processLabel(order.process)) + " · " + esc(order.quantity) + " 件</div></div>" +
      '<div class="detail-actions"><span class="row-status ' + esc(order.status) + '">' + esc(statusLabel(order.status)) + '</span><span class="tag tag-muted">' + esc(formatMoney((order.quote || {}).amountCents)) + "</span></div></div>" +
      '<div class="detail-grid"><div><div class="detail-section"><div class="detail-section-title">状态机 <span>每次迁移递增版本并追加审计</span></div>' +
      '<div class="stepper">' + stepper + "</div>" +
      '<div class="meta-grid">' +
      '<div class="meta-cell"><span>纹样</span><strong>' + esc((order.pattern || {}).name || "—") + "</strong></div>" +
      '<div class="meta-cell"><span>工艺 / 材料</span><strong>' + esc(order.processLabel || "—") + " / " + esc(order.materialLabel || "—") + "</strong></div>" +
      '<div class="meta-cell"><span>表面 / 模式</span><strong>' + esc(order.finishLabel || "—") + " / " + esc(order.modeLabel || "—") + "</strong></div>" +
      '<div class="meta-cell"><span>数量</span><strong>' + esc(order.quantity) + "</strong></div>" +
      '<div class="meta-cell"><span>判定</span><strong>' + esc(order.verdict === "pass" ? "可制造" : order.verdict === "review" ? "需复核" : "阻断") + "</strong></div>" +
      '<div class="meta-cell"><span>创建</span><strong>' + esc(formatTime(order.createdAt)) + "</strong></div></div></div>" +
      '<div class="detail-section"><div class="detail-section-title">规则证据 <span>' + esc((order.checks || []).length) + ' 条</span></div><div class="rule-result-list">' + (checkRows || '<p class="empty-copy">无规则记录。</p>') + "</div></div>" +
      '<div class="detail-section"><div class="detail-section-title">可执行动作 <span>当前角色：' + esc(roleName(state.role)) + '</span></div><div class="detail-actions" style="justify-content:flex-start">' + actionText + "</div>" +
      '<label class="note-field"><span>备注（退回 / 质检退回时必填）</span><textarea class="note-input" id="transitionNote" placeholder="例如：纹理方向与工艺单不一致，请调整后重提。"></textarea></label><div class="action-message" id="actionMessage"></div></div></div>' +
      '<div><div class="detail-section"><div class="detail-section-title">授权快照 <span>随单固化</span></div><div class="license-panel">' +
      '<div class="license-row"><span>来源</span><strong>' + esc(SOURCE_LABELS[license.source] || license.source || "—") + "</strong></div>" +
      '<div class="license-row"><span>授权编号</span><strong>' + esc(license.licenseId || "—") + "</strong></div>" +
      '<div class="license-row"><span>来源编号</span><strong>' + esc(license.sourceId || "—") + "</strong></div>" +
      '<div class="license-row"><span>使用范围</span><strong>' + esc((license.useScope || []).join(" / ") || "—") + "</strong></div>" +
      '<div class="license-state ok"><span class="status-dot"></span>创建时已校验</div></div></div>' +
      '<div class="detail-section"><div class="detail-section-title">报价快照 <span>USD</span></div><div class="quote-body">' +
      '<div class="quote-line"><span>小计</span><strong>' + esc(formatMoney((order.quote || {}).amountCents)) + "</strong></div>" +
      '<div class="quote-line"><span>平台费</span><strong>-' + esc(formatMoney((order.quote || {}).platformFeeCents)) + "</strong></div>" +
      '<div class="quote-line is-total"><span>应收</span><strong>' + esc(formatMoney((order.quote || {}).netCents)) + "</strong></div></div></div>" +
      '<div class="detail-section"><div class="detail-section-title">审计轨迹 <span>' + esc((order.audit || []).length) + ' 条</span></div><div class="audit-list">' + (auditRows || '<p class="empty-copy">无审计记录。</p>') + "</div></div></div></div>";
  }

  async function transitionOrder(action) {
    const order = state.selectedOrder;
    if (!order) return;
    const noteInput = $("#transitionNote");
    const note = noteInput ? noteInput.value.trim() : "";
    const message = $("#actionMessage");
    const buttons = $$("[data-transition]", $("#orderDetail"));
    buttons.forEach((button) => { button.disabled = true; });
    try {
      await api("/api/orders/" + encodeURIComponent(order.id) + "/transition", { method: "POST", body: { action: action, role: state.role, note: note } });
      await refreshData(true);
      const fresh = await api("/api/orders/" + encodeURIComponent(order.id));
      state.selectedOrder = fresh.order;
      renderOrderDetail();
      toast("状态已迁移：" + statusLabel(fresh.order.status), "success");
    } catch (error) {
      if (message) {
        message.className = "action-message is-error";
        message.textContent = error.message;
      }
      toast("迁移失败：" + error.message, "error");
      buttons.forEach((button) => { button.disabled = false; });
    }
  }

  function navigate(view, updateHash, orderId) {
    const allowed = ["dashboard", "orders", "rules", "architecture", "tests"];
    if (allowed.indexOf(view) < 0) view = "dashboard";
    state.view = view;
    $$(".view").forEach((node) => node.classList.toggle("is-active", node.id === "view-" + view));
    $$(".nav-item").forEach((node) => node.classList.toggle("is-active", node.dataset.view === view));
    const target = $("#view-" + view);
    const crumb = $("#crumbCurrent");
    if (crumb && target) crumb.textContent = target.dataset.title || view;
    document.title = "CraftMesh · " + (target && target.dataset.title ? target.dataset.title : "M1");
    if (updateHash !== false) {
      const next = "#/" + view + (orderId ? "/" + encodeURIComponent(orderId) : "");
      if (location.hash !== next) history.replaceState(null, "", next);
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function loadUnmanufacturable() {
    state.patternId = "moon-gate";
    state.process = "casting";
    state.material = "brass";
    state.finish = "polished";
    state.mode = "copy";
    state.quantity = 10;
    state.params = Object.assign({}, state.params, { wallThickness: 0.5, undercutAngle: 3 });
    renderPatternGrid();
    renderSelectOptions();
    renderParams();
    invalidateCheck();
    toast("已载入薄壁样例：壁厚 0.5 mm，低于 1.2 mm 硬约束。", "info");
    runCheck(true);
  }

  function resetParams() {
    if (!state.boot) return;
    state.params = {};
    (state.boot.params || []).forEach((def) => { state.params[def.key] = def.default; });
    renderParams();
    invalidateCheck();
    toast("已恢复默认工艺参数。", "info");
  }

  async function resetDemo() {
    if (state.role !== "admin") {
      toast("仅管理员可重置演示数据。请切换右上角角色。", "error");
      return;
    }
    try {
      await api("/api/demo/reset", { method: "POST", body: { role: state.role } });
      state.selectedOrder = null;
      state.check = null;
      await refreshData();
      renderVerdict();
      renderLicense();
      renderQuote();
      updateCreateButton();
      renderOrderDetail();
      toast("演示数据已重置。", "success");
    } catch (error) {
      toast("重置失败：" + error.message, "error");
    }
  }

  function buildStatusFilter() {
    const select = $("#statusFilter");
    if (!select || !state.boot) return;
    const options = { "": "全部状态" };
    Object.keys(state.boot.statuses || {}).forEach((key) => { options[key] = state.boot.statuses[key]; });
    fillSelect(select, options, state.filterStatus);
  }

  function bindEvents() {
    $$(".nav-item").forEach((node) => node.addEventListener("click", () => navigate(node.dataset.view)));
    $$("[data-view-jump]").forEach((node) => node.addEventListener("click", () => navigate(node.dataset.viewJump)));
    $$("[data-action='load-unmanufacturable']").forEach((node) => node.addEventListener("click", loadUnmanufacturable));

    const patternGrid = $("#patternGrid");
    if (patternGrid) patternGrid.addEventListener("click", (event) => {
      const card = event.target.closest("[data-pattern]");
      if (!card) return;
      state.patternId = card.dataset.pattern;
      renderPatternGrid();
      invalidateCheck();
    });

    const paramGrid = $("#paramGrid");
    if (paramGrid) paramGrid.addEventListener("input", (event) => {
      const input = event.target.closest("[data-param]");
      if (!input) return;
      const value = Number(input.value);
      state.params[input.dataset.param] = Number.isFinite(value) ? value : 0;
      invalidateCheck();
    });

    const selectMap = { processSelect: "process", materialSelect: "material", finishSelect: "finish", modeSelect: "mode" };
    Object.keys(selectMap).forEach((id) => {
      const node = $("#" + id);
      if (node) node.addEventListener("change", (event) => {
        state[selectMap[id]] = event.target.value;
        invalidateCheck();
      });
    });

    const qty = $("#quantityInput");
    if (qty) qty.addEventListener("input", (event) => {
      state.quantity = Number(event.target.value) || 1;
      invalidateCheck();
    });

    const checkButton = $("#checkButton");
    if (checkButton) checkButton.addEventListener("click", () => runCheck(true));
    const createButton = $("#createButton");
    if (createButton) createButton.addEventListener("click", createOrder);
    const resetParamsButton = $("#resetParamsButton");
    if (resetParamsButton) resetParamsButton.addEventListener("click", resetParams);
    const refreshButton = $("#refreshButton");
    if (refreshButton) refreshButton.addEventListener("click", () => refreshData());
    const refreshOrdersButton = $("#refreshOrdersButton");
    if (refreshOrdersButton) refreshOrdersButton.addEventListener("click", () => refreshData());
    const resetButton = $("#resetButton");
    if (resetButton) resetButton.addEventListener("click", resetDemo);

    const roleSelect = $("#roleSelect");
    if (roleSelect) roleSelect.addEventListener("change", (event) => {
      state.role = event.target.value;
      renderRoles();
      renderOrderDetail();
      updateCreateButton();
    });

    const statusFilter = $("#statusFilter");
    if (statusFilter) statusFilter.addEventListener("change", (event) => {
      state.filterStatus = event.target.value;
      renderOrdersTable();
    });
    const search = $("#orderSearch");
    if (search) search.addEventListener("input", (event) => {
      state.search = event.target.value;
      renderOrdersTable();
    });

    const ordersTable = $("#ordersTable");
    if (ordersTable) ordersTable.addEventListener("click", (event) => {
      const button = event.target.closest("[data-order-id]");
      if (button) selectOrder(button.dataset.orderId);
    });
    const recentOrders = $("#recentOrders");
    if (recentOrders) recentOrders.addEventListener("click", (event) => {
      const button = event.target.closest("[data-order-id]");
      if (button) selectOrder(button.dataset.orderId);
    });
    const recentAudit = $("#recentAudit");
    if (recentAudit) recentAudit.addEventListener("click", (event) => {
      const row = event.target.closest("[data-order-id]");
      if (row && row.dataset.orderId) selectOrder(row.dataset.orderId);
    });

    const detail = $("#orderDetail");
    if (detail) detail.addEventListener("click", (event) => {
      const button = event.target.closest("[data-transition]");
      if (button) transitionOrder(button.dataset.transition);
    });

    const menuButton = $("#menuButton");
    if (menuButton) menuButton.addEventListener("click", () => {
      const sidebar = $(".sidebar");
      if (sidebar) sidebar.classList.toggle("is-open");
    });

    const toastNode = $("#toast");
    if (toastNode) toastNode.addEventListener("click", () => { toastNode.className = "toast"; });

    window.addEventListener("hashchange", () => {
      const parts = location.hash.replace(/^#\//, "").split("/").filter(Boolean);
      const view = parts[0] || "dashboard";
      if (view === "orders" && parts[1]) {
        selectOrder(decodeURIComponent(parts[1]));
      } else if (view !== state.view) {
        navigate(view, false);
      }
    });
  }

  async function boot() {
    bindEvents();
    try {
      const results = await Promise.all([
        api("/api/health").catch(() => null),
        api("/api/bootstrap")
      ]);
      const health = results[0];
      const data = results[1];
      state.health = health;
      state.boot = data;
      state.patterns = data.patterns || [];
      state.orders = data.orders || [];
      state.stats = data.stats || state.stats;
      state.params = {};
      (data.params || []).forEach((def) => { state.params[def.key] = def.default; });
      if (state.patterns.length) state.patternId = state.patterns[0].id;
      const processKeys = Object.keys(data.processes || {});
      if (processKeys.length) state.process = processKeys[0];
      const materialKeys = Object.keys(data.materials || {});
      if (materialKeys.length) state.material = materialKeys[0];
      const finishKeys = Object.keys(data.finishes || {});
      if (finishKeys.length) state.finish = finishKeys[0];
      const modeKeys = Object.keys(data.modes || {});
      if (modeKeys.length) state.mode = modeKeys[0];
      renderRoles();
      renderPatternGrid();
      renderSelectOptions();
      renderParams();
      renderKpis();
      renderSidebarCounts();
      renderRecentOrders();
      renderRecentAudit();
      renderOrdersTable();
      renderRules();
      renderLicenseTable();
      renderAcceptance();
      renderTestCases();
      renderOrderDetail();
      renderVerdict();
      renderLicense();
      renderQuote();
      updateCreateButton();
      buildStatusFilter();
      const apiVersion = $("#apiVersion");
      if (apiVersion) apiVersion.textContent = "API " + (data.version || "M1.0");
      setApiOnline(true);
      const hashParts = location.hash.replace(/^#\//, "").split("/").filter(Boolean);
      const hashView = hashParts[0] || "dashboard";
      if (hashView === "orders" && hashParts[1]) {
        await selectOrder(decodeURIComponent(hashParts[1]));
      } else {
        navigate(hashView, false);
      }
      await runCheck(false);
    } catch (error) {
      setApiOnline(false);
      toast("无法加载 API：" + error.message, "error");
      const body = $("#verdictBody");
      if (body) body.innerHTML = '<p class="empty-copy">API 未连接。请先运行 python server.py，再刷新页面。</p>';
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
