/* B 模块页面逻辑：行业配置、知识库、智能体、工作流、CRM、三语站点、FDE 手册。
   所有数据来自 /api/ai/*；本页不内置任何业务假数据。 */
(function () {
  'use strict';
  const $ = UI.$;
  const $$ = UI.$$;
  const j = UI.escapeHtml;
  const api = UI.api;
  const money = UI.money;
  const time = UI.time;
  const tag = UI.tag;
  const toast = UI.toast;
  const busy = UI.busy;
  const L = String.fromCharCode(10);
  const role = () => UI.role();

  const state = {
    cfg: null,
    industryId: '',
    dashboard: null,
    docs: [],
    selectedDoc: null,
    docDetail: null,
    search: null,
    session: null,
    messages: [],
    templates: [],
    instances: [],
    workflow: null,
    lastRun: null,
    runs: [],
    leads: [],
    stages: [],
    selectedLead: null,
    site: null,
    seo: null,
    lang: 'zh',
    handbook: '',
    scenario: null
  };

  const cfg = () => state.cfg || {};
  const roleLabel = () => (cfg().roles || {})[role()] || role();
  const industryLabel = () => (cfg().industryName || state.industryId || '');

  function toastErr(err) {
    const message = (err && err.message) || (err && err.payload && err.payload.message) || '操作失败';
    toast(message, 'error');
  }

  function nl2br(text) {
    return String(text === undefined || text === null ? '' : text).split(L).map((line) => j(line)).join('<br>');
  }

  async function boot() {
    try {
      state.cfg = await api('/api/ai/config?role=' + encodeURIComponent(role()));
    } catch (err) {
      toastErr(err);
      return;
    }
    state.industryId = cfg().industry || 'woodcraft';
    fillIndustrySelect();
    applyPermissions();
    renderRoleStrip();
    renderEngineChip();
    bindOnce();
    await Promise.all([loadDashboard(), loadKnowledge(), loadWorkflows(), loadRuns(), loadLeads(), loadSite(), loadHandbook()]);
    renderAgent();
    renderStarterQuestions((cfg().agent || {}).starterQuestions || []);
    renderSearchExamples();
    renderScenario();
  }

  let bound = false;
  function bindOnce() {
    if (bound) return;
    bound = true;
    document.addEventListener('click', onClick);
    document.addEventListener('submit', onSubmit);
    const select = $('#industrySelect');
    if (select) select.addEventListener('change', onIndustryChange);
    document.addEventListener('craft-role-change', () => {
      state.session = null;
      state.messages = [];
      boot().catch(toastErr);
    });
  }

  function fillIndustrySelect() {
    const select = $('#industrySelect');
    if (!select) return;
    const list = cfg().industries || [];
    select.innerHTML = list.map((item) =>
      '<option value="' + j(item.id) + '"' + (item.id === state.industryId ? ' selected' : '') + '>' +
      j(item.name) + '（' + j(item.nameEn) + '）</option>').join('');
    select.value = state.industryId;
  }

  function applyPermissions() {
    const perms = cfg().permissions || {};
    $$('[data-perm]').forEach((el) => {
      const key = el.dataset.perm;
      const info = perms[key] || {};
      const allowed = info.allowed !== false;
      if (el.tagName === 'BUTTON' || el.tagName === 'INPUT' || el.tagName === 'SELECT' || el.tagName === 'TEXTAREA') {
        el.disabled = !allowed;
      }
      if (!allowed) el.title = '当前角色无权执行：' + (info.label || key);
    });
    $$('[data-perm-form]').forEach((form) => {
      const key = form.dataset.permForm;
      const info = perms[key] || {};
      const allowed = info.allowed !== false;
      form.dataset.allowed = allowed ? '1' : '0';
      $$('button[type="submit"]', form).forEach((btn) => { btn.disabled = !allowed; });
      if (!allowed) form.title = '当前角色无权执行：' + (info.label || key);
    });
  }

  function renderRoleStrip() {
    const box = $('#roleStrip');
    if (!box) return;
    const perms = cfg().permissions || {};
    const keys = Object.keys(perms);
    const allowed = keys.filter((key) => perms[key].allowed !== false);
    const denied = keys.length - allowed.length;
    box.innerHTML = '<span>当前角色 <strong>' + j(roleLabel()) + '</strong></span><span class="dot-sep">·</span>' +
      '<span>可执行 ' + allowed.length + ' / ' + keys.length + ' 项动作' + (denied ? '，' + denied + ' 项将被服务端拒绝（403）' : '') + '</span>' +
      '<span class="dot-sep">·</span><span>右上角切换角色后重试同一操作，可验证权限真的生效</span>';
  }

  function renderEngineChip() {
    const chip = $('#engineChip');
    if (!chip) return;
    const engine = cfg().engine || {};
    chip.textContent = (engine.label || '本地规则引擎') + ' · ' + industryLabel() + ' · ' + (cfg().version || '');
  }

  async function onIndustryChange(event) {
    const next = event.target.value;
    try {
      const result = await api('/api/ai/industry', { method: 'POST', body: { industry: next, role: role() } });
      toast('已切换到「' + (result.industry ? result.industry.name : next) + '」');
      state.industryId = next;
      state.session = null;
      state.messages = [];
      state.selectedDoc = null;
      state.docDetail = null;
      state.search = null;
      state.workflow = null;
      state.lastRun = null;
      state.selectedLead = null;
      await boot();
    } catch (err) {
      toastErr(err);
      event.target.value = state.industryId;
    }
  }

  async function loadDashboard() {
    try {
      const result = await api('/api/ai/dashboard?industry=' + encodeURIComponent(state.industryId) + '&role=' + encodeURIComponent(role()));
      state.dashboard = result.dashboard || null;
    } catch (err) {
      state.dashboard = null;
    }
    renderKpis();
  }

  function renderKpis() {
    const box = $('#kpis');
    if (!box) return;
    const data = state.dashboard || {};
    const kb = data.knowledge || { documents: 0, published: 0, chunks: 0 };
    const leads = data.leads || { total: 0, open: 0, won: 0 };
    const wf = data.workflows || { templates: 0, instances: 0, runs: 0, success: 0, failed: 0, successRate: 0, avgDurationMs: 0 };
    const sessions = data.sessions || { total: 0, messages: 0 };
    const engine = data.engine || {};
    const cards = [
      ['知识文档', String(kb.documents), '已发布 ' + kb.published + ' · 切块 ' + kb.chunks + ' 个'],
      ['CRM 线索', String(leads.total), '待跟进 ' + leads.open + ' · 已成交 ' + leads.won],
      ['工作流实例', String(wf.instances), '运行 ' + wf.runs + ' 次 · 成功 ' + wf.success + ' / 失败 ' + wf.failed],
      ['智能体会话', String(sessions.total), sessions.messages + ' 条消息 · 工具 3 类可调用'],
      ['站点语言', String(data.siteLanguages || 3), 'zh / en / ja · SEO 确定性检查'],
      ['运行成功率', String(wf.successRate || 0) + '%', '平均 ' + (wf.avgDurationMs || 0) + 'ms · ' + (engine.label || '本地规则引擎')]
    ];
    box.innerHTML = cards.map((row) =>
      '<div class="kpi-card"><div class="kpi-top"><span>' + j(row[0]) + '</span></div>' +
      '<div class="kpi-value">' + j(row[1]) + '</div>' +
      '<div class="kpi-foot">' + j(row[2]) + '</div></div>').join('');
    applyPermissions();
  }

  function describeResult(result) {
    if (result === undefined || result === null) return '';
    if (Array.isArray(result)) return '返回 ' + result.length + ' 项结果';
    if (typeof result !== 'object') return j(String(result));
    const bits = [];
    if (result.id) bits.push(j(String(result.id)));
    if (result.statusLabel) bits.push('状态 ' + j(String(result.statusLabel)));
    if (result.count !== undefined) bits.push('命中 ' + result.count);
    if (result.tookMs !== undefined) bits.push(result.tookMs + 'ms');
    if (result.chunkCount !== undefined) bits.push('切块 ' + result.chunkCount);
    if (result.messageCount !== undefined) bits.push('消息 ' + result.messageCount);
    if (result.intentLabel) bits.push(j(String(result.intentLabel)));
    if (result.reply) bits.push('回复 ' + String(result.reply).length + ' 字');
    if (result.hits) bits.push('命中 ' + result.hits.length + ' 条引用');
    if (result.lead && result.lead.id) bits.push('线索 ' + j(result.lead.id) + ' · ' + j(result.lead.stageLabel || ''));
    if (result.run) bits.push('运行 ' + j(result.run.statusLabel || '') + ' · ' + (result.run.durationMs || 0) + 'ms');
    if (result.document) bits.push('文档 ' + j(result.document.id || ''));
    if (result.sections) bits.push('手册 ' + result.sections + ' 节 / ' + result.chars + ' 字');
    if (result.industry && result.industry.name) bits.push('行业 ' + j(result.industry.name));
    if (result.score !== undefined) bits.push('评分 ' + result.score);
    if (result.citations && result.citations.length) bits.push('引用 ' + result.citations.length + ' 条');
    if (result.toolCalls && result.toolCalls.length) bits.push('工具 ' + result.toolCalls.map((c) => c.tool).join(' / '));
    if (result.failedStep && result.failedStep.message) bits.push('失败：' + j(result.failedStep.message));
    if (result.steps && result.steps.length) bits.push('步骤 ' + result.steps.length);
    return bits.slice(0, 6).join(' · ');
  }

  function renderScenario() {
    const chip = $('#scenarioChip');
    const body = $('#scenarioBody');
    if (!chip || !body) return;
    const s = state.scenario;
    if (!s) {
      chip.textContent = '未运行';
      body.innerHTML = '<p class="empty-copy">尚未运行。点击右上角「一键全链路自检」会在服务端重置 B 模块数据并跑完 17 步，逐条返回结果与证据；第 ⑯⑰ 步为预期拒绝，用来证明权限与空值校验真实生效。</p>';
      return;
    }
    chip.textContent = '生成于 ' + time(s.generatedAt);
    const items = (s.steps || []).map((step, index) => {
      const expected = step.expectError && !step.ok;
      const cls = step.ok ? 'is-ok' : expected ? 'is-expected' : 'is-fail';
      const flag = step.ok ? '通过' : expected ? '按预期拒绝' : '失败';
      const tone = step.ok ? 'green' : expected ? 'amber' : 'red';
      const meta = step.ok ? describeResult(step.result) : j([step.message, describeResult(step.result)].filter(Boolean).join(' · '));
      return '<div class="result-item ' + cls + '"><div class="result-index">' + String(index + 1).padStart(2, '0') + '</div><div>' +
        '<div class="result-title">' + j(step.title) + '<span class="result-flag">' + tag(flag, tone) + '</span></div>' +
        (meta ? '<div class="result-meta">' + meta + '</div>' : '') + '</div></div>';
    }).join('');
    const summary = s.summary || {};
    body.innerHTML =
      '<div class="scenario-summary"><div><strong>' + (summary.passed || 0) + ' / ' + (summary.steps || 0) + '</strong> 步通过</div>' +
      '<div>预期拒绝 ' + (summary.expectedFailures || 0) + ' 步（权限 / 空值校验）</div>' +
      '<div class="mono">' + j(s.scenario || 'ai-full-chain') + ' · ' + j(summary.engine || '本地规则引擎') + '</div></div>' +
      '<div class="scenario-steps">' + items + '</div>';
  }

  async function runScenario(event) {
    const button = event.target.closest('[data-action]');
    busy(button, true, '自检中…');
    try {
      const result = await api('/api/ai/scenario', { method: 'POST', body: { role: role() } });
      state.scenario = result;
      const summary = result.summary || {};
      if (summary.industry) {
        state.industryId = summary.industry;
        state.cfg = await api('/api/ai/config?role=' + encodeURIComponent(role()));
        fillIndustrySelect();
        applyPermissions();
        renderRoleStrip();
        renderEngineChip();
      }
      state.session = null;
      state.messages = [];
      state.workflow = null;
      state.lastRun = null;
      state.selectedLead = null;
      state.selectedDoc = null;
      state.docDetail = null;
      state.search = null;
      renderScenario();
      toast('自检完成：' + (summary.passed || 0) + ' / ' + (summary.steps || 0) + ' 步通过，预期拒绝 ' + (summary.expectedFailures || 0) + ' 步');
      await Promise.all([loadDashboard(), loadKnowledge(), loadWorkflows(), loadRuns(), loadLeads(), loadSite(), loadHandbook()]);
    } catch (err) {
      toastErr(err);
    } finally {
      busy(button, false);
    }
  }

  async function resetDemo(event) {
    const button = event.target.closest('[data-action]');
    if (!window.confirm('会重置 B 模块的文档、线索、工作流与会话为种子样例，确定继续？')) return;
    busy(button, true, '重置中…');
    try {
      await api('/api/ai/demo/reset', { method: 'POST', body: { role: role() } });
      state.session = null;
      state.messages = [];
      state.workflow = null;
      state.lastRun = null;
      state.selectedLead = null;
      state.search = null;
      state.selectedDoc = null;
      state.docDetail = null;
      toast('演示数据已重置');
      await boot();
    } catch (err) {
      toastErr(err);
    } finally {
      busy(button, false);
    }
  }

  async function loadKnowledge() {
    try {
      const result = await api('/api/ai/knowledge?industry=' + encodeURIComponent(state.industryId) + '&role=' + encodeURIComponent(role()));
      state.docs = result.documents || [];
    } catch (err) {
      state.docs = [];
    }
    renderKnowledge();
    const chosen = state.docs.filter((doc) => doc.id === state.selectedDoc)[0];
    if (!chosen && state.docs.length) await selectDoc(state.docs[0].id);
    const chip = $('#kbChip');
    if (chip) {
      const published = state.docs.filter((doc) => doc.status === 'published').length;
      chip.textContent = state.docs.length + ' 篇 · ' + published + ' 已发布';
    }
  }

  function renderKnowledge() {
    const box = $('#knowledgeList');
    const countChip = $('#docCountChip');
    if (countChip) countChip.textContent = state.docs.length + ' 篇';
    if (!box) return;
    if (!state.docs.length) {
      box.innerHTML = '<p class="empty-copy">当前行业还没有文档。用下方表单写入第一篇，发布后可被检索与引用。</p>';
      return;
    }
    box.innerHTML = state.docs.map((doc) => {
      const active = doc.id === state.selectedDoc ? ' is-selected' : '';
      const keywords = (doc.keywords || []).slice(0, 4).map((kw) => '<span class="ai-kw">' + j(kw) + '</span>').join('');
      const tone = doc.status === 'published' ? 'green' : doc.status === 'draft' ? 'amber' : 'muted';
      return '<button type="button" class="ai-doc-card' + active + '" data-action="select-doc" data-doc="' + j(doc.id) + '">' +
        '<div class="ai-doc-top"><span class="ai-doc-title">' + j(doc.title) + '</span>' + tag(doc.statusLabel || doc.status, tone) + '</div>' +
        '<div class="ai-doc-meta">' + j(doc.version || '') + ' · ' + (doc.chunkCount || 0) + ' 块 · ' + time(doc.updatedAt) + '</div>' +
        '<div class="ai-doc-keywords">' + keywords + '</div></button>';
    }).join('');
  }

  async function selectDoc(id) {
    state.selectedDoc = id;
    try {
      const result = await api('/api/ai/knowledge/' + encodeURIComponent(id));
      state.docDetail = result.document || null;
      state.glossary = result.glossary || [];
    } catch (err) {
      state.docDetail = null;
      toastErr(err);
    }
    renderKnowledge();
    renderKnowledgeDetail();
  }

  function renderKnowledgeDetail() {
    const box = $('#knowledgeDetail');
    if (!box) return;
    const doc = state.docDetail;
    if (!doc) {
      box.innerHTML = '';
      return;
    }
    const chunks = (doc.chunks || []).map((chunk) =>
      '<div class="ai-chunk"><div class="ai-chunk-head"><span class="mono">' + j(chunk.id || '') + '</span>' +
      '<span>' + (chunk.index || '') + ' / ' + (doc.chunkCount || (doc.chunks || []).length) + '</span></div>' +
      '<p>' + nl2br(chunk.text) + '</p>' +
      '<div class="ai-doc-keywords">' + (chunk.keywords || []).map((kw) => '<span class="ai-kw">' + j(kw) + '</span>').join('') + '</div></div>').join('');
    const glossary = (state.glossary || []).slice(0, 6).map((row) =>
      '<tr><td>' + j(row.zh) + '</td><td>' + j(row.en) + '</td><td>' + j(row.ja) + '</td><td>' + j(row.note) + '</td></tr>').join('');
    box.innerHTML = '<div class="ai-doc-detail"><div class="ai-doc-detail-head"><div><div class="ai-mini-kicker">DOCUMENT</div>' +
      '<div class="ai-mini-title">' + j(doc.title) + '</div></div>' + tag(doc.statusLabel || doc.status, doc.status === 'published' ? 'green' : 'amber') + '</div>' +
      '<div class="ai-kv">' + UI.kv([['文档 ID', '<span class="mono">' + j(doc.id) + '</span>'], ['行业', j(doc.industry)], ['版本 / 来源', j((doc.version || '') + ' · ' + (doc.source || '—'))], ['切块 / 关键词', (doc.chunkCount || 0) + ' 块 / ' + (doc.keywords || []).length + ' 个']]) + '</div>' +
      (chunks || '<p class="empty-copy">该文档没有切块。</p>') +
      (glossary ? '<div class="subhead"><h3>行业术语表（用于检索加权）</h3></div><div class="table-wrap"><table class="data-table"><thead><tr><th>中文</th><th>English</th><th>日本語</th><th>口径</th></tr></thead><tbody>' + glossary + '</tbody></table></div>' : '') +
      '</div>';
  }

  async function submitKnowledge(form) {
    if (form.dataset.allowed === '0') { toast('当前角色无权写入知识库', 'error'); return; }
    const data = new FormData(form);
    const payload = {
      title: String(data.get('title') || '').trim(),
      status: String(data.get('status') || 'published'),
      version: String(data.get('version') || '').trim() || 'v1.0',
      content: String(data.get('content') || '').trim(),
      industry: state.industryId,
      role: role()
    };
    if (!payload.title || !payload.content) { toast('标题与正文必填', 'error'); return; }
    const button = form.querySelector('button[type="submit"]');
    busy(button, true, '写入中…');
    try {
      const result = await api('/api/ai/knowledge', { method: 'POST', body: payload });
      toast('已写入并切块：' + result.document.chunkCount + ' 块');
      form.reset();
      form.querySelector('[name="version"]').value = 'v1.0';
      await loadKnowledge();
      await selectDoc(result.document.id);
      await loadDashboard();
    } catch (err) {
      toastErr(err);
    } finally {
      busy(button, false);
    }
  }

  async function submitSearch(form) {
    const data = new FormData(form);
    const query = String(data.get('query') || '').trim();
    if (!query) { toast('请输入检索问题', 'error'); return; }
    const topK = Number(data.get('topK') || 3);
    const button = form.querySelector('button[type="submit"]');
    busy(button, true, '检索中…');
    try {
      const result = await api('/api/ai/search', { method: 'POST', body: { query: query, topK: topK, industry: state.industryId, role: role() } });
      state.search = result;
      renderSearch();
    } catch (err) {
      state.search = null;
      renderSearch();
      toastErr(err);
    } finally {
      busy(button, false);
    }
  }

  function renderSearch() {
    const chip = $('#searchChip');
    const box = $('#searchResults');
    if (!box) return;
    const result = state.search;
    if (!result) return;
    if (chip) chip.textContent = result.count + ' 条 · ' + result.tookMs + 'ms';
    if (!result.hits || !result.hits.length) {
      box.innerHTML = '<p class="empty-copy">没有命中。可换一个更具体的问题，或先确认文档状态为「已发布」。空查询会被服务端直接拒绝（400），不会编造答案。</p>';
      return;
    }
    box.innerHTML = result.hits.map((hit) =>
      '<div class="ai-result-card"><div class="ai-hit-head"><div class="ai-hit-title">' + j(hit.docTitle) + '</div>' +
      '<span class="ai-hit-score">' + hit.score + '</span></div>' +
      '<p class="ai-hit-text">' + nl2br(hit.text) + '</p>' +
      '<div class="ai-hit-foot"><span class="mono">' + j(hit.citation) + '</span>' +
      '<button type="button" class="btn btn-small" data-action="select-doc" data-doc="' + j(String(hit.citation).split('#')[0]) + '">打开文档</button></div></div>').join('');
  }

  function renderSearchExamples() {
    const box = $('#searchExamples');
    if (!box) return;
    const examples = state.industryId === 'jewelry'
      ? ['18K 金婚戒的交付周期和质检标准是什么？', '客户预算 8 万，婚戒定制怎么报价？']
      : ['木蜡油要做几遍？含水率控制在多少？', '户外黑胡桃餐桌的报价与交期怎么算？'];
    box.innerHTML = examples.map((q) => '<button type="button" class="ai-chip" data-action="search-example" data-q="' + j(q) + '">' + j(q) + '</button>').join('');
  }

  function renderStarterQuestions(list) {
    const box = $('#starterQuestions');
    if (!box) return;
    const questions = list || [];
    box.innerHTML = questions.map((q) => '<button type="button" class="ai-chip" data-action="ask-starter" data-q="' + j(q) + '">' + j(q) + '</button>').join('');
  }

  async function newSession() {
    const result = await api('/api/ai/sessions', { method: 'POST', body: { title: industryLabel() + ' · 页面会话', industry: state.industryId, role: role() } });
    state.session = result.session;
    state.messages = [];
    renderStarterQuestions(result.session.starterQuestions || (cfg().agent || {}).starterQuestions || []);
    await reloadSession();
    toast('已新建会话 ' + result.session.id);
    return result.session;
  }

  async function reloadSession() {
    if (!state.session) return;
    const result = await api('/api/ai/sessions/' + encodeURIComponent(state.session.id));
    state.session = result.session;
    state.messages = result.session.messages || [];
    renderStarterQuestions(result.session.starterQuestions || (cfg().agent || {}).starterQuestions || []);
    renderAgent();
  }

  async function sendAgentMessage(content) {
    const text = String(content || '').trim();
    if (!text) { toast('消息不能为空', 'error'); return; }
    try {
      if (!state.session) await newSession();
      const result = await api('/api/ai/sessions/' + encodeURIComponent(state.session.id) + '/messages', { method: 'POST', body: { content: text, role: role() } });
      await reloadSession();
      toast('智能体已回复：' + result.intentLabel);
      const form = $('#agentForm');
      if (form) form.reset();
    } catch (err) {
      toastErr(err);
    }
  }

  function renderAgent() {
    const chip = $('#agentChip');
    const chat = $('#agentChat');
    const line = $('#agentAgentLine');
    const facts = $('#agentFacts');
    const trail = $('#toolTrail');
    const cites = $('#agentCitations');
    const agent = cfg().agent || {};
    if (line) {
      line.innerHTML = state.session
        ? '<span class="live-dot"></span><span>' + j(agent.name || '智能体') + ' · ' + j(industryLabel()) + ' · 本地规则引擎 · 会话 ' + j(String(state.session.id).slice(-6)) + '</span>'
        : '<span class="live-dot"></span><span>选择示例问题，或先新建会话。</span>';
    }
    if (chip) chip.textContent = state.session ? state.messages.length + ' 条消息' : '未建会话';
    if (chat) {
      if (!state.messages.length) {
        chat.innerHTML = '<p class="empty-copy">还没有会话。示例问题会真实创建会话、调用工具并写入 SQLite；回答基于已发布文档片段，引用格式 docId#chunk。</p>';
      } else {
        chat.innerHTML = state.messages.map((msg) => {
          const isUser = msg.sender === 'user';
          const meta = isUser ? '用户 · ' + j(msg.role || '') : j(agent.name || '智能体') + ' · ' + j(msg.intentLabel || '规则路由');
          const extra = !isUser && msg.citations && msg.citations.length
            ? '<div class="ai-msg-cites">' + msg.citations.map((c) => '<span class="ai-cite">' + j(c.citation) + '</span>').join('') + '</div>'
            : '';
          return '<div class="bubble ' + (isUser ? 'is-user' : 'is-agent') + '"><div class="ai-msg-meta">' + meta + '</div><div>' + nl2br(msg.content) + '</div>' + extra + '</div>';
        }).join('');
        chat.scrollTop = chat.scrollHeight;
      }
    }
    if (facts) {
      facts.innerHTML = UI.kv([
        ['会话', state.session ? '<span class="mono">' + j(state.session.id) + '</span>' : '未创建'],
        ['行业', j(industryLabel())],
        ['消息数', String(state.messages.length)],
        ['可用工具', j((agent.tools || []).join(' · ') || 'search_knowledge · create_lead · draft_workflow')]
      ]);
    }
    const lastAssistant = state.messages.slice().reverse().filter((m) => m.sender === 'assistant')[0];
    if (trail) {
      const calls = lastAssistant && lastAssistant.toolCalls ? lastAssistant.toolCalls : [];
      trail.innerHTML = calls.length ? calls.map((call) =>
        '<div class="ai-tool-call"><div class="ai-tool-head"><span class="ai-tool-name">' + j(call.tool) + '</span>' +
        tag(call.ok ? '成功' : '失败', call.ok ? 'green' : 'red') + '</div>' +
        '<details open><summary>参数与结果</summary>' +
        '<div class="ai-step-detail">参数 ' + j(JSON.stringify(call.args || {})) + '</div>' +
        '<div class="ai-step-detail">' + j(call.resultSummary || call.summary || call.detail || '') + (call.durationMs !== undefined ? ' · ' + call.durationMs + 'ms' : '') + '</div></details></div>').join('')
        : '<p class="empty-copy">首轮回复后显示工具名、参数摘要与耗时。</p>';
    }
    if (cites) {
      const list = lastAssistant && lastAssistant.citations ? lastAssistant.citations : [];
      cites.innerHTML = list.length ? list.map((c) =>
        '<div class="ai-cite-list"><div class="ai-hit-head"><span class="mono">' + j(c.citation) + '</span>' + tag(c.docTitle || '', 'muted') + '</div>' +
        '<div class="ai-cite-snippet">' + nl2br(c.text || '') + '</div></div>').join('')
        : '<p class="empty-copy">知识类回答会附带 docId#chunk 引用。</p>';
    }
  }

  async function loadWorkflows() {
    try {
      const result = await api('/api/ai/workflows?industry=' + encodeURIComponent(state.industryId) + '&role=' + encodeURIComponent(role()));
      state.templates = result.templates || [];
      state.instances = result.workflows || [];
    } catch (err) {
      state.templates = [];
      state.instances = [];
    }
    renderTemplates();
    renderInstances();
    const chip = $('#workflowChip');
    if (chip) {
      const wf = (state.dashboard || {}).workflows || {};
      chip.textContent = wf.runs ? '运行 ' + wf.runs + ' 次 · 成功率 ' + wf.successRate + '%' : state.templates.length + ' 个模板';
    }
  }

  function renderTemplates() {
    const box = $('#workflowTemplates');
    const chip = $('#templateChip');
    if (chip) chip.textContent = state.templates.length + ' 个';
    if (!box) return;
    if (!state.templates.length) {
      box.innerHTML = '<p class="empty-copy">当前行业没有可用的工作流模板。</p>';
      return;
    }
    box.innerHTML = state.templates.map((tpl) => {
      const steps = (tpl.steps || []).length;
      const inputs = (tpl.requiredInputs || []).map((key) => '<span class="ai-kw">' + j(key) + '</span>').join('');
      return '<div class="ai-workflow-card is-template"><div class="ai-workflow-top"><div class="ai-workflow-name">' + j(tpl.name) + '</div>' +
        tag(tpl.version || 'v1.0', 'muted') + '</div>' +
        '<p class="ai-workflow-desc">' + j(tpl.description || '') + '</p>' +
        '<div class="ai-workflow-meta"><span>' + steps + ' 步</span><span>' + j((tpl.trigger || {}).label || '手动触发') + '</span></div>' +
        '<div class="ai-doc-keywords">' + inputs + '</div>' +
        '<div class="ai-form-actions"><button type="button" class="btn btn-small" data-action="create-workflow" data-template="' + j(tpl.id) + '">从模板创建实例</button></div></div>';
    }).join('');
  }

  function renderInstances() {
    const box = $('#workflowInstances');
    const chip = $('#instanceChip');
    if (chip) chip.textContent = state.instances.length + ' 个';
    if (!box) return;
    if (!state.instances.length) {
      box.innerHTML = '<p class="empty-copy">还没有实例。从左侧模板创建一个即可运行，每一步都会真实执行并记录。</p>';
      return;
    }
    box.innerHTML = state.instances.map((wf) => {
      const active = state.workflow && state.workflow.id === wf.id ? ' is-selected' : '';
      const tone = wf.status === 'active' ? 'green' : 'amber';
      return '<button type="button" class="ai-workflow-card' + active + '" data-action="select-workflow" data-workflow="' + j(wf.id) + '">' +
        '<div class="ai-workflow-top"><span class="ai-workflow-name">' + j(wf.name) + '</span>' + tag(wf.statusLabel || wf.status, tone) + '</div>' +
        '<div class="ai-workflow-meta"><span class="mono">' + j(wf.id) + '</span><span>' + (wf.steps || []).length + ' 步 · 已运行 ' + (wf.runCount || 0) + ' 次</span></div></button>';
    }).join('');
  }

  async function createWorkflow(templateId) {
    const template = state.templates.filter((tpl) => tpl.id === templateId)[0];
    if (!template) return;
    try {
      const result = await api('/api/ai/workflows', { method: 'POST', body: { templateId: templateId, name: template.name + ' · 页面实例', role: role() } });
      toast('已创建工作流实例 ' + result.workflow.id);
      await loadWorkflows();
      await loadWorkflow(result.workflow.id);
      await loadDashboard();
    } catch (err) {
      toastErr(err);
    }
  }

  async function loadWorkflow(id) {
    try {
      const result = await api('/api/ai/workflows/' + encodeURIComponent(id) + '?role=' + encodeURIComponent(role()));
      state.workflow = result.workflow || null;
      state.lastRun = null;
      renderInstances();
      renderWorkflowDetail();
      const box = $('#runResult');
      if (box) box.innerHTML = '<p class="empty-copy">填写输入并运行；运行结果会显示逐步状态、耗时与失败原因。</p>';
    } catch (err) {
      toastErr(err);
    }
  }

  const INPUT_LABELS = { name: '姓名', email: '邮箱', country: '国家 / 地区', interest: '需求', budget: '预算', lang: '语言' };

  function inputFields(example, values) {
    // 合并示例字段与已填值：失败重试时 inputSummary 会省略空字段（例如 email），
    // 若只用 values 会缺失输入框，用户无法补齐缺失字段。
    const source = Object.assign({}, example || {}, values || {});
    const order = ['name', 'email', 'country', 'interest', 'budget'];
    let html = '';
    order.forEach((key) => {
      if (!(key in source) && !(example && key in example)) return;
      const type = key === 'email' ? 'email' : 'text';
      html += '<label class="field"><span>' + j(INPUT_LABELS[key] || key) + '</span><input type="' + type + '" name="' + key + '" value="' + j(source[key] === undefined || source[key] === null ? '' : source[key]) + '" maxlength="120"></label>';
    });
    const langValue = String(source.lang || 'zh');
    html += '<label class="field"><span>' + j(INPUT_LABELS.lang) + '</span><select name="lang">' +
      ['zh:中文', 'en:English', 'ja:日本語'].map((pair) => {
        const parts = pair.split(':');
        return '<option value="' + parts[0] + '"' + (parts[0] === langValue ? ' selected' : '') + '>' + parts[1] + '</option>';
      }).join('') + '</select></label>';
    return html;
  }

  function renderWorkflowDetail() {
    const box = $('#workflowDetail');
    if (!box) return;
    const wf = state.workflow;
    if (!wf) {
      box.innerHTML = '<p class="empty-copy">选择左侧实例查看步骤、运行表单与结果。</p>';
      return;
    }
    const template = state.templates.filter((tpl) => tpl.id === wf.templateId)[0];
    const example = (template && template.inputExample) || { name: '林女士', email: 'lin@example.com', country: 'CN', interest: '黑胡桃户外餐桌', budget: '120000', lang: 'zh' };
    const steps = (wf.steps || []).map((step, index) =>
      '<div class="ai-run-step ok"><div class="ai-step-index">' + (index + 1) + '</div><div><div class="ai-step-name">' + j(step.name) + '</div>' +
      '<div class="ai-step-detail">' + j(step.typeLabel || step.type) + (step.condition ? ' · 条件 ' + j(JSON.stringify(step.condition)) : '') + '</div></div></div>').join('');
    box.innerHTML = '<div class="ai-run-head"><div><div class="ai-mini-kicker">INSTANCE</div><div class="ai-mini-title">' + j(wf.name) + '</div></div>' +
      tag(wf.statusLabel || wf.status, wf.status === 'active' ? 'green' : 'amber') + '</div>' +
      '<div class="ai-run-meta"><span class="mono">' + j(wf.id) + '</span><span>模板 ' + j(wf.templateId || '') + '</span><span>已运行 ' + (wf.runCount || 0) + ' 次</span></div>' +
      '<div class="ai-steps">' + steps + '</div>' +
      '<form class="ai-run-form" id="runForm" data-form="run-form" data-workflow="' + j(wf.id) + '"><div class="field-label">运行输入 <span>缺必填字段会让校验步骤真实失败</span></div>' +
      inputFields(example, null) +
      '<div class="ai-form-actions"><button type="submit" class="btn btn-primary btn-small">运行工作流</button><span class="ai-hint">成功后线索会写入 CRM，可在下方线索表看到。</span></div></form>';
  }

  async function runWorkflowForm(form) {
    const data = new FormData(form);
    const input = {};
    data.forEach((value, key) => {
      const text = String(value === null ? '' : value).trim();
      if (text) input[key] = text;
    });
    const workflowId = form.dataset.workflow;
    const button = form.querySelector('button[type="submit"]');
    busy(button, true, '运行中…');
    try {
      const result = await api('/api/ai/workflows/' + encodeURIComponent(workflowId) + '/run', { method: 'POST', body: { input: input, role: role() } });
      state.lastRun = result.run;
      renderRunResult(result.run);
      toast('运行完成：' + result.run.statusLabel + ' · ' + result.run.durationMs + 'ms');
      await Promise.all([loadRuns(), loadDashboard()]);
      if (result.run.leadId) await loadLeads();
    } catch (err) {
      toastErr(err);
      if (err && err.payload && err.payload.run) {
        state.lastRun = err.payload.run;
        renderRunResult(err.payload.run);
      }
    } finally {
      busy(button, false);
    }
  }

  function citationChips(list) {
    if (!list || !list.length) return '';
    return '<div class="ai-msg-cites">' + list.map((item) => '<span class="ai-cite">' + j(item) + '</span>').join('') + '</div>';
  }

  function renderRunResult(run) {
    const box = $('#runResult');
    if (!box || !run) return;
    const tone = run.status === 'success' ? 'green' : 'red';
    const failed = run.failedStep
      ? '<div class="callout is-warn"><strong>失败步骤 #' + run.failedStep.index + ' ' + j(run.failedStep.name) + '</strong><div>' + j(run.failedStep.message || run.failedStep.error || '') + '</div></div>'
      : '';
    const steps = (run.steps || []).map((step) => {
      const cls = step.ok ? (step.skipped ? 'skipped' : 'ok') : 'fail';
      const stateLabel = step.ok ? (step.skipped ? '跳过' : '通过') : '失败';
      return '<div class="ai-run-step ' + cls + '"><div class="ai-step-index">' + step.index + '</div><div>' +
        '<div class="ai-step-name">' + j(step.name) + ' ' + tag(stateLabel, step.ok ? (step.skipped ? 'muted' : 'green') : 'red') + '</div>' +
        '<div class="ai-step-detail">' + j(step.detail || '') + (step.error ? ' · ' + j(step.error) : '') + '</div>' +
        '<div class="ai-step-extra">' + (step.durationMs !== undefined ? step.durationMs + 'ms · ' : '') + j(step.typeLabel || step.type || '') + '</div></div></div>';
    }).join('');
    const leadLine = run.leadId
      ? '<div class="ai-run-foot"><span>线索 <span class="mono">' + j(run.leadId) + '</span> · 评级 ' + j(run.grade || '—') + '</span>' +
        '<button type="button" class="btn btn-small" data-action="select-lead" data-lead="' + j(run.leadId) + '">在 CRM 中查看</button></div>'
      : '';
    const retry = run.status === 'failed'
      ? '<form class="ai-retry-form" id="retryForm" data-form="retry-form" data-run="' + j(run.id) + '"><div class="field-label">补齐字段后重试 <span>只有失败运行可重试；会生成 attempt ' + ((run.attempt || 1) + 1) + '</span></div>' +
        inputFields((state.workflow && state.templates.filter((tpl) => tpl.id === state.workflow.templateId)[0] || {}).inputExample || {}, run.input || {}) +
        '<div class="ai-form-actions"><button type="submit" class="btn btn-primary btn-small">补齐并重试</button><span class="ai-hint">重试不会篡改原失败记录，会新建一条运行并标注 retryOf。</span></div></form>'
      : '';
    box.innerHTML = '<div class="ai-run-head"><div><div class="ai-mini-kicker">RUN RESULT</div><div class="ai-mini-title">' + j(run.workflowName || (state.workflow && state.workflow.name) || '') + '</div></div>' + tag(run.statusLabel || run.status, tone) + '</div>' +
      '<div class="ai-run-meta"><span class="mono">' + j(run.id) + '</span><span>attempt ' + (run.attempt || 1) + (run.retryOf ? ' · retryOf ' + j(run.retryOf) : '') + '</span><span>' + (run.durationMs || 0) + 'ms</span><span>' + time(run.startedAt) + '</span></div>' +
      failed +
      '<div class="ai-steps">' + steps + '</div>' +
      citationChips(run.citations) + leadLine + retry;
  }

  async function submitRetry(form) {
    const data = new FormData(form);
    const input = {};
    data.forEach((value, key) => {
      const text = String(value === null ? '' : value).trim();
      if (text) input[key] = text;
    });
    const runId = form.dataset.run;
    const button = form.querySelector('button[type="submit"]');
    busy(button, true, '重试中…');
    try {
      const result = await api('/api/ai/workflows/runs/' + encodeURIComponent(runId) + '/retry', { method: 'POST', body: { input: input, role: role() } });
      state.lastRun = result.run;
      renderRunResult(result.run);
      toast('重试完成：' + result.run.statusLabel);
      await Promise.all([loadRuns(), loadDashboard()]);
      if (result.run.leadId) await loadLeads();
    } catch (err) {
      toastErr(err);
    } finally {
      busy(button, false);
    }
  }

  async function loadRuns() {
    try {
      const result = await api('/api/ai/workflows/runs?limit=20&role=' + encodeURIComponent(role()));
      state.runs = result.runs || [];
    } catch (err) {
      state.runs = [];
    }
    renderRuns();
    const chip = $('#runChip');
    if (chip) chip.textContent = state.runs.length + ' 条';
  }

  function renderRuns() {
    const box = $('#runHistory');
    if (!box) return;
    if (!state.runs.length) {
      box.innerHTML = '<p class="empty-copy">运行一次后显示历史记录（含失败与重试）。</p>';
      return;
    }
    box.innerHTML = state.runs.map((run) => {
      const tone = run.status === 'success' ? 'green' : 'red';
      const failed = run.failedStep ? '<div class="ai-step-detail">失败 #' + run.failedStep.index + ' ' + j(run.failedStep.name) + '：' + j(run.failedStep.message || run.failedStep.error || '') + '</div>' : '';
      return '<div class="ai-history-card"><div class="ai-history-top"><div><div class="ai-history-title">' + j(run.workflowName || '') + '</div>' +
        '<div class="ai-history-meta"><span class="mono">' + j(run.id) + '</span><span>attempt ' + (run.attempt || 1) + (run.retryOf ? ' · retryOf ' + j(run.retryOf) : '') + '</span><span>' + (run.durationMs || 0) + 'ms</span><span>' + time(run.startedAt) + '</span></div></div>' +
        tag(run.statusLabel || run.status, tone) + '</div>' + failed +
        '<div class="ai-form-actions"><button type="button" class="btn btn-small" data-action="view-run" data-run="' + j(run.id) + '">查看逐步结果</button>' +
        (run.status === 'failed' ? '<button type="button" class="btn btn-small" data-action="prepare-retry" data-run="' + j(run.id) + '">补齐并重试</button>' : '') +
        '</div></div>';
    }).join('');
  }

  async function viewRun(runId) {
    try {
      const result = await api('/api/ai/workflows/runs/' + encodeURIComponent(runId) + '?role=' + encodeURIComponent(role()));
      state.lastRun = result.run;
      // 先载入所属实例，renderRunResult 才能拿到模板 inputExample，
      // 失败运行缺少的必填字段（如 email）才会在重试表单里出现。
      if (result.run.workflowId) {
        try { await loadWorkflow(result.run.workflowId); } catch (err) { /* 实例加载失败也展示运行结果 */ }
      }
      renderRunResult(result.run);
      const box = $('#runResult');
      if (box && box.scrollIntoView) box.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (err) {
      toastErr(err);
    }
  }

  async function prepareRetry(runId) {
    const brief = state.runs.filter((run) => run.id === runId)[0];
    if (!brief) return;
    try {
      await loadWorkflow(brief.workflowId);
    } catch (err) {
      toastErr(err);
    }
    const box = $('#runResult');
    if (!box) return;
    box.innerHTML = '<div class="ai-run-head"><div><div class="ai-mini-kicker">RETRY</div><div class="ai-mini-title">补齐后重试 ' + j(runId) + '</div></div>' + tag('失败待重试', 'amber') + '</div>' +
      '<form class="ai-retry-form" id="retryForm" data-form="retry-form" data-run="' + j(runId) + '"><div class="field-label">运行输入 <span>原运行缺少必填字段时会被校验拦截，这里补齐即可</span></div>' +
      inputFields({ name: '', email: '', country: 'CN', interest: '', budget: '', lang: 'zh' }, brief.inputSummary || {}) +
      '<div class="ai-form-actions"><button type="submit" class="btn btn-primary btn-small">补齐并重试</button><span class="ai-hint">只有失败运行可重试；成功后生成新运行记录。</span></div></form>';
    if (box.scrollIntoView) box.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  async function loadLeads() {
    try {
      const result = await api('/api/ai/leads?industry=' + encodeURIComponent(state.industryId) + '&role=' + encodeURIComponent(role()));
      state.leads = result.leads || [];
      state.stages = result.stages || [];
    } catch (err) {
      state.leads = [];
    }
    renderLeads();
    const chip = $('#leadChip');
    if (chip) {
      const open = state.leads.filter((lead) => lead.status !== 'closed').length;
      chip.textContent = state.leads.length + ' 条 · ' + open + ' 待跟进';
    }
  }

  const STAGE_TONES = { blue: 'accent', amber: 'amber', green: 'green', red: 'red' };

  function renderLeads() {
    const table = $('#leadTable');
    const detail = $('#leadDetail');
    if (!table) return;
    const body = table.querySelector('tbody');
    if (!state.leads.length) {
      body.innerHTML = '<tr><td colspan="6" class="table-empty">还没有线索。提交一次询盘，或让智能体调用 create_lead。</td></tr>';
    } else {
      body.innerHTML = state.leads.map((lead) => {
        const active = state.selectedLead && state.selectedLead.id === lead.id ? ' class="is-selected"' : '';
        const tone = STAGE_TONES[lead.stageTone] || (lead.stage === 'won' ? 'green' : lead.stage === 'lost' ? 'red' : 'accent');
        return '<tr' + active + ' data-action="select-lead" data-lead="' + j(lead.id) + '">' +
          '<td><div class="ai-lead-name">' + j(lead.name) + '</div><div class="ai-lead-sub mono">' + j(lead.id) + '</div></td>' +
          '<td><div>' + j(lead.email) + '</div><div class="ai-lead-sub">' + j(lead.countryLabel || lead.country || '—') + ' · ' + j(lead.lang || '') + '</div></td>' +
          '<td>' + j(lead.interest || '—') + '</td>' +
          '<td>' + j(lead.budgetText || '—') + '</td>' +
          '<td>' + tag((lead.score || {}).grade || '—', (lead.score || {}).grade === 'A' ? 'green' : (lead.score || {}).grade === 'B' ? 'amber' : 'muted') + '</td>' +
          '<td>' + tag(lead.stageLabel || lead.stage, tone) + '</td></tr>';
      }).join('');
    }
    if (detail && !state.selectedLead) {
      detail.innerHTML = '<p class="empty-copy">选择一条线索推进阶段并记录备注；阶段与备注都会写入历史。</p>';
    }
  }

  async function selectLead(leadId) {
    const lead = state.leads.filter((item) => item.id === leadId)[0];
    if (!lead) return;
    state.selectedLead = lead;
    renderLeads();
    renderLeadDetail();
  }

  function renderLeadDetail() {
    const box = $('#leadDetail');
    if (!box) return;
    const lead = state.selectedLead;
    if (!lead) { box.innerHTML = ''; return; }
    const stageOptions = state.stages.map((stage) => '<option value="' + j(stage.id) + '"' + (stage.id === lead.stage ? ' selected' : '') + '>' + j(stage.label) + '</option>').join('');
    const notes = (lead.notes || []).slice().reverse().map((note) =>
      '<div class="ai-lead-note"><div class="ai-step-detail">' + time(note.at) + ' · ' + j(note.by || '') + '</div><div>' + nl2br(note.text) + '</div></div>').join('');
    const history = (lead.history || []).slice().reverse().map((row) =>
      '<div class="ai-step-detail">' + time(row.at) + ' · ' + j(row.from || '—') + ' → ' + j(row.to || '—') + ' · ' + j(row.by || '') + (row.note ? ' · ' + j(row.note) : '') + '</div>').join('');
    box.innerHTML = '<div class="ai-lead-detail"><div class="ai-lead-detail-head"><div><div class="ai-mini-kicker">LEAD</div><div class="ai-mini-title">' + j(lead.name) + '</div></div>' +
      tag((lead.score || {}).grade || '—', (lead.score || {}).grade === 'A' ? 'green' : 'amber') + '</div>' +
      '<div class="ai-kv">' + UI.kv([
        ['线索 ID', '<span class="mono">' + j(lead.id) + '</span>'],
        ['联系', j(lead.email) + ' · ' + j(lead.countryLabel || lead.country || '—')],
        ['需求', j(lead.interest || '—')],
        ['预算', j(lead.budgetText || '—')],
        ['来源', j(lead.source || '—')],
        ['阶段', tag(lead.stageLabel || lead.stage, STAGE_TONES[lead.stageTone] || 'accent')]
      ]) + '</div>' +
      '<form class="ai-lead-edit" id="leadForm" data-form="lead-form" data-lead="' + j(lead.id) + '">' +
      '<label class="field"><span>推进到阶段</span><select name="stage">' + stageOptions + '</select></label>' +
      '<label class="field"><span>备注（可选，≤500 字）</span><textarea name="note" rows="3" maxlength="500" placeholder="例如：已电话确认需求，约 11 月上门复尺（合成样例）"></textarea></label>' +
      '<div class="ai-form-actions"><button type="submit" class="btn btn-primary btn-small">保存阶段与备注</button></div></form>' +
      (notes ? '<div class="subhead"><h3>备注</h3></div>' + notes : '') +
      '<div class="subhead"><h3>阶段历史</h3></div>' + (history || '<p class="empty-copy">暂无历史。</p>') + '</div>';
  }

  async function submitLead(form) {
    const data = new FormData(form);
    const leadId = form.dataset.lead;
    const payload = { stage: String(data.get('stage') || ''), note: String(data.get('note') || '').trim(), role: role() };
    const button = form.querySelector('button[type="submit"]');
    busy(button, true, '保存中…');
    try {
      await api('/api/ai/leads/' + encodeURIComponent(leadId), { method: 'POST', body: payload });
      toast('线索已更新');
      await loadLeads();
      await selectLead(leadId);
      await loadDashboard();
    } catch (err) {
      toastErr(err);
    } finally {
      busy(button, false);
    }
  }

  async function submitInquiry(form) {
    const data = new FormData(form);
    const payload = {
      name: String(data.get('name') || '').trim(),
      email: String(data.get('email') || '').trim(),
      country: String(data.get('country') || '').trim(),
      budget: String(data.get('budget') || '').trim(),
      interest: String(data.get('interest') || '').trim(),
      message: String(data.get('message') || '').trim(),
      lang: String(data.get('lang') || 'zh'),
      industry: state.industryId,
      role: role()
    };
    if (!payload.name || !payload.email || !payload.interest) { toast('姓名、邮箱、需求必填', 'error'); return; }
    const button = form.querySelector('button[type="submit"]');
    busy(button, true, '提交中…');
    try {
      const result = await api('/api/ai/inquiries', { method: 'POST', body: payload });
      state.inquiry = result.lead;
      renderInquiry(result.lead);
      toast('询盘已写入 CRM：' + result.lead.id);
      form.reset();
      form.querySelector('[name="country"]').value = 'CN';
      await loadLeads();
      await loadDashboard();
    } catch (err) {
      toastErr(err);
    } finally {
      busy(button, false);
    }
  }

  function renderInquiry(lead) {
    const box = $('#inquiryResult');
    if (!box) return;
    if (!lead) { box.innerHTML = ''; return; }
    box.innerHTML = '<div class="ai-inquiry-result"><div class="ai-inquiry-head"><div class="ai-mini-title">已写入 CRM</div>' +
      tag(lead.stageLabel || lead.stage, 'accent') + '</div>' +
      '<div class="ai-kv">' + UI.kv([
        ['线索', '<span class="mono">' + j(lead.id) + '</span>'],
        ['评级', j((lead.score || {}).grade || '—')],
        ['邮箱', j(lead.email)],
        ['需求', j(lead.interest || '—')]
      ]) + '</div></div>';
  }

  async function loadSite() {
    try {
      const result = await api('/api/ai/site/' + encodeURIComponent(state.lang) + '?industry=' + encodeURIComponent(state.industryId) + '&role=' + encodeURIComponent(role()));
      state.site = result.site || null;
      state.seo = result.seo || null;
    } catch (err) {
      state.site = null;
      state.seo = null;
    }
    renderSite();
    renderSeo();
    const chip = $('#growthChip');
    if (chip) chip.textContent = state.lang + ' · ' + (state.seo ? state.seo.coverage.pct + '% 关键词覆盖' : '加载中');
  }

  function renderSite() {
    const box = $('#sitePreview');
    if (!box) return;
    const site = state.site;
    if (!site) {
      box.innerHTML = '<p class="empty-copy">站点文案加载失败，可检查 /api/ai/site/' + j(state.lang) + '。</p>';
      return;
    }
    const tabs = $$('.ai-tab');
    tabs.forEach((tab) => { tab.classList.toggle('is-active', tab.dataset.lang === state.lang); });
    const sections = (site.sections || []).map((section) =>
      '<div class="ai-site-section"><h4>' + j(section.heading) + '</h4><p>' + nl2br(section.body) + '</p></div>').join('');
    const faq = (site.faq || []).map((row) =>
      '<div class="ai-faq"><div class="ai-faq-title">' + j(row.q) + '</div><div class="ai-faq-a">' + nl2br(row.a) + '</div></div>').join('');
    box.innerHTML = '<div class="ai-site-hero"><div class="ai-site-kicker">' + j(industryLabel()) + ' · ' + j(site.label || state.lang) + ' · 合成演示站</div>' +
      '<div class="ai-site-title">' + j(site.title) + '</div>' +
      '<h3>' + j(site.hero ? site.hero.headline : '') + '</h3>' +
      '<p>' + j(site.hero ? site.hero.subline : '') + '</p>' +
      '<span class="ai-site-cta">' + j(site.hero ? site.hero.cta : '') + '</span></div>' +
      '<p class="ai-md">' + j(site.description || '') + '</p>' +
      '<div class="ai-site-sections">' + sections + '</div>' +
      '<div class="ai-site-sections">' + faq + '</div>' +
      '<p class="ai-hint">当前为合成演示站，robots 设为 noindex,nofollow；站长与备案信息以真实交付为准。</p>';
  }

  function renderSeo() {
    const box = $('#seoPanel');
    if (!box) return;
    const seo = state.seo;
    if (!seo) {
      box.innerHTML = '<p class="empty-copy">SEO 检查加载失败。</p>';
      return;
    }
    const checks = (seo.checks || []).map((check) =>
      '<div class="ai-check ' + (check.ok ? 'pass' : 'fail') + '"><span class="dot"></span><div><div class="ai-check-name">' + j(check.label) + '</div>' +
      '<div class="ai-check-detail">' + j(check.detail) + '</div></div></div>').join('');
    const coverage = seo.coverage || { matched: [], missing: [], pct: 0 };
    const matched = (coverage.matched || []).map((kw) => '<span class="ai-kw">' + j(kw) + '</span>').join('');
    const missing = (coverage.missing || []).map((kw) => '<span class="ai-kw">缺 ' + j(kw) + '</span>').join('');
    const meta = seo.meta || {};
    box.innerHTML = '<div class="ai-seo"><div class="ai-seo-head"><div><div class="ai-mini-kicker">SEO</div><div class="ai-mini-title">确定性命中检查</div></div>' +
      '<div class="ai-seo-score">' + (coverage.pct || 0) + '%</div></div>' +
      '<div class="ai-seo-meta">' + UI.kv([
        ['title', j(meta.title || '')],
        ['description', j(meta.description || '')],
        ['robots', j(meta.robots || '')],
        ['canonical', '<span class="mono">' + j(meta.canonical || '') + '</span>']
      ]) + '</div>' +
      '<div class="ai-check-list">' + checks + '</div>' +
      '<div class="ai-keyword-row">' + matched + missing + '</div>' +
      '<p class="ai-hint">分数只代表关键词与长度规则的确定性匹配，不代表真实搜索排名或流量承诺。</p></div>';
  }

  async function setLang(lang) {
    state.lang = lang;
    await loadSite();
  }

  async function loadHandbook() {
    try {
      const result = await api('/api/ai/fde-handbook');
      state.handbook = result.markdown || '';
    } catch (err) {
      state.handbook = '';
    }
    renderHandbook();
  }

  function inlineMarkdown(text) {
    let out = j(text);
    const boldParts = out.split('**');
    out = boldParts.map((part, index) => (index % 2 === 1 ? '<strong>' + part + '</strong>' : part)).join('');
    const tick = String.fromCharCode(96);
    const codeParts = out.split(tick);
    out = codeParts.map((part, index) => (index % 2 === 1 ? '<code>' + part + '</code>' : part)).join('');
    return out;
  }

  function isTableSeparator(cells) {
    if (!cells.length) return false;
    return cells.every((cell) => {
      const text = cell.trim();
      return text === '' || text.indexOf('--') === 0 || text.indexOf('—') === 0 || text.indexOf(':--') === 0;
    });
  }

  function renderTable(rows) {
    if (!rows.length) return '';
    const bodyRows = rows.slice(1).filter((cells) => !isTableSeparator(cells));
    const head = '<thead><tr>' + rows[0].map((cell) => '<th>' + inlineMarkdown(cell.trim()) + '</th>').join('') + '</tr></thead>';
    const body = '<tbody>' + bodyRows.map((cells) => '<tr>' + cells.map((cell) => '<td>' + inlineMarkdown(cell.trim()) + '</td>').join('') + '</tr>').join('') + '</tbody>';
    return '<div class="ai-md-table-wrap"><table class="data-table">' + head + body + '</table></div>';
  }

  function mdBlocks(lines) {
    let html = '';
    let index = 0;
    while (index < lines.length) {
      const line = lines[index].trim();
      if (!line) { index += 1; continue; }
      if (line.charAt(0) === '|') {
        const rows = [];
        while (index < lines.length && lines[index].trim().charAt(0) === '|') {
          const raw = lines[index].trim();
          const cells = raw.split('|');
          cells.shift();
          if (cells.length && cells[cells.length - 1].trim() === '') cells.pop();
          rows.push(cells);
          index += 1;
        }
        html += renderTable(rows);
        continue;
      }
      if (line.indexOf('- ') === 0 || line.indexOf('* ') === 0) {
        const items = [];
        while (index < lines.length) {
          const current = lines[index].trim();
          if (current.indexOf('- ') !== 0 && current.indexOf('* ') !== 0) break;
          items.push('<li>' + inlineMarkdown(current.slice(2)) + '</li>');
          index += 1;
        }
        html += '<ul>' + items.join('') + '</ul>';
        continue;
      }
      if (line.indexOf('> ') === 0) {
        const quotes = [];
        while (index < lines.length && lines[index].trim().indexOf('> ') === 0) {
          quotes.push(inlineMarkdown(lines[index].trim().slice(2)));
          index += 1;
        }
        html += '<blockquote class="ai-md">' + quotes.join('<br>') + '</blockquote>';
        continue;
      }
      if (line.indexOf('### ') === 0) {
        html += '<h4>' + inlineMarkdown(line.slice(4)) + '</h4>';
        index += 1;
        continue;
      }
      const firstChar = line.charAt(0);
      if (firstChar >= '0' && firstChar <= '9' && line.indexOf('. ') > 0) {
        const marks = [];
        while (index < lines.length) {
          const current = lines[index].trim();
          const second = current.charAt(0);
          if (!(second >= '0' && second <= '9') || current.indexOf('. ') < 0) break;
          marks.push('<li>' + inlineMarkdown(current.slice(current.indexOf('. ') + 2)) + '</li>');
          index += 1;
        }
        html += '<ol>' + marks.join('') + '</ol>';
        continue;
      }
      const paragraph = [line];
      index += 1;
      while (index < lines.length) {
        const next = lines[index].trim();
        if (!next || next.charAt(0) === '|' || next.indexOf('- ') === 0 || next.indexOf('* ') === 0 || next.indexOf('### ') === 0 || next.indexOf('> ') === 0) break;
        paragraph.push(next);
        index += 1;
      }
      html += '<p class="ai-md">' + paragraph.map(inlineMarkdown).join('<br>') + '</p>';
    }
    return html;
  }

  function renderHandbook() {
    const box = $('#handbookBody');
    const chip = $('#handbookChip');
    if (!box) return;
    const markdown = state.handbook || '';
    if (!markdown) {
      box.innerHTML = '<p class="empty-copy">FDE 手册加载失败，可直接访问 /api/ai/fde-handbook 查看原始 markdown。</p>';
      return;
    }
    const lines = markdown.split(L);
    const intro = [];
    const sections = [];
    let current = null;
    lines.forEach((line) => {
      const trimmed = line.trim();
      if (trimmed.indexOf('## ') === 0) {
        current = { title: trimmed.slice(3), lines: [] };
        sections.push(current);
        return;
      }
      if (current) current.lines.push(line);
      else intro.push(line);
    });
    box.innerHTML = '<div class="ai-md-intro">' + mdBlocks(intro) + '</div>' +
      sections.map((section) => '<section class="ai-md-section"><h3>' + inlineMarkdown(section.title) + '</h3>' + mdBlocks(section.lines) + '</section>').join('');
    if (chip) chip.textContent = sections.length + ' 节 · ' + markdown.length + ' 字符';
  }

  function toggleHandbook(mode) {
    const sections = $$('#handbookBody .ai-md-section');
    sections.forEach((section) => { section.style.display = mode === 'collapse' ? 'none' : ''; });
  }

  async function onClick(event) {
    const target = event.target.closest('[data-action]');
    if (!target) return;
    if (target.tagName === 'FORM') return;
    if (target.tagName === 'BUTTON' && target.type === 'submit' && target.closest('form')) return;
    const action = target.dataset.action;
    if (action === 'run-scenario') return runScenario(event);
    if (action === 'reset-demo') return resetDemo(event);
    if (action === 'select-doc') return selectDoc(target.dataset.doc);
    if (action === 'ask-starter') return sendAgentMessage(target.dataset.q);
    if (action === 'search-example') {
      const form = $('#searchForm');
      const input = form && form.querySelector('[name="query"]');
      if (input) input.value = target.dataset.q || '';
      if (form) return submitSearch(form);
      return undefined;
    }
    if (action === 'new-session') {
      try { await newSession(); renderAgent(); } catch (err) { toastErr(err); }
      return;
    }
    if (action === 'create-workflow') return createWorkflow(target.dataset.template);
    if (action === 'select-workflow') return loadWorkflow(target.dataset.workflow);
    if (action === 'view-run') return viewRun(target.dataset.run);
    if (action === 'prepare-retry') return prepareRetry(target.dataset.run);
    if (action === 'set-lang') return setLang(target.dataset.lang);
    if (action === 'expand-handbook') return toggleHandbook('expand');
    if (action === 'collapse-handbook') return toggleHandbook('collapse');
    if (action === 'select-lead') return selectLead(target.dataset.lead);
  }

  async function onSubmit(event) {
    const form = event.target;
    if (!form || !form.id) return;
    if (form.id === 'knowledgeForm') {
      event.preventDefault();
      return submitKnowledge(form);
    }
    if (form.id === 'searchForm') {
      event.preventDefault();
      return submitSearch(form);
    }
    if (form.id === 'agentForm') {
      event.preventDefault();
      const data = new FormData(form);
      return sendAgentMessage(data.get('content'));
    }
    if (form.id === 'inquiryForm') {
      event.preventDefault();
      return submitInquiry(form);
    }
    if (form.id === 'leadForm') {
      event.preventDefault();
      return submitLead(form);
    }
    if (form.id === 'runForm') {
      event.preventDefault();
      return runWorkflowForm(form);
    }
    if (form.id === 'retryForm') {
      event.preventDefault();
      return submitRetry(form);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => { boot().catch(toastErr); });
  } else {
    boot().catch(toastErr);
  }
})();
