/* 验收驾驶舱：把 config/acceptance.json 的 11 条验收项跑成真实证据。
   服务端负责静态检查（文件/源码/人工基线/unittest），浏览器负责 http 与 scenario 两类真实请求，
   两边结果在本页合并成一份 run，落库后可导出 Markdown 证据包。 */
(function () {
  'use strict';

  const UI = window.UI;
  const $ = UI.$;
  const j = UI.escapeHtml;

  const state = {
    cfg: null,
    staticResult: null,
    staticMap: {},
    probes: {},
    moduleProbes: {},
    scenarios: {},
    run: null,
    runs: [],
    packs: [],
    busy: false,
    lastExport: null,
    progress: [],
  };

  const TONE = { passed: 'green', failed: 'red', skipped: 'amber', deferred: 'muted', partial: 'amber' };
  const LABEL = { passed: '通过', failed: '未通过', skipped: '跳过', deferred: '待执行', partial: '部分完成' };
  const TYPE_LABEL = {
    file: '文件存在', filecount: '素材数量', grep: '源码关键字', m1cases: '人工规则基线',
    tests: '单元测试', http: '在线接口', scenario: '全链路场景',
  };
  const MODULE_LABEL = {
    m1: 'M1 工作站', m2: 'M2 预售与派单', ai: 'B 企业 AI 服务层', ip: 'C 文化 IP 短剧管线', ALL: '全部模块',
  };

  function errorText(err) {
    if (!err) return '未知错误';
    if (err.payload && (err.payload.message || err.payload.error)) return err.payload.message || err.payload.error;
    return err.message || String(err);
  }

  function statusTag(status) {
    if (!status) return UI.tag('未运行', 'muted');
    return UI.tag(LABEL[status] || status, TONE[status] || '');
  }

  function pct(n, d) {
    if (!d) return '0%';
    return Math.round((n / d) * 100) + '%';
  }

  function toneClass(status) {
    if (status === 'passed') return 'is-ok';
    if (status === 'failed') return 'is-fail';
    if (status === 'skipped' || status === 'deferred') return 'is-expected';
    return '';
  }

  function durationText(ms) {
    const v = Number(ms || 0);
    if (v < 1000) return v + 'ms';
    return (v / 1000).toFixed(1) + 's';
  }

  function bytes(n) {
    const v = Number(n || 0);
    if (v >= 1024 * 1024) return (v / 1024 / 1024).toFixed(2) + ' MB';
    if (v >= 1024) return (v / 1024).toFixed(1) + ' KB';
    return v + ' B';
  }

  function scenarioOf(moduleKey) {
    return state.scenarios[moduleKey] || null;
  }

  function scenariosFromRun(run) {
    const out = {};
    ((run && run.items) || []).forEach(function (item) {
      (item.checks || []).forEach(function (check) {
        if (check.type === 'scenario' && check.artifact && check.artifact.module) {
          out[check.artifact.module] = check.artifact;
        }
      });
    });
    return out;
  }

  async function probe(path) {
    const started = Date.now();
    try {
      const response = await fetch(path, { headers: { Accept: 'application/json' }, cache: 'no-store' });
      let body = null;
      try { body = await response.json(); } catch (err) { body = null; }
      const ok = response.ok && !(body && body.ok === false);
      return { path: path, ok: ok, status: response.status, durationMs: Date.now() - started, at: new Date().toISOString() };
    } catch (err) {
      return { path: path, ok: false, status: 0, durationMs: Date.now() - started, error: String(err && err.message || err), at: new Date().toISOString() };
    }
  }

  async function probeModules() {
    const modules = (state.cfg && state.cfg.modules) || {};
    const keys = Object.keys(modules);
    for (const key of keys) {
      const item = modules[key] || {};
      const result = await probe(item.config || '/api/health');
      result.label = item.label || key;
      result.config = item.config;
      result.scenario = item.scenario;
      state.moduleProbes[key] = result;
    }
    const httpPaths = [];
    ((state.cfg && state.cfg.items) || []).forEach(function (item) {
      (item.checks || []).forEach(function (spec) {
        if (spec.type === 'http' && spec.path && httpPaths.indexOf(spec.path) < 0) httpPaths.push(spec.path);
      });
    });
    for (const p of httpPaths) state.probes[p] = await probe(p);
    return state.moduleProbes;
  }

  async function runScenario(moduleKey) {
    const modules = (state.cfg && state.cfg.modules) || {};
    const endpoint = modules[moduleKey] && modules[moduleKey].scenario;
    if (!endpoint) return null;
    const started = Date.now();
    try {
      const payload = await UI.api(endpoint, { method: 'POST', body: { role: 'admin' } });
      return {
        module: moduleKey, endpoint: endpoint, ok: payload.ok === true,
        scenario: payload.scenario || '', steps: payload.steps || [], summary: payload.summary || null,
        generatedAt: payload.generatedAt || '', durationMs: Date.now() - started,
      };
    } catch (err) {
      return {
        module: moduleKey, endpoint: endpoint, ok: false, steps: [], summary: null,
        error: errorText(err), durationMs: Date.now() - started,
      };
    }
  }

  function progressEntry(title, note, status) {
    state.progress.push({ title: title, note: note || '', status: status || 'running' });
    renderProgress();
  }

  function renderProgress() {
    const box = $('#progressTrace');
    if (!box) return;
    box.innerHTML = state.progress.map(function (row) {
      const mark = row.status === 'passed' ? '✓' : (row.status === 'failed' ? '✗' : '…');
      return '<li class="result-item ' + toneClass(row.status === 'passed' ? 'passed' : (row.status === 'failed' ? 'failed' : 'skipped')) + '">' +
        '<span class="result-index">' + mark + '</span>' +
        '<div><div class="result-title">' + j(row.title) + '</div>' +
        '<div class="result-meta">' + j(row.note || (row.status === 'running' ? '执行中…' : '')) + '</div></div>' +
        '<span class="result-flag">' + j(row.status === 'passed' ? '完成' : (row.status === 'failed' ? '失败' : '进行中')) + '</span>' +
        '</li>';
    }).join('');
  }

  async function step(title, fn) {
    progressEntry(title, '', 'running');
    try {
      const note = await fn();
      state.progress[state.progress.length - 1].status = 'passed';
      state.progress[state.progress.length - 1].note = note || '';
      renderProgress();
      return note;
    } catch (err) {
      state.progress[state.progress.length - 1].status = 'failed';
      state.progress[state.progress.length - 1].note = errorText(err);
      renderProgress();
      throw err;
    }
  }

  function buildRun(label) {
    const items = ((state.cfg && state.cfg.items) || []).map(function (item) {
      const checks = (item.checks || []).map(function (spec) {
        return evaluateCheck(item, spec);
      });
      const failed = checks.filter(function (c) { return c.status === 'failed'; }).length;
      const skipped = checks.filter(function (c) { return c.status === 'skipped'; }).length;
      const status = failed > 0 ? 'failed' : (skipped > 0 ? 'partial' : 'passed');
      return {
        id: item.id, ref: item.ref, title: item.title, milestone: item.milestone, module: item.module,
        requirement: item.requirement, status: status,
        passedChecks: checks.filter(function (c) { return c.status === 'passed'; }).length,
        totalChecks: checks.length, checks: checks,
      };
    });
    const tests = (state.staticResult && state.staticResult.checks || []).filter(function (c) { return c.type === 'tests'; })[0];
    const scenarios = {};
    Object.keys(state.scenarios).forEach(function (key) {
      const sc = state.scenarios[key];
      if (!sc) return;
      scenarios[key] = {
        endpoint: sc.endpoint, ok: sc.ok, steps: (sc.steps || []).length,
        expectedFailures: sc.summary && sc.summary.expectedFailures, durationMs: sc.durationMs,
      };
    });
    return {
      runId: '',
      label: label || '全量自检',
      generatedAt: new Date().toISOString(),
      items: items,
      tests: tests ? tests.artifact : null,
      manifest: (state.staticResult && state.staticResult.manifest) || [],
      environment: (state.staticResult && state.staticResult.environment) || {},
      probes: state.probes,
      scenarios: scenarios,
    };
  }

  function evaluateCheck(item, spec) {
    const kind = spec.type;
    const label = spec.label || TYPE_LABEL[kind] || kind;
    if (kind === 'http') {
      const probeResult = state.probes[spec.path];
      if (!probeResult) {
        return { label: label, type: kind, status: 'skipped', detail: '未探测（先运行一次在线探测）', artifact: null };
      }
      return {
        label: label, type: kind, status: probeResult.ok ? 'passed' : 'failed',
        detail: probeResult.ok ? ('HTTP ' + probeResult.status + ' · ' + spec.path) : ('HTTP ' + probeResult.status + ' · 请求失败'),
        artifact: probeResult,
      };
    }
    if (kind === 'scenario') {
      const sc = scenarioOf(spec.module);
      const minSteps = Number(spec.minSteps || 1);
      if (!sc) {
        return { label: label, type: kind, status: 'skipped', detail: '未运行模块场景', artifact: null };
      }
      const steps = (sc.steps || []).length;
      const expected = (sc.summary && sc.summary.expectedFailures) || 0;
      const ok = sc.ok === true && steps >= minSteps;
      const detail = ok
        ? (steps + ' 步全部按预期完成（其中 ' + expected + ' 步为预期拒绝），耗时 ' + (sc.durationMs / 1000).toFixed(1) + 's')
        : (sc.error || ('只跑到 ' + steps + ' 步，少于要求的 ' + minSteps + ' 步'));
      return { label: label, type: kind, status: ok ? 'passed' : 'failed', detail: detail, artifact: sc };
    }
    const hit = state.staticMap[item.id + '|' + kind + '|' + label];
    if (!hit) {
      return { label: label, type: kind, status: 'skipped', detail: '未执行静态检查', artifact: null };
    }
    return { label: label, type: kind, status: hit.status, detail: hit.detail, artifact: hit.artifact };
  }

  function parseStatic(result) {
    state.staticResult = result;
    state.staticMap = {};
    (result.checks || []).forEach(function (row) {
      state.staticMap[row.itemId + '|' + row.type + '|' + row.label] = row;
    });
  }

  function renderMeta() {
    const box = $('#acceptanceMeta');
    if (!box || !state.cfg) return;
    const cfg = state.cfg;
    const total = (cfg.items || []).length;
    box.innerHTML = '<span>平台验收任务：' + j(cfg.platformTask || 'ClawHunt #1724') + '</span>' +
      '<span>映射版本 ' + j(cfg.version || '-') + ' · ' + total + ' 条验收项 · 更新 ' + j(cfg.updatedAt || '-') + '</span>' +
      '<span>编号 0)~10) 为任务书原文；A01–A10 是本仓库自拟对照编号，仅作内部索引</span>';
  }

  function renderKpis() {
    const box = $('#kpis');
    if (!box) return;
    const run = state.run;
    const items = (run && run.items) || [];
    const total = ((state.cfg && state.cfg.items) || []).length;
    const passedItems = items.filter(function (it) { return it.status === 'passed'; }).length;
    const failedItems = items.filter(function (it) { return it.status === 'failed'; }).length;
    const checks = [];
    items.forEach(function (it) { (it.checks || []).forEach(function (c) { checks.push(c); }); });
    const passedChecks = checks.filter(function (c) { return c.status === 'passed'; }).length;
    const scenarioSteps = Object.keys(state.scenarios).reduce(function (sum, key) {
      const sc = state.scenarios[key];
      return sum + ((sc && sc.steps) ? sc.steps.length : 0);
    }, 0);
    const cards = [
      ['通过验收项', items.length ? (passedItems + ' / ' + total) : '—', items.length ? ('未通过 ' + failedItems + ' 项 · ' + pct(passedItems, total)) : '尚未运行自检'],
      ['检查项通过率', checks.length ? (passedChecks + ' / ' + checks.length) : '—', checks.length ? ('全部检查中 ' + pct(passedChecks, checks.length) + ' 通过') : '静态 + 接口 + 场景合并统计'],
      ['模块场景步数', items.length ? String(scenarioSteps) : '—', 'M2 / B / C 三套全链路实际执行的步骤'],
      ['证据包', String(state.packs.length), state.lastExport ? ('最新：' + state.lastExport.filename) : '一键自检后可导出 Markdown'],
      ['最近运行', run ? UI.time(run.generatedAt) : '—', run ? ('运行编号 ' + (run.runId || '未落库')) : '点右上角「一键全量自检」'],
    ];
    box.innerHTML = cards.map(function (row) {
      return '<div class="kpi-card"><div class="kpi-top"><span>' + j(row[0]) + '</span></div>' +
        '<div class="kpi-value">' + j(row[1]) + '</div>' +
        '<div class="kpi-foot">' + j(row[2]) + '</div></div>';
    }).join('');
  }

  function renderModules() {
    const box = $('#modules');
    const chip = $('#moduleChip');
    if (!box) return;
    const modules = (state.cfg && state.cfg.modules) || {};
    const keys = Object.keys(modules);
    box.innerHTML = keys.map(function (key) {
      const item = modules[key] || {};
      const probeResult = state.moduleProbes[key];
      const ok = probeResult && probeResult.ok;
      const status = probeResult ? (ok ? '在线' : '不可用') : '未探测';
      return '<div class="panel">' +
        '<div class="subhead"><h3>' + j(item.label || key) + '</h3>' + UI.tag(status, probeResult ? (ok ? 'green' : 'red') : 'muted') + '</div>' +
        '<div class="kv-list">' + UI.kv([
          ['配置接口', '<code>' + j(item.config || '-') + '</code>'],
          ['场景接口', item.scenario ? '<code>' + j(item.scenario) + '</code>' : '—（M1 只有页面与 API）'],
          ['探测结果', probeResult ? ('HTTP ' + probeResult.status + ' · ' + probeResult.durationMs + 'ms') : '尚未探测'],
        ]) + '</div>' +
        (item.scenario ? '<p class="mini-note">该模块的全链路场景会在「一键全量自检」里真实执行一次。</p>' : '') +
        '</div>';
    }).join('');
    if (chip) chip.textContent = Object.keys(state.moduleProbes).length ? (Object.keys(state.moduleProbes).filter(function (k) { return state.moduleProbes[k].ok; }).length + ' / ' + keys.length + ' 在线') : '未探测';
  }

  function artifactBlock(check) {
    const art = check.artifact;
    if (!art) return '';
    if (check.type === 'm1cases' && art.rows) {
      const rows = art.rows.map(function (row) {
        return '<tr><td>' + j(row.id) + '</td><td>' + j(row.title) + '</td><td>' + j(row.expected) + '</td><td>' + j(row.actual) + '</td><td>' + (row.matched ? '一致' : '不一致') + '</td></tr>';
      }).join('');
      return '<details class="doc-block"><summary>展开 10 条人工规则基线</summary><div class="table-wrap"><table class="data-table"><thead><tr><th>编号</th><th>概念输入</th><th>人工预期</th><th>系统判定</th><th>是否一致</th></tr></thead><tbody>' + rows + '</tbody></table></div></details>';
    }
    if (check.type === 'tests') {
      const tail = (art.outputTail || []).slice(-40).join('\n');
      return '<details class="doc-block"><summary>展开测试输出（' + j(art.ran) + ' 例，退出码 ' + j(art.exitCode) + '）</summary><pre>' + j(tail) + '</pre></details>';
    }
    if (check.type === 'scenario') {
      const steps = art.steps || [];
      if (!steps.length) return '<p class="mini-note">' + j(art.error || '没有执行步骤') + '</p>';
      const rows = steps.map(function (row, idx) {
        const status = row.ok ? 'passed' : (row.expectError ? 'skipped' : 'failed');
        const flag = row.ok ? '通过' : (row.expectError ? '预期拒绝' : '失败');
        const meta = row.ok ? ((row.result && row.result.summary) || '') : (row.message || row.error || '');
        return '<div class="result-item ' + toneClass(status) + '"><span class="result-index">' + (idx + 1) + '</span>' +
          '<div><div class="result-title">' + j(row.title || '') + '</div><div class="result-meta">' + j(typeof meta === 'string' ? meta : JSON.stringify(meta)) + '</div></div>' +
          '<span class="result-flag">' + flag + '</span></div>';
      }).join('');
      return '<details class="doc-block"><summary>展开 ' + steps.length + ' 步场景证据（' + durationText(art.durationMs) + '）</summary><div class="scenario-steps">' + rows + '</div></details>';
    }
    if (check.type === 'grep' && art.matches) {
      const rows = art.matches.map(function (m) { return '<div class="kv-row"><span>L' + m.line + '</span><code>' + j(m.text) + '</code></div>'; }).join('');
      return '<details class="doc-block"><summary>展开命中行</summary><div class="kv-list">' + rows + '</div></details>';
    }
    if (check.type === 'filecount') {
      const files = (art || []).map(function (row) { return row.path + '（' + bytes(row.bytes) + '）'; });
      if (!files.length) return '';
      return '<details class="doc-block"><summary>展开素材清单</summary><p class="mini-note">' + j(files.join('　')) + '</p></details>';
    }
    if (check.type === 'file' || check.type === 'http') {
      const text = art.sha256 ? (art.path + ' · ' + bytes(art.bytes) + ' · sha256 ' + art.sha256.slice(0, 16) + '…') : JSON.stringify(art);
      return '<p class="mini-note">' + j(text) + '</p>';
    }
    return '';
  }

  function renderItems() {
    const box = $('#items');
    const chip = $('#itemsChip');
    if (!box || !state.cfg) return;
    const runItems = (state.run && state.run.items) || null;
    const items = runItems || (state.cfg.items || []).map(function (item) {
      return {
        id: item.id, ref: item.ref, title: item.title, milestone: item.milestone, module: item.module,
        requirement: item.requirement, status: '', passedChecks: 0, totalChecks: (item.checks || []).length,
        checks: (item.checks || []).map(function (spec) {
          return { label: spec.label, type: spec.type, status: '', detail: '尚未运行', artifact: null };
        }),
      };
    });
    box.innerHTML = items.map(function (item) {
      const rows = (item.checks || []).map(function (check) {
        return '<tr><td>' + j(check.label) + '</td><td>' + j(TYPE_LABEL[check.type] || check.type) + '</td>' +
          '<td>' + (check.status ? statusTag(check.status) : UI.tag('未运行', 'muted')) + '</td>' +
          '<td class="table-sub">' + j(check.detail || '') + artifactBlock(check) + '</td></tr>';
      }).join('');
      const summary = (!runItems)
        ? '<span class="server-chip">未运行</span>'
        : statusTag(item.status) + '<span class="server-chip">' + item.passedChecks + ' / ' + item.totalChecks + ' 检查</span>';
      return '<article class="panel">' +
        '<div class="panel-head"><div>' +
        '<div class="panel-kicker">' + j(item.id) + ' · 对应任务书 ' + j(item.ref) + ' · ' + j(item.milestone || '-') + ' · ' + j(MODULE_LABEL[item.module] || item.module || '-') + '</div>' +
        '<h2>' + j(item.title) + '</h2>' +
        '<p class="panel-copy">' + j(item.requirement) + '</p>' +
        '</div><div class="page-actions">' + summary + '</div></div>' +
        '<div class="table-wrap"><table class="data-table"><thead><tr><th>检查项</th><th>方式</th><th>结果</th><th>证据</th></tr></thead><tbody>' + rows + '</tbody></table></div>' +
        '</article>';
    }).join('');
    if (chip) {
      const total = items.length;
      const passed = items.filter(function (it) { return it.status === 'passed'; }).length;
      chip.textContent = runItems ? (passed + ' / ' + total + ' 项通过') : (total + ' 项待运行');
    }
  }

  function renderRuns() {
    const box = $('#runsTable');
    const chip = $('#runsChip');
    if (!box) return;
    const body = box.querySelector('tbody');
    if (!state.runs.length) {
      body.innerHTML = '<tr><td colspan="3" class="table-empty">尚未运行</td></tr>';
    } else {
      body.innerHTML = state.runs.map(function (row) {
        const selected = state.run && state.run.runId === row.runId;
        return '<tr data-run-id="' + j(row.runId) + '" class="' + (selected ? 'is-selected' : '') + '">' +
          '<td>' + j(row.runId) + '<div class="table-sub">' + j(row.label || '') + '</div></td>' +
          '<td>' + (row.passedItems + ' / ' + row.totalItems) + '</td>' +
          '<td>' + j(UI.time(row.generatedAt)) + '</td></tr>';
      }).join('');
    }
    if (chip) chip.textContent = state.runs.length + ' 次';
  }

  function renderPacks() {
    const box = $('#packs');
    const count = $('#packCount');
    if (!box) return;
    if (count) count.textContent = state.packs.length + ' 个';
    if (!state.packs.length) {
      box.innerHTML = '<p class="empty-copy">还没有导出过证据包。运行一次全量自检后点「导出证据包」。</p>';
      return;
    }
    box.innerHTML = state.packs.map(function (pack) {
      return '<div class="kv-row"><span><a href="/data/evidence/packs/' + encodeURIComponent(pack.name) + '" download>' + j(pack.name) + '</a></span>' +
        '<strong>' + bytes(pack.bytes) + ' · ' + j(UI.time(pack.modifiedAt)) + '</strong></div>';
    }).join('');
  }

  function renderAll() {
    renderMeta();
    renderKpis();
    renderModules();
    renderItems();
    renderRuns();
    renderPacks();
    const btn = $('#btnExport');
    if (btn) btn.disabled = !(state.run && state.run.runId && !state.busy);
  }

  async function loadConfig() {
    const cfg = await UI.api('/api/evidence/config');
    state.cfg = cfg;
    state.packs = cfg.packs || [];
  }

  async function loadRuns() {
    try {
      const payload = await UI.api('/api/evidence/runs');
      state.runs = (payload.runs || []).slice();
    } catch (err) {
      state.runs = [];
    }
    renderRuns();
  }

  async function loadPacks() {
    try {
      const payload = await UI.api('/api/evidence/packs');
      state.packs = payload.packs || [];
    } catch (err) {
      state.packs = [];
    }
    renderPacks();
  }

  function setBusy(isBusy, title) {
    state.busy = isBusy;
    const panel = $('#progressPanel');
    if (panel) panel.hidden = !isBusy && state.progress.length === 0;
    if (title && $('#progressTitle')) $('#progressTitle').textContent = title;
    const chip = $('#progressChip');
    if (chip) chip.textContent = isBusy ? '运行中' : '已完成';
    UI.busy($('#btnRunAll'), isBusy, '自检运行中…');
    UI.busy($('#btnStatic'), isBusy, '运行中…');
    const btnExport = $('#btnExport');
    if (btnExport) btnExport.disabled = true;
    if (!isBusy) renderAll();
  }

  async function fullCheck() {
    if (state.busy) return;
    state.progress = [];
    state.lastExport = null;
    if ($('#packPreview')) $('#packPreview').hidden = true;
    setBusy(true, '全量自检：静态检查 → 模块探测 → 三套场景 → 汇总落库');
    try {
      await step('① 服务端静态检查：文件体积 / 源码关键字 / 人工规则基线 / unittest', async function () {
        const result = await UI.api('/api/evidence/static-run', { method: 'POST', body: {} });
        parseStatic(result);
        const rows = result.checks || [];
        const passed = rows.filter(function (c) { return c.status === 'passed'; }).length;
        const failed = rows.filter(function (c) { return c.status === 'failed'; }).length;
        return '静态检查：' + passed + ' 通过 · ' + failed + ' 未通过 · ' + rows.filter(function (c) { return c.status === 'deferred'; }).length + ' 项交给浏览器';
      });
      await step('② 在线探测：M1 / M2 / B / C 的配置接口与验收用到的 HTTP 端点', async function () {
        await probeModules();
        const modules = Object.keys(state.moduleProbes);
        const online = modules.filter(function (k) { return state.moduleProbes[k].ok; }).length;
        return online + ' / ' + modules.length + ' 个模块在线，' + Object.keys(state.probes).length + ' 个 HTTP 端点已探测';
      });
      const moduleKeys = ['m2', 'ai', 'ip'];
      for (let idx = 0; idx < moduleKeys.length; idx += 1) {
        const key = moduleKeys[idx];
        const module = (state.cfg.modules || {})[key];
        if (!module || !module.scenario) continue;
        try {
          await step('③.' + (idx + 1) + ' ' + MODULE_LABEL[key] + ' 全链路场景（会重置该模块演示数据）', async function () {
            const sc = await runScenario(key);
            state.scenarios[key] = sc;
            if (!sc) return '该模块未声明场景接口';
            const steps = (sc.steps || []).length;
            if (!sc.ok) throw new Error(sc.error || ('场景失败：' + steps + ' 步'));
            return steps + ' 步完成，其中 ' + ((sc.summary && sc.summary.expectedFailures) || 0) + ' 步为预期拒绝，耗时 ' + durationText(sc.durationMs);
          });
        } catch (err) {
          state.scenarios[key] = state.scenarios[key] || {
            module: key, endpoint: (module && module.scenario) || '', ok: false, steps: [], summary: null,
            error: errorText(err), durationMs: 0,
          };
        }
      }
      await step('④ 汇总 11 条验收项并写入运行记录', async function () {
        const run = buildRun('全量自检');
        const stored = await UI.api('/api/evidence/record', { method: 'POST', body: { run: run } });
        run.runId = stored.runId;
        state.run = run;
        const passedItems = run.items.filter(function (it) { return it.status === 'passed'; }).length;
        await loadRuns();
        return '运行 ' + stored.runId + ' 已落库：' + passedItems + ' / ' + run.items.length + ' 项通过';
      });
      UI.toast('全量自检完成，可导出证据包');
    } catch (err) {
      UI.toast('自检中断：' + errorText(err), 'error');
    } finally {
      setBusy(false);
      renderAll();
    }
  }

  async function staticCheck() {
    if (state.busy) return;
    state.progress = [];
    setBusy(true, '仅静态检查：不跑场景、不影响演示数据');
    try {
      await step('① 服务端静态检查', async function () {
        const result = await UI.api('/api/evidence/static-run', { method: 'POST', body: {} });
        parseStatic(result);
        const rows = result.checks || [];
        return rows.filter(function (c) { return c.status === 'passed'; }).length + ' 通过 · ' + rows.filter(function (c) { return c.status === 'failed'; }).length + ' 未通过';
      });
      await step('② 汇总并写入运行记录（场景与在线检查标记为跳过）', async function () {
        state.scenarios = {};
        state.probes = {};
        const run = buildRun('仅静态检查');
        const stored = await UI.api('/api/evidence/record', { method: 'POST', body: { run: run } });
        run.runId = stored.runId;
        state.run = run;
        await loadRuns();
        return '静态结论已落库：' + stored.runId;
      });
      UI.toast('静态检查完成（场景未运行，如实标记为跳过）');
    } catch (err) {
      UI.toast('静态检查失败：' + errorText(err), 'error');
    } finally {
      setBusy(false);
      renderAll();
    }
  }

  async function exportPack() {
    if (!state.run || !state.run.runId) {
      UI.toast('先跑一次自检再导出', 'error');
      return;
    }
    UI.busy($('#btnExport'), true, '导出中…');
    try {
      const payload = await UI.api('/api/evidence/export', { method: 'POST', body: { runId: state.run.runId } });
      state.lastExport = payload;
      const preview = $('#packPreview');
      const markdown = $('#packMarkdown');
      if (markdown) markdown.textContent = payload.markdown || '';
      if (preview) preview.hidden = false;
      await loadPacks();
      renderAll();
      UI.toast('证据包已写入 ' + payload.path);
    } catch (err) {
      UI.toast('导出失败：' + errorText(err), 'error');
    } finally {
      UI.busy($('#btnExport'), false);
      renderAll();
    }
  }

  async function resetCockpit() {
    if (!window.confirm('重置会清空运行记录与已导出的证据包（不影响 M1/M2/B/C 演示数据），继续？')) return;
    try {
      await UI.api('/api/evidence/demo/reset', { method: 'POST', body: {} });
      state.run = null;
      state.staticResult = null;
      state.staticMap = {};
      state.probes = {};
      state.moduleProbes = {};
      state.scenarios = {};
      state.progress = [];
      state.lastExport = null;
      if ($('#progressPanel')) $('#progressPanel').hidden = true;
      if ($('#packPreview')) $('#packPreview').hidden = true;
      await loadRuns();
      await loadPacks();
      renderAll();
      UI.toast('验收驾驶舱数据已重置');
    } catch (err) {
      UI.toast('重置失败：' + errorText(err), 'error');
    }
  }

  async function loadRun(runId) {
    try {
      const payload = await UI.api('/api/evidence/runs/' + encodeURIComponent(runId));
      const run = payload.run;
      state.run = run;
      state.scenarios = scenariosFromRun(run);
      state.probes = run.probes || {};
      renderAll();
      const meta = $('#progressPanel');
      if (meta) meta.hidden = true;
      UI.toast('已载入历史运行 ' + runId);
    } catch (err) {
      UI.toast('载入失败：' + errorText(err), 'error');
    }
  }

  function bind() {
    $('#btnRunAll').addEventListener('click', fullCheck);
    $('#btnStatic').addEventListener('click', staticCheck);
    $('#btnExport').addEventListener('click', exportPack);
    $('#btnReset').addEventListener('click', resetCockpit);
    document.addEventListener('click', function (event) {
      const row = event.target.closest('[data-run-id]');
      if (row) loadRun(row.getAttribute('data-run-id'));
    });
  }

  async function init() {
    bind();
    try {
      await loadConfig();
      renderMeta();
      renderItems();
      await probeModules();
      renderModules();
      renderKpis();
      await loadRuns();
      await loadPacks();
      const latest = state.runs[0];
      if (latest) {
        try {
          const payload = await UI.api('/api/evidence/runs/' + encodeURIComponent(latest.runId));
          state.run = payload.run;
          state.scenarios = scenariosFromRun(state.run);
          state.probes = state.run.probes || state.probes;
        } catch (err) { /* 历史记录读取失败不影响主流程 */ }
      }
      renderAll();
      if (!latest) renderItems();
      const params = new URLSearchParams(window.location.search);
      if (params.get('autorun') === '1') {
        await fullCheck();
        if (params.get('export') === '1') await exportPack();
      }
    } catch (err) {
      const box = $('#items');
      if (box) box.innerHTML = '<p class="empty-copy">加载失败：' + j(errorText(err)) + '（请确认服务已重启并加载 mod_evidence.py）</p>';
    }
  }

  init();
})();
