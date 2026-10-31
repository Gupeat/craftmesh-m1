/* M2 · C2M 预售与制造协同 页面逻辑（全部数据来自本地 API） */
(() => {
  const { $, api, escapeHtml: esc, money, pct, time, tag, statusTag, toast, role, busy } = UI;

  const state = {
    config: null, dashboard: null,
    campaigns: [], orders: [], ledger: [], events: [],
    campaignDetail: null, orderDetail: null,
    capability: null, scenario: null,
    selectedCampaignId: null, selectedOrderId: null,
    capWorkshopId: null, capDimension: 60,
  };

  const post = (path, body) => api(path, { method: 'POST', body: Object.assign({ role: role() }, body || {}) });
  const cfg = () => state.config || {};
  const procLabel = (key) => (cfg().processLabels || {})[key] || key;
  const orderLabel = (key) => (cfg().orderStatusLabels || {})[key] || key;
  const campLabel = (key) => (cfg().campaignStatusLabels || {})[key] || key;
  const roleLabel = (key) => (cfg().actors || {})[key] || key;
  const need = (cap) => ((cfg().permissions || {})[cap] || []).map((p) => p.label).join(' / ') || '-';
  const j = (value) => esc(String(value == null ? '-' : value));

  async function bootstrap() {
    try {
      state.config = await api('/api/m2/config');
      renderFormFields();
      renderRoleStrip();
      const form = $('#createCampaignForm');
      if (form) form.dataset.action = 'create-campaign';
      const scenarioBtn = $('#btnScenario');
      if (scenarioBtn) scenarioBtn.addEventListener('click', () => runAction('run-scenario', {}, scenarioBtn));
      const resetBtn = $('#btnReset');
      if (resetBtn) resetBtn.addEventListener('click', () => runAction('reset-demo', {}, resetBtn));
      await refresh();
    } catch (err) {
      toast('M2 接口不可用：' + err.message, 'error');
    }
  }

  async function refresh() {
    const res = await Promise.all([
      api('/api/m2/dashboard'), api('/api/m2/campaigns'), api('/api/m2/production-orders'),
      api('/api/m2/ledger'), api('/api/m2/events'),
    ]);
    state.dashboard = res[0].dashboard;
    state.campaigns = res[1].campaigns || [];
    state.orders = res[2].orders || [];
    state.ledger = res[3].ledger || [];
    state.events = res[4].events || [];
    if (!state.campaigns.some((c) => c.id === state.selectedCampaignId)) {
      state.selectedCampaignId = state.campaigns.length ? state.campaigns[0].id : null;
    }
    if (!state.orders.some((o) => o.id === state.selectedOrderId)) {
      state.selectedOrderId = state.orders.length ? state.orders[0].id : null;
    }
    await Promise.all([loadCampaign(), loadOrder()]);
    renderAll();
  }

  async function loadCampaign() {
    state.campaignDetail = state.selectedCampaignId ? await api('/api/m2/campaigns/' + state.selectedCampaignId) : null;
  }

  async function loadOrder() {
    state.orderDetail = state.selectedOrderId ? await api('/api/m2/production-orders/' + state.selectedOrderId) : null;
    const order = state.orderDetail && state.orderDetail.order;
    if (order && order.status === 'created') {
      if (!state.capWorkshopId) state.capWorkshopId = ((cfg().workshops || [])[0] || {}).id;
      await refreshCapability();
    } else {
      state.capability = null;
    }
  }

  async function refreshCapability() {
    const order = state.orderDetail && state.orderDetail.order;
    if (!order) { state.capability = null; return; }
    try {
      state.capability = await post('/api/m2/production-orders/' + order.id + '/capability', {
        workshopId: state.capWorkshopId, dimensionMm: state.capDimension,
      });
    } catch (err) {
      state.capability = null;
    }
  }

  function renderAll() {
    renderKpis(); renderScenario(); renderCampaigns(); renderCampaignDetail();
    renderOrder(); renderCapability(); renderLedger(); renderEvents();
  }

  function renderFormFields() {
    const c = cfg();
    const opt = (value, label) => '<option value="' + j(value) + '">' + j(label) + '</option>';
    const patternOpts = (c.patterns || []).map((p) => opt(p.id, p.name + ' · ' + p.sourceLabel + ' · ' + p.licenseId)).join('');
    const procOpts = Object.keys(c.processLabels || {}).map((k) => opt(k, c.processLabels[k] + '（起订 ' + ((c.rules.minBatch || {})[k] || 10) + ' 份）')).join('');
    const matOpts = Object.keys(c.materialLabels || {}).map((k) => opt(k, c.materialLabels[k])).join('');
    const finOpts = Object.keys(c.finishLabels || {}).map((k) => opt(k, c.finishLabels[k])).join('');
    const box = $('#campaignFormFields');
    if (!box) return;
    box.innerHTML =
      '<label class="field"><span>纹样</span><select name="patternId">' + patternOpts + '</select></label>' +
      '<label class="field"><span>工艺</span><select name="process">' + procOpts + '</select></label>' +
      '<label class="field"><span>材料</span><select name="material">' + matOpts + '</select></label>' +
      '<label class="field"><span>表面处理</span><select name="finish">' + finOpts + '</select></label>' +
      '<label class="field"><span>每份件数</span><input name="quantityPerUnit" type="number" min="1" max="200" value="1"></label>' +
      '<label class="field"><span>预售天数</span><input name="deadlineDays" type="number" min="1" max="90" value="14"></label>' +
      '<label class="field"><span>标题（可选）</span><input name="title" placeholder="留空自动生成"></label>';
  }

  function renderKpis() {
    const d = state.dashboard || {};
    const c = d.campaigns || { total: 0, open: 0, funded: 0, pledgedDepositCents: 0 };
    const o = d.orders || { total: 0, inFlight: 0, settled: 0, grossCents: 0 };
    const l = d.ledger || { entries: 0, netCents: 0 };
    const cards = [
      ['预售活动', String(c.total), c.open + ' 进行中 · ' + c.funded + ' 已成团'],
      ['定金归集', money(c.pledgedDepositCents), '支持者定金累计（含成团后转工艺单）'],
      ['在制工艺单', String(o.inFlight), '共 ' + o.total + ' 张 · 已结算 ' + o.settled],
      ['交易总额', money(o.grossCents), '平台 25% / 授权 10% / 工坊余额'],
      ['台账净额', money(l.netCents), l.entries + ' 笔分账与退款'],
    ];
    const box = $('#kpis');
    if (box) box.innerHTML = cards.map((row) =>
      '<div class="kpi-card"><div class="kpi-top"><span>' + j(row[0]) + '</span></div>' +
      '<div class="kpi-value">' + row[1] + '</div>' +
      '<div class="kpi-foot">' + j(row[2]) + '</div></div>').join('');
  }

  function renderRoleStrip() {
    const r = role();
    const perms = cfg().permissions || {};
    const allowed = Object.keys(perms).filter((k) => (perms[k] || []).some((p) => p.role === r));
    const box = $('#roleStrip');
    if (!box) return;
    box.innerHTML = '<span>当前角色 <strong>' + j(roleLabel(r)) + '</strong></span><span class="dot-sep">·</span>' +
      '<span>可执行 ' + allowed.length + ' 项业务动作，其余请求由服务端拒绝（403）</span><span class="dot-sep">·</span>' +
      '<span>在右上角切换角色后重试同一操作，可验证权限确实生效</span>';
  }

  function renderScenario() {
    const chip = $('#scenarioChip');
    const body = $('#scenarioBody');
    if (!chip || !body) return;
    const s = state.scenario;
    if (!s) {
      chip.textContent = '未运行';
      body.innerHTML = '<p class="empty-copy">尚未运行。点击「一键跑通全链路」会在服务端重置 M2 数据并跑完 16 步，逐条返回结果与证据。</p>';
      return;
    }
    chip.textContent = '生成于 ' + time(s.generatedAt);
    const items = s.steps.map((step, index) => {
      const expected = step.expectError && !step.ok;
      const cls = step.ok ? 'is-ok' : expected ? 'is-expected' : 'is-fail';
      const flag = step.ok ? '通过' : expected ? '按预期拒绝' : '失败';
      const tone = step.ok ? 'green' : expected ? 'amber' : 'red';
      const meta = step.ok ? describeResult(step.result) : [step.message, describeChecks(step.extra)].filter(Boolean).join('；');
      return '<div class="result-item ' + cls + '"><div class="result-index">' + String(index + 1).padStart(2, '0') + '</div><div>' +
        '<div class="result-title">' + j(step.title) + '<span class="result-flag">' + tag(flag, tone) + '</span></div>' +
        (meta ? '<div class="result-meta">' + meta + '</div>' : '') + '</div></div>';
    }).join('');
    const summary = s.summary || {};
    body.innerHTML =
      '<div class="scenario-summary"><div><strong>' + (summary.passed || 0) + ' / ' + (summary.steps || 0) + '</strong> 步通过</div>' +
      '<div>预期失败 ' + (summary.expectedFailures || 0) + ' 步（能力校验拒绝）</div>' +
      '<div class="mono">campaign ' + j(summary.campaignId) + ' · order ' + j(summary.orderId) + '</div></div>' +
      '<div class="scenario-steps">' + items + '</div>';
  }

  function describeChecks(extra) {
    if (!extra || !extra.checks) return '';
    return '服务端校验未通过 —— ' + extra.checks.filter((c) => !c.ok).map((c) => c.name + '：' + c.detail).join('；');
  }

  function describeResult(result) {
    if (!result) return '';
    if (result.statusLabel && result.id) {
      const bits = ['预售 ' + j(result.id), '状态 ' + j(result.statusLabel), '累计 ' + (result.pledgedQty || 0) + '/' + (result.minBatch || 0) + ' 份'];
      if (result.productionOrderId) bits.push('工艺单 ' + j(result.productionOrderId));
      return bits.join('；');
    }
    const bits = [];
    const order = result.order;
    if (order && order.status) bits.push('工艺单 ' + j(order.id) + ' · ' + j(orderLabel(order.status)));
    if (result.workshopName) bits.push('派给 ' + j(result.workshopName));
    if (result.dispatch && result.dispatch.workshopName) bits.push('派单给 ' + j(result.dispatch.workshopName));
    if (result.settlement) bits.push('平台 ' + money(result.settlement.platformFeeCents) + ' / 授权 ' + money(result.settlement.licenseRoyaltyCents) + ' / 工坊 ' + money(result.settlement.workshopPayoutCents));
    if (result.dispute) bits.push('争议 ' + j(result.dispute.id) + ' · ' + j(result.dispute.status));
    if (result.ledger && result.ledger.length) bits.push(result.ledger.length + ' 条台账');
    return bits.join('；');
  }

  const CAMPAIGN_STEPS = [['draft', '草稿'], ['open', '预售中'], ['funded', '已成团'], ['in_production', '生产中'], ['completed', '已完成']];
  const ORDER_STEPS = [['created', '待派单'], ['dispatched', '已派单'], ['accepted', '已接单'], ['in_progress', '生产中'], ['qc_pending', '待质检'], ['qc_passed', '质检通过'], ['shipped', '已发货'], ['settled', '已结算']];

  function stepper(steps, status, extra) {
    if (extra && extra.cancelled) return '<div class="stepper"><div class="step is-cancelled"><span class="step-dot"></span>已取消</div></div>';
    const index = steps.findIndex((pair) => pair[0] === status);
    return '<div class="stepper">' + steps.map((pair, i) =>
      '<div class="step ' + (i < index ? 'is-done' : i === index ? 'is-current' : '') + '"><span class="step-dot"></span>' + pair[1] + '</div>').join('') + '</div>';
  }

  function renderCampaigns() {
    const body = document.querySelector('#campaignTable tbody');
    const chip = $('#campaignChip');
    if (chip) chip.textContent = state.campaigns.length + ' 条';
    if (!body) return;
    if (!state.campaigns.length) {
      body.innerHTML = '<tr><td colspan="3" class="table-empty">暂无预售活动，先创建一条草稿</td></tr>';
      return;
    }
    body.innerHTML = state.campaigns.map((c) => {
      const ratio = Math.min(100, Math.round((c.pledgedQty / Math.max(1, c.minBatch)) * 100));
      return '<tr class="' + (c.id === state.selectedCampaignId ? 'is-selected' : '') + '"><td>' +
        '<button class="row-button" data-action="select-campaign" data-id="' + j(c.id) + '">' + j(c.title) + '</button>' +
        '<div class="table-sub">' + j(c.id) + '</div></td>' +
        '<td><div class="progress-track"><div class="progress-fill ' + (ratio >= 100 ? 'is-done' : '') + '" style="width:' + ratio + '%"></div></div>' +
        '<div class="table-sub">' + c.pledgedQty + '/' + c.minBatch + ' 份 · 定金 ' + money(c.pledgedDepositCents) + '</div></td>' +
        '<td>' + statusTag(c.status, campLabel(c.status)) + '</td></tr>';
    }).join('');
  }

  function renderCampaignDetail() {
    const box = $('#campaignDetail');
    if (!box) return;
    const detail = state.campaignDetail;
    if (!detail || !detail.campaign) {
      box.innerHTML = '<p class="empty-copy">选择或创建一条预售活动查看详情。</p>';
      return;
    }
    const c = detail.campaign;
    const pledges = detail.pledges || [];
    const ratio = Math.min(100, Math.round((c.pledgedQty / Math.max(1, c.minBatch)) * 100));
    const license = c.licenseSnapshot || {};
    const scopeOk = (license.useScope || []).indexOf(license.use || 'commercial') >= 0;
    const sourceLabel = ((cfg().patterns || []).filter((p) => p.id === c.pattern.id)[0] || {}).sourceLabel || '';
    let actions = '';
    if (c.status === 'draft') {
      actions = '<div class="action-block"><p class="block-title">开放预售</p><div class="action-row">' +
        '<button class="btn btn-primary btn-small" data-action="open-campaign" data-id="' + j(c.id) + '">开放预售</button>' +
        '<span class="form-hint">需要角色：' + j(need('campaign.open')) + '</span></div></div>' +
        '<form class="inline-form" data-action="cancel-campaign" data-id="' + j(c.id) + '">' +
        '<label class="field"><span>取消原因</span><input name="reason" placeholder="可选"></label>' +
        '<button class="btn btn-small" type="submit">取消活动</button></form>';
    } else if (c.status === 'open') {
      const suggest = Math.max(1, c.minBatch - c.pledgedQty);
      actions = '<div class="action-block"><p class="block-title">支持者定金下单</p>' +
        '<form class="inline-form" data-action="pledge" data-id="' + j(c.id) + '">' +
        '<label class="field"><span>支持者</span><input name="backer" value="支持者 A（合成样例）" required></label>' +
        '<label class="field field-narrow"><span>份数</span><input name="qty" type="number" min="1" max="500" value="' + suggest + '"></label>' +
        '<button class="btn btn-primary btn-small" type="submit">付定金下单</button></form>' +
        '<p class="form-hint">需要角色：' + j(need('pledge.create')) + '；达到起订量 ' + c.minBatch + ' 份自动成团并生成工艺单，定金转制造款。</p></div>' +
        '<form class="inline-form" data-action="cancel-campaign" data-id="' + j(c.id) + '">' +
        '<label class="field"><span>取消原因</span><input name="reason" placeholder="未成团可取消并原路退回定金"></label>' +
        '<button class="btn btn-small" type="submit">取消活动</button></form>';
    } else if (c.productionOrderId) {
      actions = '<div class="action-block"><p class="block-title">已生成工艺单</p><div class="action-row">' +
        '<button class="btn btn-small" data-action="select-order" data-id="' + j(c.productionOrderId) + '">查看工艺单 ' + j(c.productionOrderId) + '</button></div></div>';
    }
    box.innerHTML =
      '<div class="detail-head"><div><div class="mono">' + j(c.id) + '</div><h3>' + j(c.title) + '</h3></div>' + statusTag(c.status, campLabel(c.status)) + '</div>' +
      stepper(CAMPAIGN_STEPS, c.status, { cancelled: c.status === 'cancelled' }) +
      '<div class="kv-list">' +
      '<div class="kv-row"><span>纹样</span><strong>' + j(c.pattern.name) + (sourceLabel ? ' · ' + j(sourceLabel) : '') + '</strong></div>' +
      '<div class="kv-row"><span>工艺 / 材料 / 表面</span><strong>' + j(procLabel(c.process)) + ' · ' + j((cfg().materialLabels || {})[c.material]) + ' · ' + j((cfg().finishLabels || {})[c.finish]) + '</strong></div>' +
      '<div class="kv-row"><span>单价（每份）</span><strong>' + money(c.unitCents) + ' × ' + c.quantityPerUnit + ' 件</strong></div>' +
      '<div class="kv-row"><span>定金比例</span><strong>' + pct(Math.round(c.depositPct * 10000)) + ' · ' + money(c.depositCentsPerUnit) + ' / 份</strong></div>' +
      '<div class="kv-row"><span>起订量</span><strong>' + c.minBatch + ' 份</strong></div>' +
      '<div class="kv-row"><span>预售截止</span><strong>' + time(c.deadlineAt) + '</strong></div></div>' +
      '<div class="license-box"><strong>授权快照</strong>　' + j(license.patternName || c.pattern.name) + '　来源：' + j(license.source || c.pattern.source) +
      '　许可：' + j(license.licenseId) + '<br>用途：' + j(license.use || 'commercial') + '　范围：' + j((license.useScope || []).join(' / ')) +
      '　衍生：' + (license.derivativeAllowed ? '允许' : '不允许') + '　校验：' + (scopeOk ? '<span class="ok">在授权范围内</span>' : '<span class="no">超出授权范围</span>') + '</div>' +
      '<div class="subhead" style="margin:14px 0 6px"><h3>支持者定金</h3><span class="mono muted">' + c.pledgedQty + '/' + c.minBatch + ' 份 · ' + money(c.pledgedDepositCents) + '</span></div>' +
      '<div class="progress-track"><div class="progress-fill ' + (ratio >= 100 ? 'is-done' : '') + '" style="width:' + ratio + '%"></div></div>' +
      (pledges.length
        ? '<div class="table-wrap" style="margin-top:10px"><table class="data-table"><thead><tr><th>支持者</th><th>份数</th><th>定金</th><th>时间</th></tr></thead><tbody>' +
          pledges.map((p) => '<tr><td>' + j(p.backer) + '</td><td>' + p.qty + '</td><td>' + money(p.depositCents) + '</td><td class="mono muted">' + time(p.createdAt) + '</td></tr>').join('') +
          '</tbody></table></div>'
        : '<p class="table-note">还没有定金记录。</p>') + actions;
  }

  function renderOrder() {
    const box = $('#orderDetail');
    const chip = $('#orderChip');
    if (chip) chip.textContent = state.orders.length + ' 条';
    if (!box) return;
    const detail = state.orderDetail;
    if (!detail || !detail.order) {
      box.innerHTML = '<p class="empty-copy">暂无工艺单。先让预售达到起订量，系统会自动成团并生成工艺单。</p>';
      return;
    }
    const order = detail.order;
    const dispatch = detail.dispatch;
    const disputes = detail.disputes || [];
    const quality = order.quality || { attempts: 0, reworkCount: 0, history: [] };
    let actions = '';
    if (order.status === 'created') {
      const opts = (cfg().workshops || []).map((w) => '<option value="' + j(w.id) + '">' + j(w.name) + '</option>').join('');
      actions = '<div class="action-block"><p class="block-title">派单给工坊</p>' +
        '<form class="inline-form" data-action="dispatch" data-id="' + j(order.id) + '">' +
        '<label class="field"><span>工坊</span><select name="workshopId" id="capWorkshop">' + opts + '</select></label>' +
        '<label class="field field-narrow"><span>尺寸 mm</span><input name="dimensionMm" type="number" min="1" max="5000" value="' + state.capDimension + '"></label>' +
        '<button class="btn btn-primary btn-small" type="submit">派单</button></form>' +
        '<p class="form-hint">需要角色：' + j(need('order.dispatch')) + '　派单前服务端复核 5 项能力，右侧为预检结果。</p></div>';
    } else if (order.status === 'dispatched' && dispatch) {
      actions = '<div class="action-block"><p class="block-title">等待工坊确认</p>' +
        '<div class="kv-list"><div class="kv-row"><span>派单号</span><strong>' + j(dispatch.id) + '</strong></div>' +
        '<div class="kv-row"><span>工坊</span><strong>' + j(dispatch.workshopName) + '</strong></div>' +
        '<div class="kv-row"><span>状态</span><strong>' + j((cfg().dispatchStatusLabels || {})[dispatch.status] || dispatch.status) + '</strong></div></div>' +
        '<div class="action-row"><button class="btn btn-primary btn-small" data-action="respond-accept" data-id="' + j(dispatch.id) + '">接单</button>' +
        '<button class="btn btn-small" data-action="respond-decline" data-id="' + j(dispatch.id) + '">拒单</button>' +
        '<span class="form-hint">需要角色：' + j(need('dispatch.respond')) + '</span></div></div>';
    } else if (order.status === 'accepted') {
      actions = actionBlock('工坊已接单', '开工', 'start', order.id, 'order.start');
    } else if (order.status === 'in_progress') {
      actions = actionBlock('生产中', '提交质检', 'submit-qc', order.id, 'order.qc');
    } else if (order.status === 'qc_pending') {
      actions = '<div class="action-block"><p class="block-title">质检结论</p>' +
        '<div class="action-row"><button class="btn btn-primary btn-small" data-action="qc-pass" data-id="' + j(order.id) + '">质检通过</button></div>' +
        '<form class="inline-form" data-action="qc-fail" data-id="' + j(order.id) + '">' +
        '<label class="field" style="flex:1;min-width:220px"><span>返工原因（必填）</span><input name="note" placeholder="如：边角有砂眼，需补蜡重铸" required></label>' +
        '<button class="btn btn-small" type="submit">不通过并返工</button></form>' +
        '<p class="form-hint">需要角色：' + j(need('order.qc')) + '；返工超过 ' + ((cfg().rules.quality || {}).reworkLimit || 2) + ' 次会升级为待处理。</p></div>';
    } else if (order.status === 'rework') {
      actions = actionBlock('返工中（第 ' + (quality.reworkCount || 1) + ' 次）', '返工完成，重新开工', 'start', order.id, 'order.start');
    } else if (order.status === 'qc_passed') {
      actions = '<div class="action-block"><p class="block-title">发货</p>' +
        '<form class="inline-form" data-action="ship" data-id="' + j(order.id) + '">' +
        '<label class="field"><span>承运商</span><input name="carrier" value="顺丰（合成）" required></label>' +
        '<label class="field"><span>运单号</span><input name="trackingNo" value="SF-DEMO-0001" required></label>' +
        '<button class="btn btn-primary btn-small" type="submit">确认发货</button></form>' +
        '<p class="form-hint">需要角色：' + j(need('order.ship')) + '</p></div>';
    } else if (order.status === 'shipped') {
      actions = '<div class="action-block"><p class="block-title">结算分账</p><div class="action-row">' +
        '<button class="btn btn-primary btn-small" data-action="settle" data-id="' + j(order.id) + '">按规则结算</button>' +
        '<span class="form-hint">需要角色：' + j(need('order.settle')) + '</span></div></div>' + disputeForm(order.id);
    } else if (order.status === 'settled') {
      actions = disputeForm(order.id);
    } else if (order.status === 'escalated') {
      actions = '<div class="action-block"><p class="block-title">返工超限，等待运营处理</p><p class="form-hint">返工上限 ' + ((cfg().rules.quality || {}).reworkLimit || 2) + ' 次已触发，可走争议或人工介入。</p></div>';
    }
    const shipment = order.shipment ? '<div class="kv-row"><span>发货</span><strong>' + j(order.shipment.carrier) + ' · ' + j(order.shipment.trackingNo) + '</strong></div>' : '';
    const settlement = order.settlement ? '<div class="kv-row"><span>分账</span><strong>平台 ' + money(order.settlement.platformFeeCents) + ' / 授权 ' + money(order.settlement.licenseRoyaltyCents) + ' / 工坊 ' + money(order.settlement.workshopPayoutCents) + '</strong></div>' : '';
    box.innerHTML =
      '<div class="detail-head"><div><div class="mono">' + j(order.id) + ' · 预售 ' + j(order.campaignId) + '</div><h3>' + j(order.patternName) + ' · ' + j(procLabel(order.process)) + ' · ' + order.qty + ' 份</h3></div>' + statusTag(order.status, orderLabel(order.status)) + '</div>' +
      stepper(ORDER_STEPS, order.status === 'rework' || order.status === 'escalated' ? 'qc_pending' : order.status, { cancelled: order.status === 'cancelled' }) +
      '<div class="kv-list">' +
      '<div class="kv-row"><span>材料 / 表面</span><strong>' + j((cfg().materialLabels || {})[order.material]) + ' · ' + j((cfg().finishLabels || {})[order.finish]) + '</strong></div>' +
      '<div class="kv-row"><span>单价 / 总额</span><strong>' + money(order.unitCents) + ' × ' + order.qty + ' = ' + money(order.grossCents) + '</strong></div>' +
      '<div class="kv-row"><span>已收定金</span><strong>' + money(order.depositCents) + '</strong></div>' +
      (dispatch ? '<div class="kv-row"><span>派单工坊</span><strong>' + j(dispatch.workshopName) + '</strong></div>' : '') + shipment + settlement + '</div>' +
      (quality.history && quality.history.length
        ? '<div class="subhead" style="margin-top:14px"><h3>质检记录</h3><span class="mono muted">返工 ' + (quality.reworkCount || 0) + ' 次</span></div>' +
          '<div class="table-wrap"><table class="data-table"><thead><tr><th>时间</th><th>结论</th><th>说明</th></tr></thead><tbody>' +
          quality.history.map((h) => '<tr><td class="mono muted">' + time(h.at) + '</td><td>' + (h.result === 'pass' ? '<span class="status-pill pass">通过</span>' : '<span class="status-pill fail">不通过</span>') + '</td><td>' + j(h.note) + '</td></tr>').join('') +
          '</tbody></table></div>'
        : '') +
      actions + renderDisputes(disputes);
  }

  function actionBlock(title, label, action, id, cap) {
    return '<div class="action-block"><p class="block-title">' + j(title) + '</p><div class="action-row">' +
      '<button class="btn btn-primary btn-small" data-action="' + action + '" data-id="' + j(id) + '">' + j(label) + '</button>' +
      '<span class="form-hint">需要角色：' + j(need(cap)) + '</span></div></div>';
  }

  function disputeForm(orderId) {
    return '<div class="action-block"><p class="block-title">买家发起争议</p>' +
      '<form class="inline-form" data-action="dispute" data-id="' + j(orderId) + '">' +
      '<label class="field field-narrow"><span>类型</span><select name="type"><option value="quality">质量</option><option value="timing">交期</option><option value="damage">破损</option></select></label>' +
      '<label class="field" style="flex:1;min-width:200px"><span>原因（至少 4 字）</span><input name="reason" value="收到后 2 件表面有轻微色差（演示数据）" required></label>' +
      '<button class="btn btn-small" type="submit">提交争议</button></form>' +
      '<p class="form-hint">需要角色：' + j(need('dispute.create')) + '</p></div>';
  }

  function renderDisputes(disputes) {
    if (!disputes.length) return '';
    const labels = { open: '待处理', resolved: '已结案', rejected: '已驳回' };
    return '<div class="action-block"><p class="block-title">争议记录</p>' + disputes.map((d) => {
      const open = d.status === 'open';
      return '<div class="doc-block" style="margin-bottom:8px"><strong>' + j(d.id) + '</strong>　' + j(d.type) + '　' + statusTag(d.status, labels[d.status] || d.status) + '<br>' + j(d.reason) +
        (d.refundCents ? '<br>退款 ' + money(d.refundCents) : '') +
        (open ? '<form class="inline-form" data-action="resolve-dispute" data-id="' + j(d.id) + '">' +
          '<label class="field field-narrow"><span>处理</span><select name="resolution"><option value="refund">退款</option><option value="rework">返工</option><option value="reject">驳回</option></select></label>' +
          '<label class="field field-narrow"><span>退款比例</span><input name="refundPct" type="number" min="0.05" max="1" step="0.05" value="0.3"></label>' +
          '<button class="btn btn-small" type="submit">结案</button></form>' : '') + '</div>';
    }).join('') + '<p class="form-hint">需要角色：' + j(need('dispute.resolve')) + '</p></div>';
  }

  function renderCapability() {
    const box = $('#capabilityPanel');
    if (!box) return;
    const order = state.orderDetail && state.orderDetail.order;
    if (!order || order.status !== 'created') {
      box.innerHTML = '<div class="doc-block"><strong>工坊公开能力</strong><br>' + (cfg().workshops || []).map((w) =>
        j(w.name) + '：' + (w.processes || []).map(procLabel).join('/') + ' · ' +
        (w.materials || []).map((m) => (cfg().materialLabels || {})[m]).join('/') +
        ' · ≤' + w.maxDimensionMm + 'mm · 起订 ' + w.minOrderQty + ' · 交期 ' + w.leadDays + ' 天').join('<br>') +
        '</div><p class="mini-note">能力来自 config/workshops.json，为合成样例。</p>';
      return;
    }
    const cap = state.capability;
    const checks = (cap && cap.checks) || [];
    box.innerHTML = '<div class="subhead"><h3>派单能力预检</h3><span class="server-chip">' + (cap ? (cap.passed ? '全部通过' : '存在不匹配') : '预检中') + '</span></div>' +
      '<div class="doc-block"><strong>' + j(cap ? cap.workshopName : '选择工坊') + '</strong>　尺寸 ' + (cap ? cap.dimensionMm + 'mm' : '-') +
      '<div class="check-list">' + checks.map((c) => '<div class="check-row ' + (c.ok ? 'is-ok' : 'is-fail') + '"><span class="check-mark">' + (c.ok ? '✓' : '✗') + '</span><div><strong>' + j(c.name) + '</strong>　' + j(c.detail) + '</div></div>').join('') + '</div></div>' +
      '<p class="mini-note">与派单接口共用同一套校验函数；预检不写任何状态，真正派单时服务端会再校验一次。</p>';
  }

  const LEDGER_LABELS = { deposit: '定金', platform_fee: '平台服务费', license_royalty: '授权分成', workshop_payout: '工坊结算', refund_buyer: '买家退款', workshop_adjust: '工坊调整' };
  const PARTY_LABELS = { buyer: '买家', platform: '平台', license_owner: '授权方', workshop: '工坊' };
  const LEDGER_CLASS = { deposit: 'amount-pos', platform_fee: 'amount-pos', license_royalty: 'amount-pos', workshop_payout: 'amount-pos', refund_buyer: 'amount-neg', workshop_adjust: 'amount-neg' };

  function renderLedger() {
    const body = document.querySelector('#ledgerTable tbody');
    const chip = $('#ledgerChip');
    if (chip) chip.textContent = state.ledger.length + ' 笔';
    if (!body) return;
    if (!state.ledger.length) { body.innerHTML = '<tr><td colspan="4" class="table-empty">暂无台账记录</td></tr>'; return; }
    body.innerHTML = state.ledger.map((entry) =>
      '<tr><td class="mono muted">' + time(entry.createdAt) + '</td>' +
      '<td>' + j(LEDGER_LABELS[entry.type] || entry.type) + '</td>' +
      '<td class="mono muted">' + j(entry.ref) + '<br>' + j(PARTY_LABELS[entry.party] || entry.party) + '</td>' +
      '<td class="' + (LEDGER_CLASS[entry.type] || 'amount-zero') + '">' + (entry.amountCents >= 0 ? '+' : '') + money(entry.amountCents) + '</td></tr>').join('');
  }

  function renderEvents() {
    const box = $('#eventTimeline');
    const chip = $('#eventChip');
    if (!box) return;
    const rows = state.events.slice(0, 20);
    if (chip) chip.textContent = rows.length ? '最近 ' + rows.length + ' 条' : '暂无';
    if (!rows.length) { box.innerHTML = '<p class="empty-copy">暂无审计记录</p>'; return; }
    box.innerHTML = rows.map((e) =>
      '<div class="timeline-item"><span class="timeline-dot"></span><div class="timeline-content">' +
      '<div class="timeline-title"><span>' + j(e.label) + '</span><span class="timeline-time">' + time(e.at) + '</span></div>' +
      '<div class="timeline-note">' + j(e.scope) + ' · ' + j(e.ref) + ' · ' + j(roleLabel(e.role)) + (e.note ? ' · ' + j(e.note) : '') + (e.from || e.to ? ' · ' + j(e.from || '-') + ' → ' + j(e.to || '-') : '') + '</div></div></div>').join('');
  }

  async function runAction(action, data, button) {
    busy(button, true);
    try {
      if (action === 'run-scenario') {
        state.scenario = await post('/api/m2/scenario');
        state.capWorkshopId = null; state.capDimension = 60;
        await refresh();
        toast('全链路已跑完：' + state.scenario.summary.passed + '/' + state.scenario.summary.steps + ' 步通过，' + state.scenario.summary.expectedFailures + ' 步按预期被拒绝');
      } else if (action === 'reset-demo') {
        await post('/api/m2/demo/reset');
        state.scenario = null; state.selectedCampaignId = null; state.selectedOrderId = null; state.capWorkshopId = null;
        await refresh();
        toast('M2 演示数据已清空');
      } else if (action === 'select-campaign') {
        state.selectedCampaignId = data.id;
        await loadCampaign();
        renderCampaigns(); renderCampaignDetail(); return;
      } else if (action === 'select-order') {
        state.selectedOrderId = data.id; state.capWorkshopId = null;
        await loadOrder();
        renderOrder(); renderCapability(); return;
      } else if (action === 'create-campaign') {
        const created = await post('/api/m2/campaigns', {
          patternId: data.patternId, process: data.process, material: data.material, finish: data.finish,
          quantityPerUnit: Number(data.quantityPerUnit || 1), deadlineDays: Number(data.deadlineDays || 14),
          title: data.title || undefined,
        });
        state.selectedCampaignId = created.campaign.id;
        await refresh();
        toast('预售草稿已创建：' + created.campaign.id);
      } else if (action === 'open-campaign') {
        await post('/api/m2/campaigns/' + data.id + '/open');
        await refresh(); toast('预售已开放');
      } else if (action === 'cancel-campaign') {
        await post('/api/m2/campaigns/' + data.id + '/cancel', { reason: data.reason || '' });
        await refresh(); toast('预售已取消，已付定金按规则退回');
      } else if (action === 'pledge') {
        const result = await post('/api/m2/campaigns/' + data.id + '/pledge', { backer: data.backer, qty: Number(data.qty || 1) });
        await refresh();
        toast(result.campaign.pledgedQty >= result.campaign.minBatch ? '下单成功，已达到起订量并自动成团' : '下单成功');
      } else if (action === 'dispatch') {
        const result = await post('/api/m2/production-orders/' + data.id + '/dispatch', { workshopId: data.workshopId, dimensionMm: Number(data.dimensionMm || 60) });
        state.capWorkshopId = data.workshopId; state.capDimension = Number(data.dimensionMm || 60);
        await refresh(); toast('已派单给 ' + result.dispatch.workshopName + '，等待工坊确认');
      } else if (action === 'respond-accept' || action === 'respond-decline') {
        const accept = action === 'respond-accept';
        await post('/api/m2/dispatches/' + data.id + '/respond', { accept: accept, note: accept ? '工坊确认接单' : '工坊拒单' });
        await refresh(); toast(accept ? '工坊已接单' : '工坊已拒单，工艺单回到待派单');
      } else if (action === 'start') {
        await post('/api/m2/production-orders/' + data.id + '/start');
        await refresh(); toast('已开工');
      } else if (action === 'submit-qc') {
        await post('/api/m2/production-orders/' + data.id + '/submit-qc');
        await refresh(); toast('已提交质检');
      } else if (action === 'qc-pass') {
        await post('/api/m2/production-orders/' + data.id + '/qc', { result: 'pass', note: '抽检 5 件外观合格' });
        await refresh(); toast('质检通过，可安排发货');
      } else if (action === 'qc-fail') {
        await post('/api/m2/production-orders/' + data.id + '/qc', { result: 'fail', note: data.note });
        await refresh(); toast('质检不通过，工艺单已转返工');
      } else if (action === 'ship') {
        await post('/api/m2/production-orders/' + data.id + '/ship', { carrier: data.carrier, trackingNo: data.trackingNo });
        await refresh(); toast('已发货，等待结算');
      } else if (action === 'settle') {
        const result = await post('/api/m2/production-orders/' + data.id + '/settle');
        await refresh();
        toast('已分账：平台 ' + money(result.settlement.platformFeeCents) + ' / 授权 ' + money(result.settlement.licenseRoyaltyCents) + ' / 工坊 ' + money(result.settlement.workshopPayoutCents));
      } else if (action === 'dispute') {
        await post('/api/m2/disputes', { orderId: data.id, type: data.type, reason: data.reason });
        await refresh(); toast('争议已提交，等待财务处理');
      } else if (action === 'resolve-dispute') {
        const result = await post('/api/m2/disputes/' + data.id + '/resolve', {
          resolution: data.resolution, refundPct: Number(data.refundPct || 0.3), note: '按 ' + data.resolution + ' 结案',
        });
        await refresh(); toast(result.dispute && result.dispute.status === 'resolved' ? '争议已结案' : '争议已处理');
      }
    } catch (err) {
      toast(err.message || '操作失败', 'error');
      if (err.payload && err.payload.checks) {
        state.capability = Object.assign({ workshopName: '', dimensionMm: state.capDimension }, err.payload);
        renderCapability();
      }
    } finally {
      busy(button, false);
    }
  }

  const CLICK_ACTIONS = ['run-scenario', 'reset-demo', 'open-campaign', 'select-campaign', 'select-order',
    'respond-accept', 'respond-decline', 'start', 'submit-qc', 'qc-pass', 'settle'];

  document.addEventListener('click', (event) => {
    const target = event.target.closest('[data-action]');
    if (!target) return;
    if (target.tagName === 'FORM') return;
    if (target.tagName === 'BUTTON' && target.type === 'submit') return;
    if (CLICK_ACTIONS.indexOf(target.dataset.action) === -1) return;
    runAction(target.dataset.action, Object.assign({}, target.dataset), target);
  });

  document.addEventListener('submit', (event) => {
    const form = event.target.closest('form[data-action]');
    if (!form) return;
    event.preventDefault();
    const data = Object.fromEntries(new FormData(form).entries());
    Object.assign(data, form.dataset);
    runAction(form.dataset.action, data, form.querySelector('button[type=submit]'));
  });

  document.addEventListener('change', (event) => {
    if (event.target.id === 'capWorkshop') {
      state.capWorkshopId = event.target.value;
      refreshCapability().then(renderCapability);
    }
  });

  document.addEventListener('craft-role-change', () => {
    renderRoleStrip();
    toast('已切换为「' + roleLabel(role()) + '」，越权操作会被服务端拒绝');
  });

  bootstrap();
})();
