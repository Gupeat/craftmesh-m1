/* 扩展模块统一外壳：左侧导航 + 顶栏。页面只负责自己的正文。 */
(() => {
  const NAV = [
    { key: "home", label: "工作台（M1）", href: "/", icon: "grid" },
    { key: "m2", label: "预售与工厂派单", href: "/pages/m2.html", icon: "orders", kicker: "M2" },
    { key: "ai", label: "企业 AI 服务层", href: "/pages/ai.html", icon: "db", kicker: "B" },
    { key: "ip", label: "文化 IP 短剧管线", href: "/pages/ip.html", icon: "layers", kicker: "C" },
    { key: "evidence", label: "验收驾驶舱", href: "/pages/evidence.html", icon: "check" },
  ];
  const META = {
    m2: { crumb: "M2 预售与派单", title: "C2M 预售与制造协同" },
    ai: { crumb: "B 企业 AI 服务层", title: "知识库 · 智能体 · 自动化工作流" },
    ip: { crumb: "C 文化 IP 短剧管线", title: "剧本到字幕的可运行管线" },
    evidence: { crumb: "验收驾驶舱", title: "一键复跑的证据面板" },
  };
  const ROLES = [
    ["designer", "设计师"], ["ops", "生产运营"], ["workshop", "工坊"], ["finance", "财务"],
    ["buyer", "买家 / 支持者"], ["admin", "管理员"],
  ];

  const page = document.body.dataset.page || "m2";
  const meta = META[page] || META.m2;

  const SPRITE_SVG = '<svg xmlns="http://www.w3.org/2000/svg" class="svg-sprite" aria-hidden="true">'
    + '<symbol id="i-grid" viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></symbol>'
    + '<symbol id="i-orders" viewBox="0 0 24 24"><path d="M7 3h10l3 4v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7l3-4Z"/><path d="M4 7h16M9 12h6M9 16h6"/></symbol>'
    + '<symbol id="i-shield" viewBox="0 0 24 24"><path d="M12 3 4.5 6v6c0 4.6 3.2 8 7.5 9 4.3-1 7.5-4.4 7.5-9V6L12 3Z"/><path d="m9 12 2 2 4-4"/></symbol>'
    + '<symbol id="i-layers" viewBox="0 0 24 24"><path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="m3 12 9 5 9-5M3 16l9 5 9-5"/></symbol>'
    + '<symbol id="i-check" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="m8 12 2.5 2.5L16 9"/></symbol>'
    + '<symbol id="i-refresh" viewBox="0 0 24 24"><path d="M20 11a8 8 0 1 0-2.3 6.3M20 5v6h-6"/></symbol>'
    + '<symbol id="i-plus" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></symbol>'
    + '<symbol id="i-arrow" viewBox="0 0 24 24"><path d="M5 12h14M13 6l6 6-6 6"/></symbol>'
    + '<symbol id="i-db" viewBox="0 0 24 24"><ellipse cx="12" cy="5.5" rx="7.5" ry="3"/><path d="M4.5 5.5v6c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3v-6M4.5 11.5v6c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3v-6"/></symbol>'
    + '<symbol id="i-code" viewBox="0 0 24 24"><path d="m8 7-5 5 5 5M16 7l5 5-5 5M13 4l-2 16"/></symbol>'
    + '<symbol id="i-doc" viewBox="0 0 24 24"><path d="M6 3h8l5 5v13H6V3Z"/><path d="M14 3v5h5M9 13h7M9 17h7"/></symbol>'
    + '<symbol id="i-spark" viewBox="0 0 24 24"><path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M18 6l-2.5 2.5M8.5 15.5 6 18"/><circle cx="12" cy="12" r="2.5"/></symbol>'
    + '<symbol id="i-play" viewBox="0 0 24 24"><path d="M8 5v14l11-7-11-7Z"/></symbol>'
    + '<symbol id="i-mic" viewBox="0 0 24 24"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3M9 21h6"/></symbol>'
    + '<symbol id="i-film" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4"/></symbol>'
    + "</svg>";
  if (!document.querySelector(".svg-sprite")) {
    document.body.insertAdjacentHTML("afterbegin", SPRITE_SVG);
  }

  function sidebar() {
    const items = NAV.map((item) => {
      const active = item.key === page ? " is-active" : "";
      return `<a class="nav-item nav-link${active}" href="${item.href}">
        <svg class="icon"><use href="#i-${item.icon}"></use></svg>
        <span>${item.label}</span>
        ${item.kicker ? `<span class="nav-kicker">${item.kicker}</span>` : ""}
      </a>`;
    }).join("");
    return `
      <div class="brand">
        <div class="brand-mark">CM</div>
        <div>
          <div class="brand-name">CraftMesh</div>
          <div class="brand-sub">工艺协同中台 · 全栈交付</div>
        </div>
      </div>
      <div class="workspace-pill">
        <span class="live-dot"></span>
        <span>参考实现环境</span>
        <span class="workspace-version">M1+M2+B+C</span>
      </div>
      <nav class="sidebar-nav" aria-label="主导航">${items}</nav>
      <div class="sidebar-section-label">交付说明</div>
      <div class="sidebar-meta">
        <div><span>数据</span><strong>全部合成 / 脱敏</strong></div>
        <div><span>服务</span><strong>Python HTTP API</strong></div>
        <div><span>存储</span><strong>SQLite · 本地</strong></div>
        <div><span>规则</span><strong>JSON 配置文件</strong></div>
      </div>
      <div class="sidebar-note">
        <div class="note-kicker">不是静态原型</div>
        <p>本页所有状态、金额与判定均由本地 API 与 SQLite 实时生成，可复跑、可审计。</p>
      </div>
      <div class="sidebar-foot">
        <span class="live-dot"></span>
        <span id="apiVersion">API 连接中</span>
        <span class="dot-sep">·</span>
        <span id="apiState">检查中</span>
      </div>`;
  }

  function topbar() {
    return `
      <div class="topbar-left">
        <div class="crumb">
          <span class="crumb-root">CraftMesh</span>
          <span class="crumb-sep">/</span>
          <strong>${meta.crumb}</strong>
        </div>
      </div>
      <div class="topbar-right">
        <span class="api-badge" id="apiBadge"><span class="live-dot"></span><span>API 检查中</span></span>
        <label class="role-switcher"><span>当前角色</span>
          <select id="shellRole" aria-label="切换演示角色">
            ${ROLES.map(([v, label]) => `<option value="${v}">${label}</option>`).join("")}
          </select>
        </label>
        <a class="btn btn-ghost btn-small" href="/">返回 M1 工作台</a>
      </div>`;
  }

  document.getElementById("sidebar").innerHTML = sidebar();
  document.getElementById("topbar").innerHTML = topbar();

  const roleSelect = document.getElementById("shellRole");
  roleSelect.value = localStorage.getItem("craftmesh-role") || "admin";
  roleSelect.addEventListener("change", () => {
    localStorage.setItem("craftmesh-role", roleSelect.value);
    document.dispatchEvent(new CustomEvent("craft-role-change", { detail: roleSelect.value }));
  });

  fetch("/api/health").then((r) => r.json()).then((data) => {
    const badge = document.getElementById("apiBadge");
    if (badge) badge.innerHTML = '<span class="live-dot"></span><span>API 在线</span>';
    const version = document.getElementById("apiVersion");
    if (version) version.textContent = "API " + (data.version || "1.0");
    const state = document.getElementById("apiState");
    if (state) state.textContent = "SQLite " + (data.orders ?? 0) + " 订单";
  }).catch(() => {
    const badge = document.getElementById("apiBadge");
    if (badge) { badge.className = "api-badge is-offline"; badge.innerHTML = '<span class="live-dot"></span><span>API 不可用</span>'; }
    const state = document.getElementById("apiState");
    if (state) state.textContent = "离线";
  });
})();
