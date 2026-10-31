/* ============================================================
   CraftMesh · C 文化 IP 短剧管线
   页面逻辑：角色 / 分镜 / 播放器 / 审核 / 授权 / 自检
   无外部依赖；所有数据来自本地 /api/ip/*
   ============================================================ */
(function () {
  'use strict';

  var U = window.UI;
  if (!U) {
    console.error('[ip] UI 未加载，页面无法初始化');
    return;
  }

  function $(selector, root) { return (root || document).querySelector(selector); }
  function $$(selector, root) { return Array.prototype.slice.call((root || document).querySelectorAll(selector)); }
  function j(value) { return U.escapeHtml(value == null ? '' : String(value)); }
  function tag(label, tone) {
    if (U.tag) return U.tag(label, tone);
    return '<span class="tag">' + j(label) + '</span>';
  }
  function toast(message, tone) {
    if (U.toast) U.toast(message, tone);
    else console.log('[ip] ' + message);
  }
  function busy(element, on) {
    if (U.busy) U.busy(element, on);
    else if (element) element.disabled = !!on;
  }
  function post(path, body) {
    return U.api(path, { method: 'POST', body: Object.assign({ role: U.role() }, body || {}) });
  }
  function setText(id, text) {
    var element = document.getElementById(id);
    if (element) element.textContent = text == null ? '' : String(text);
  }
  function pad(value) {
    value = String(value);
    return value.length < 2 ? '0' + value : value;
  }
  function clip(text, max) {
    text = text == null ? '' : String(text);
    max = max || 100;
    return text.length > max ? text.slice(0, max - 1) + '…' : text;
  }
  function fmtSeconds(ms) {
    if (!ms && ms !== 0) return '—';
    return (Math.round(Number(ms) / 100) / 10).toFixed(1) + ' 秒';
  }
  function fmtDuration(ms) {
    if (!ms && ms !== 0) return '—';
    return (Math.round(Number(ms) / 100) / 10).toFixed(1) + 's';
  }
  function fmtClock(ms) {
    ms = Math.max(0, Number(ms) || 0);
    var totalTenths = Math.floor(ms / 100);
    var minutes = Math.floor(totalTenths / 600);
    var seconds = Math.floor((totalTenths % 600) / 10);
    var tenths = totalTenths % 10;
    return pad(minutes) + ':' + pad(seconds) + '.' + tenths;
  }
  function fmtBytes(bytes) {
    if (!bytes && bytes !== 0) return '—';
    if (bytes >= 1048576) return (bytes / 1048576).toFixed(2) + ' MB';
    if (bytes >= 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return bytes + ' B';
  }
  function fmtYuan(cents) {
    if (cents == null || isNaN(Number(cents))) return '—';
    return '¥' + (Number(cents) / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function fmtPct(bps) {
    if (bps == null || isNaN(Number(bps))) return '—';
    var value = Number(bps) / 100;
    return (Math.round(value * 10) / 10).toFixed(1).replace(/\.0$/, '') + '%';
  }
  function when(iso) {
    if (!iso) return '—';
    var date = new Date(iso);
    if (isNaN(date.getTime())) return String(iso);
    return pad(date.getMonth() + 1) + '-' + pad(date.getDate()) + ' ' + pad(date.getHours()) + ':' + pad(date.getMinutes());
  }
  function safeColor(value, fallback) {
    return /^#[0-9a-fA-F]{6}$/.test(String(value || '')) ? String(value) : fallback;
  }

  var ROLE_FALLBACK = {
    designer: '设计师',
    ops: '生产运营',
    workshop: '工坊',
    finance: '财务',
    buyer: '买家 / 支持者',
    admin: '管理员'
  };
  var KIND_LABELS = {
    scene: '场景 SVG',
    voice: '分镜配音',
    subtitle: '分镜字幕',
    character: '角色设定',
    poster: '主视觉',
    master_audio: '总配音',
    master_subtitle: '总字幕'
  };
  var SEVERITY_LABELS = { blocker: '阻断', major: '重要', minor: '提示' };
  var SEVERITY_TONES = { blocker: 'red', major: 'amber', minor: 'muted' };
  var RESULT_LABELS = {
    module: '模块', version: '版本', characters: '角色', shots: '分镜', beats: '节拍',
    reviewRules: '审核规则', licenseClauses: '合同条款', skus: 'SKU', canCounts: '能力数',
    cannotCounts: '禁区数', coverage: '覆盖镜号', titles: '场标题', fieldsPerShot: '每格字段',
    first: '首格', speakers: '说话人', duration: '时长', summary: '汇总', checks: '校验',
    totalMs: '时间轴', totalSeconds: '总秒数', masterMs: '主音轨', masterSrtCues: '总字幕条数',
    contiguous: '连续', audioTotalMs: '配音合计', allAudioFits: '配音入槽', clips: '片段',
    sampleRates: '采样率', minMs: '最短片段', maxMs: '最长片段', detail: '明细',
    masterCues: '总字幕条数', shotSrt: '分镜字幕', firstCue: '首条字幕', masterBytes: '主音轨字节',
    reviewId: '审核记录', verdict: '结论', findings: '命中', reviewedAt: '审核时间',
    rules: '规则', labels: '标签', count: '数量', verdicts: '结论分布', ids: '记录编号',
    licenseId: '授权编号', draftNo: '合同编号', licensee: '被许可方', purpose: '用途',
    territory: '区域', termMonths: '期限', clauses: '条款', baseFee: '基础授权费',
    disclaimer: '声明', status: '状态', error: '错误', message: '说明', missing: '缺失',
    simulated: '模拟注入', ok: '结果', total: '合计', passed: '通过', steps: '步骤',
    expectedFailures: '预期失败', durationOk: '时长校验', reviewPass: '合规文案',
    reviewReject: '违规文案', licenseNo: '合同编号', assets: '素材', templates: '模板'
  };

  var state = {
    config: null,
    story: null,
    manifest: null,
    assets: null,
    dashboard: null,
    reviews: null,
    licenses: null,
    derivatives: null,
    scenario: null,
    totalMs: 0,
    activeIndex: 0,
    playerReady: false,
    playing: false,
    atEnd: false,
    pendingSeekMs: null,
    imageTimer: null,
    scenarioRunning: false,
    lastLicense: null,
    audioObjectUrl: null,
    audioBlobLoading: false
  };

  function roleName(role) {
    var actors = state.config && state.config.actors ? state.config.actors : null;
    var actor = actors ? actors[role] : null;
    if (typeof actor === 'string') return actor;
    if (actor && actor.label) return actor.label;
    return ROLE_FALLBACK[role] || role;
  }
  function permissionMap() {
    return (state.config && state.config.permissionMap) || {};
  }
  function allowedRoles(capability) {
    var map = permissionMap();
    return Array.isArray(map[capability]) ? map[capability] : [];
  }
  function roleCan(capability) {
    return allowedRoles(capability).indexOf(U.role()) >= 0;
  }

  function renderRoleStrip() {
    var box = $('#roleStrip');
    if (!box) return;
    var current = U.role();
    var map = permissionMap();
    var labels = (state.config && state.config.capabilityLabels) || {};
    var allowed = Object.keys(map).filter(function (capability) {
      return (map[capability] || []).indexOf(current) >= 0;
    });
    var text = allowed.map(function (capability) { return labels[capability] || capability; });
    box.innerHTML = '<span>当前角色 <strong>' + j(roleName(current)) + '</strong></span>' +
      '<span class="dot-sep">·</span>' +
      '<span>可执行 ' + allowed.length + ' 项业务动作：' + (text.length ? j(text.join('、')) : '只读查看') + '</span>' +
      '<span class="dot-sep">·</span>' +
      '<span>权限由服务端逐次校验，越权请求返回 403，不会只靠前端隐藏按钮</span>';
  }

  function updateRoleHints() {
    var reviewAllowed = allowedRoles('content.review');
    var licenseAllowed = allowedRoles('license.preview');
    var current = U.role();
    var reviewHint = $('#reviewRoleHint');
    var reviewNeeded = $('#reviewNeeded');
    var licenseNeeded = $('#licenseNeeded');
    if (reviewHint) {
      reviewHint.textContent = roleName(current) + (roleCan('content.review')
        ? ' · 可提交审核'
        : ' · 无审核权限，提交将被 403 拒绝');
    }
    if (reviewNeeded) {
      reviewNeeded.textContent = reviewAllowed.length
        ? reviewAllowed.map(roleName).join(' / ')
        : '尚未配置（服务端会拒绝）';
    }
    if (licenseNeeded) {
      licenseNeeded.textContent = '需要 ' + (licenseAllowed.length ? licenseAllowed.map(roleName).join(' / ') : '—') +
        '；当前 ' + roleName(current) + '，越权生成将被拒绝。';
    }
  }

  function fillLicenseSelects() {
    var license = (state.config && state.config.license) || {};
    setSelectOptions($('#licensePurpose'), license.purposes || [], function (item) { return item; });
    setSelectOptions($('#licenseTerritory'), license.territories || [], function (item) { return item; });
    setSelectOptions($('#licenseTerm'), license.termOptions || [], function (item) { return item + ' 个月'; });
  }

  function setSelectOptions(select, items, labeler) {
    if (!select) return;
    var previous = select.value;
    select.innerHTML = items.map(function (item) {
      return '<option value="' + j(item) + '">' + j(labeler(item)) + '</option>';
    }).join('');
    if (items.some(function (item) { return String(item) === previous; })) {
      select.value = previous;
    } else if (items.length) {
      select.selectedIndex = 0;
    }
  }

  function renderCharacters() {
    var box = $('#charactersGrid');
    if (!box) return;
    var characters = (state.config && state.config.characters) || [];
    if (!characters.length) {
      box.innerHTML = '<p class="empty-copy">尚未读取角色设定，请检查 /api/ip/config。</p>';
      return;
    }
    box.innerHTML = characters.map(function (character, index) {
      var color = safeColor((character.palette || [])[0], index === 0 ? '#0f3b3a' : '#8f3f2e');
      var can = (character.can || []).map(function (item) { return '<li>' + j(item) + '</li>'; }).join('');
      var cannot = (character.cannot || []).map(function (item) { return '<li>' + j(item) + '</li>'; }).join('');
      var motifs = (character.motifs || []).map(function (item) { return '<span class="tag">' + j(item) + '</span>'; }).join('');
      var voice = character.voice || {};
      return '<article class="ip-character-card" style="--ch:' + color + '">' +
        '<div class="ip-character-portrait">' +
          '<img src="' + j(character.portrait) + '" alt="' + j(character.name) + ' 角色设定卡（自制 SVG）" loading="lazy">' +
          '<span class="ip-character-symbol">' + j(character.symbol || character.roman) + '</span>' +
        '</div>' +
        '<div class="ip-character-body">' +
          '<div class="ip-character-top">' +
            '<div><div class="ip-character-role">' + j(character.role) + ' · ' + (index === 0 ? '视觉角色' : '听觉角色') + '</div>' +
            '<h3>' + j(character.name) + ' <small>' + j(character.roman) + '</small></h3></div>' +
            tag(index === 0 ? '原创' : '原创', 'green') +
          '</div>' +
          '<p class="ip-character-tagline">' + j(character.tagline) + '</p>' +
          '<p class="ip-character-setting">' + j(character.setting) + '</p>' +
          '<div class="ip-character-motifs">' + motifs + '</div>' +
          '<div class="ip-character-abilities">' +
            '<div><span class="ip-ability-label">能</span><ul>' + can + '</ul></div>' +
            '<div class="is-cannot"><span class="ip-ability-label is-cannot">不能</span><ul>' + cannot + '</ul></div>' +
          '</div>' +
          '<div class="ip-character-voice"><strong>声音画像 · ' + j(voice.sapiVoice || '本机语音') + ' / rate ' + j(voice.rate) + '</strong>' +
            j(voice.profile || '') +
            (voice.sampleLine ? '<br><em>「' + j(voice.sampleLine) + '」</em>' : '') +
          '</div>' +
        '</div>' +
      '</article>';
    }).join('');
    setText('characterChip', characters.length + ' 个原创角色 · 能与不能均写入配置');
  }

  function renderKpis() {
    var box = $('#kpis');
    if (!box) return;
    var dashboard = state.dashboard || {};
    var config = state.config || {};
    var manifest = state.manifest || {};
    var media = config.media || {};
    var counts = dashboard.reviews || {};
    var reviewTotal = counts.total != null ? counts.total : (state.reviews && state.reviews.total) || 0;
    var reviewPass = counts.pass != null ? counts.pass : (state.reviews && state.reviews.counts && state.reviews.counts.pass) || 0;
    var reviewReject = counts.reject != null ? counts.reject : (state.reviews && state.reviews.counts && state.reviews.counts.reject) || 0;
    var reviewRevise = counts.revise != null ? counts.revise : (state.reviews && state.reviews.counts && state.reviews.counts.revise) || 0;
    var totalMs = dashboard.totalMs || manifest.totalMs || media.totalMs || 0;
    var durationOk = !!(dashboard.durationOk || manifest.durationOk || media.durationOk);
    var lastVerdict = dashboard.lastReviewVerdict || '';
    var lastVerdictLabel = dashboard.reviews && lastVerdict === 'pass' ? '最新通过' :
      lastVerdict === 'reject' ? '最新拒绝' : lastVerdict === 'revise' ? '最新需修改' : '暂无留痕';
    var lastVerdictTone = lastVerdict === 'pass' ? 'green' : lastVerdict === 'reject' ? 'red' : lastVerdict === 'revise' ? 'amber' : 'muted';
    var assets = dashboard.assets || (state.assets && state.assets.summary) || {};
    var cards = [
      {
        label: '原创角色 / 设定', value: (dashboard.characters || (config.characters && config.characters.length) || 0),
        unit: '个', chip: '双原创', tone: 'green',
        foot: (dashboard.beats || (config.story && config.story.beats && config.story.beats.length) || 0) + ' 场剧本 · 外观 / 声音 / 边界'
      },
      {
        label: '分镜格数', value: (dashboard.shots || (state.story && state.story.shots && state.story.shots.length) || 0),
        unit: '格', chip: '≥ 10', tone: 'green', foot: '每格含画面 / 镜头 / 台词 / 音效'
      },
      {
        label: '样片总时长', value: totalMs ? (Math.round(totalMs / 100) / 10).toFixed(1) : '—',
        unit: '秒', chip: durationOk ? '区间通过' : '待校验', tone: durationOk ? 'green' : 'amber',
        foot: '30–45 秒硬性区间 · 逐格累加校验'
      },
      {
        label: '自制素材', value: assets.total != null ? assets.total : '—',
        unit: '项', chip: assets.missing ? (assets.missing + ' 缺失') : '0 缺失',
        tone: assets.missing ? 'red' : 'green',
        foot: (assets.scenes || 0) + ' SVG · ' + (assets.voices || 0) + ' WAV · ' + (assets.subtitles || 0) + ' SRT'
      },
      {
        label: '审核留痕', value: reviewTotal, unit: '条',
        chip: lastVerdictLabel, tone: lastVerdictTone,
        foot: '通过 ' + reviewPass + ' · 需修改 ' + reviewRevise + ' · 拒绝 ' + reviewReject
      },
      {
        label: '授权草稿', value: dashboard.licenses != null ? dashboard.licenses : (state.licenses && state.licenses.total) || 0,
        unit: '份', chip: '模板', tone: 'muted',
        foot: dashboard.lastLicenseNo ? clip(dashboard.lastLicenseNo, 26) : '尚未生成合同草稿'
      },
      {
        label: '衍生品 SKU', value: dashboard.skus || (config.derivatives && config.derivatives.count) || 0,
        unit: '个', chip: '待授权', tone: 'amber', foot: '规格 / 起订量 / 建议零售价 / 分成'
      },
      {
        label: '本地规则审核', value: dashboard.reviewRules || (config.review && config.review.rules && config.review.rules.length) || 0,
        unit: '条', chip: '确定性', tone: 'green', foot: '关键词 + 否定词 + 豁免词 · 无外部模型'
      }
    ];
    box.innerHTML = cards.map(function (card) {
      return '<div class="kpi-card">' +
        '<div class="kpi-top"><span>' + j(card.label) + '</span>' + tag(card.chip, card.tone) + '</div>' +
        '<div class="kpi-value">' + j(card.value) + '<small>' + j(card.unit) + '</small></div>' +
        '<div class="kpi-foot">' + j(card.foot) + '</div>' +
      '</div>';
    }).join('');
  }

  function renderStoryMeta() {
    var data = state.story || {};
    var duration = data.duration || {};
    var shots = (data.shots || []).length;
    var totalMs = duration.totalMs || (state.config && state.config.media && state.config.media.totalMs) || 0;
    var badge = $('#durationBadge');
    if (badge) {
      badge.innerHTML = tag(duration.ok === false ? '校验失败' : '区间通过', duration.ok === false ? 'red' : 'green') +
        ' 总时长 ' + fmtSeconds(totalMs) + ' · ' + shots + ' 格';
    }
    var notes = [];
    if (data.story && Array.isArray(data.story.scriptNotes)) notes = notes.concat(data.story.scriptNotes);
    notes.push('剧本、角色与台词均为原创合成样例；山谷为虚构地点，不对应真实非遗项目或真实人物。');
    var noteBox = $('#storyNotes');
    if (noteBox) noteBox.textContent = notes.join(' ');
  }

  function renderBeats() {
    var box = $('#beatsGrid');
    if (!box) return;
    var story = (state.story && state.story.story) || (state.config && state.config.story) || {};
    var beats = Array.isArray(story.beats) ? story.beats : [];
    if (!beats.length) {
      box.innerHTML = '<p class="empty-copy">剧本节拍加载中…</p>';
      return;
    }
    box.innerHTML = beats.map(function (beat, index) {
      var shotTags = (beat.shots || []).map(function (shot) {
        return '<span>' + pad(shot) + '</span>';
      }).join('');
      return '<article class="ip-beat">' +
        '<div class="ip-beat-no">BEAT ' + pad(beat.no || index + 1) + '</div>' +
        '<h3>' + j(beat.title) + '</h3>' +
        '<p>' + j(beat.summary) + '</p>' +
        '<div class="ip-beat-shots">' + shotTags + '</div>' +
      '</article>';
    }).join('');
  }

  function renderShotTable() {
    var body = $('#shotTableBody');
    if (!body) return;
    var shots = (state.story && state.story.shots) || [];
    if (!shots.length) {
      body.innerHTML = '<tr><td colspan="6" class="table-empty">分镜加载中…</td></tr>';
      return;
    }
    var maxDuration = shots.reduce(function (max, shot) { return Math.max(max, Number(shot.durationMs) || 0); }, 1);
    body.innerHTML = shots.map(function (shot) {
      var width = Math.max(8, Math.round((Number(shot.durationMs) || 0) / maxDuration * 100));
      var characters = (shot.characters || []).map(function (name) { return '<span class="tag">' + j(name) + '</span>'; }).join('');
      return '<tr>' +
        '<td class="ip-td-shot"><span class="ip-shot-no">' + pad(shot.no) + '</span>' +
          '<span class="ip-shot-scene">' + j(shot.id || '') + '</span></td>' +
        '<td><div class="ip-cell-main">' + j(shot.scene) + '</div><div class="ip-cell-sub">场景类型：' + j(shot.sceneType || '—') + '</div></td>' +
        '<td><div class="ip-duration"><b>' + fmtDuration(shot.durationMs) + '</b>' +
          '<span class="ip-duration-track"><i style="width:' + width + '%"></i></span></div></td>' +
        '<td><div class="ip-cell-main">' + j(shot.visual) + '</div><div class="ip-cell-sub">镜头：' + j(shot.camera) + '</div></td>' +
        '<td><div class="ip-cell-caption">' + j(shot.speaker || '旁白') + '</div><div class="ip-cell-chars">' + characters + '</div></td>' +
        '<td><div class="ip-cell-caption">「' + j(shot.caption) + '」</div><div class="ip-cell-sfx">♪ ' + j(shot.sfx) + '</div></td>' +
      '</tr>';
    }).join('');
  }

  async function loadConfig() {
    var data = await U.api('/api/ip/config');
    state.config = data;
    var module = data.module || {};
    var media = data.media || {};
    var title = (data.story && data.story.title) || module.title || '山谷回声';
    document.title = 'CraftMesh · C 文化 IP 短剧管线 · ' + title;
    setText('playerTitle', title);
    setText('playerDurationChip', '总时长 ' + fmtSeconds(media.totalMs || 0) + ' · ' + (media.durationOk ? '30–45s 通过' : '待校验'));
    setText('playerFormatChip', (media.voiceName || '本机语音') + ' · WAV · ' + (media.shotCount || 12) + ' 段');
    setText('reviewNeeded', '—');
    renderCharacters();
    renderRoleStrip();
    updateRoleHints();
    fillLicenseSelects();
    var reviewText = $('#reviewText');
    if (reviewText && !reviewText.value.trim() && data.review && data.review.samples) {
      reviewText.value = data.review.samples.pass || '';
    }
    updateReviewChars();
  }

  async function loadStory() {
    var data = await U.api('/api/ip/story');
    state.story = data;
    renderBeats();
    renderShotTable();
    renderStoryMeta();
  }

  function renderAssetSummary(summary, manifest) {
    var box = $('#assetSummary');
    if (!box) return;
    summary = summary || {};
    var timelineMs = (manifest && manifest.totalMs) || state.totalMs || 0;
    var masterMs = summary.masterAudioMs || (manifest && manifest.master && manifest.master.durationMs) || 0;
    var rates = summary.sampleRates || [];
    var audioTotal = summary.audioTotalMs || (manifest && manifest.audioTotalMs) || 0;
    var wideText = fmtSeconds(masterMs) + ' 主音轨 / ' + fmtSeconds(timelineMs) + ' 时间轴 · 误差 ≤ 120ms';
    box.innerHTML =
      '<div class="ip-asset-stat"><span>素材总数</span><strong>' + j(summary.total != null ? summary.total : '—') + '</strong><em>清单读取</em></div>' +
      '<div class="ip-asset-stat"><span>存在 / 缺失</span><strong>' + j(summary.present != null ? summary.present : '—') + ' / ' + j(summary.missing != null ? summary.missing : '—') + '</strong><em>' + (summary.missing ? '需要修复' : '全部可读') + '</em></div>' +
      '<div class="ip-asset-stat"><span>场景 SVG</span><strong>' + j(summary.scenes || 0) + '</strong><em>12 格分镜</em></div>' +
      '<div class="ip-asset-stat"><span>分镜配音 WAV</span><strong>' + j(summary.voices || 0) + '</strong><em>逐格入槽</em></div>' +
      '<div class="ip-asset-stat"><span>字幕 SRT</span><strong>' + j(summary.subtitles || 0) + '</strong><em>逐格 + 总字幕</em></div>' +
      '<div class="ip-asset-stat"><span>角色 / 主视觉</span><strong>' + j(summary.characters || 0) + ' + 1</strong><em>自制 SVG</em></div>' +
      '<div class="ip-asset-stat is-wide"><span>主音轨 / 分镜时间轴</span><strong>' + j(wideText) + '</strong><em>配音合计 ' + j(fmtSeconds(audioTotal)) + ' · 采样率 ' + j(rates.length ? rates.join(' / ') : '—') + ' Hz · 单声道</em></div>';
  }

  function renderAssetChecks(checks) {
    var box = $('#assetChecks');
    if (!box) return;
    checks = checks || [];
    if (!checks.length) {
      box.innerHTML = '<p class="empty-copy">暂无校验结果。</p>';
      return;
    }
    box.innerHTML = checks.map(function (check) {
      return '<div class="check-row ' + (check.ok ? 'is-ok' : 'is-fail') + '">' +
        '<span class="check-mark">' + (check.ok ? '✓' : '✕') + '</span>' +
        '<span><strong>' + j(check.label) + '</strong>' +
          (check.detail ? '<span class="ip-check-detail">' + j(check.detail) + '</span>' : '') +
        '</span>' +
      '</div>';
    }).join('');
  }

  function renderAssetTable() {
    var body = $('#assetTableBody');
    if (!body) return;
    var assets = (state.assets && state.assets.assets) || [];
    if (!assets.length) {
      body.innerHTML = '<tr><td colspan="5" class="table-empty">素材清单加载中…</td></tr>';
      return;
    }
    body.innerHTML = assets.map(function (asset) {
      var duration = '—';
      if (asset.kind === 'voice' || asset.kind === 'master_audio') {
        duration = fmtDuration(asset.durationMs) + (asset.sampleRate ? ' · ' + (asset.sampleRate / 1000).toFixed(2) + ' kHz' : '');
      } else if (asset.kind === 'subtitle' || asset.kind === 'master_subtitle') {
        duration = (asset.cues || 0) + ' 条字幕';
      } else if (asset.kind === 'scene' || asset.kind === 'character' || asset.kind === 'poster') {
        duration = '矢量 SVG';
      }
      return '<tr>' +
        '<td><span class="tag ip-asset-kind">' + j(KIND_LABELS[asset.kind] || asset.kind) + '</span></td>' +
        '<td><div class="ip-cell-main">' + j(asset.label) + (asset.shot ? ' <span class="muted">· 镜 ' + pad(asset.shot) + '</span>' : '') + '</div></td>' +
        '<td><div class="ip-asset-path">' + j(asset.path) + '</div></td>' +
        '<td><span class="mono">' + j(fmtBytes(asset.bytes)) + '</span></td>' +
        '<td><span class="mono">' + j(duration) + '</span> ' + (asset.exists ? tag('在', 'green') : tag('缺失', 'red')) + '</td>' +
      '</tr>';
    }).join('');
  }

  function renderAssetResultPass(message, detail) {
    var box = $('#assetResult');
    if (!box) return;
    box.innerHTML = '<div class="ip-pass-note"><strong>✓</strong><span>' + j(message) + (detail ? '　' + j(detail) : '') + '</span></div>';
  }

  function renderAssetResultError(error) {
    var box = $('#assetResult');
    if (!box) return;
    var payload = (error && error.payload) || {};
    var missing = payload.missing || [];
    var message = payload.message || (error && error.message) || '素材校验失败';
    box.innerHTML = '<div class="ip-finding" data-severity="blocker">' +
      '<div class="ip-finding-top"><strong>素材校验未通过' + (error && error.status ? '（HTTP ' + j(error.status) + '）' : '') + '</strong>' + tag('阻断', 'red') + '</div>' +
      '<div class="ip-finding-fix">' + j(message) + (missing.length ? '<br>缺失路径：' + j(missing.join('、')) : '') + '</div>' +
    '</div>';
  }

  async function loadAssets() {
    var data = await U.api('/api/ip/assets');
    state.assets = data;
    var summary = data.summary || {};
    renderAssetSummary(summary, state.manifest);
    renderAssetChecks(data.checks);
    renderAssetTable();
    var chip = $('#assetChip');
    if (chip) chip.textContent = (summary.present || 0) + ' / ' + (summary.total || 0) + ' 存在 · ' + (summary.missing || 0) + ' 缺失';
    renderAssetResultPass('素材清单读取完成：' + (summary.present || 0) + ' / ' + (summary.total || 0) + ' 项存在。',
      '点击「重新校验素材」会由服务端重新读取 WAV 头、SRT 条数并核对主音轨时长。');
  }

  async function loadDashboard() {
    var data = await U.api('/api/ip/dashboard');
    state.dashboard = data.dashboard || null;
    renderKpis();
  }

  async function loadReviews() {
    var data = await U.api('/api/ip/reviews?limit=12');
    state.reviews = data;
    renderReviewHistory(data);
  }

  async function loadLicenses() {
    var data = await U.api('/api/ip/licenses?limit=10');
    state.licenses = data;
    renderLicenseHistory(data);
  }

  async function loadDerivatives() {
    var data = await U.api('/api/ip/derivatives');
    state.derivatives = data;
    renderSkus(data);
  }

  function renderSkus(data) {
    var body = $('#skuTableBody');
    if (!body) return;
    var skus = (data && data.skus) || [];
    if (!skus.length) {
      body.innerHTML = '<tr><td colspan="7" class="table-empty">SKU 加载中…</td></tr>';
      return;
    }
    body.innerHTML = skus.map(function (sku) {
      var specs = sku.specs || {};
      var specText = ['size', 'material', 'process', 'packaging'].map(function (key) {
        return specs[key] ? j(specs[key]) : '';
      }).filter(Boolean).join(' / ');
      return '<tr>' +
        '<td><span class="mono">' + j(sku.id) + '</span></td>' +
        '<td><div class="ip-sku-name">' + j(sku.name) + '</div><div class="ip-sku-specs">' + j(sku.category || '') + '</div></td>' +
        '<td><div class="ip-cell-main">' + j(specText || '—') + '</div></td>' +
        '<td><span class="mono">' + j(sku.moq) + '</span></td>' +
        '<td><span class="mono">' + j(fmtYuan(sku.retailCents)) + '</span></td>' +
        '<td><span class="mono">' + j(fmtPct(sku.royaltyBps)) + '</span></td>' +
        '<td>' + tag(sku.statusLabel || '待授权', 'amber') + '</td>' +
      '</tr>';
    }).join('');
    var chip = $('#skuChip');
    if (chip) chip.textContent = skus.length + ' 个 SKU · 全部待授权';
    var note = $('#skuNote');
    if (note) {
      note.textContent = (data.notes ? data.notes + ' ' : '') + (data.disclaimer || '');
    }
  }

  function initPlayer() {
    var manifest = state.manifest;
    if (!manifest) return;
    state.totalMs = Number(manifest.totalMs) || 0;
    var audio = $('#ipAudio');
    if (audio && manifest.master && manifest.master.audio) {
      if (audio.getAttribute('src') !== manifest.master.audio) {
        audio.src = manifest.master.audio;
        try { audio.load(); } catch (error) { /* 播放事件会给出提示 */ }
      }
    }
    var durationOk = manifest.durationOk !== false;
    var durationChip = $('#playerDurationChip');
    if (durationChip) {
      durationChip.innerHTML = tag(durationOk ? '通过' : '异常', durationOk ? 'green' : 'red') +
        ' 总时长 ' + fmtSeconds(state.totalMs) + ' · ' + (manifest.minMs ? fmtSeconds(manifest.minMs) : '30 秒') + '–' + (manifest.maxMs ? fmtSeconds(manifest.maxMs) : '45 秒');
    }
    var sampleRate = manifest.master && manifest.master.sampleRate;
    setText('playerFormatChip', (manifest.voiceName || '本机语音') + (sampleRate ? ' · ' + (sampleRate / 1000).toFixed(2) + ' kHz' : '') + ' · ' + (manifest.shotCount || manifest.shots.length) + ' 段');
    setText('timeTotal', fmtClock(state.totalMs));
    setText('playNote', '点击播放，开始 ' + fmtSeconds(state.totalMs) + ' 样片（浏览器要求用户手势，不自动播放）');
    var timeline = $('#timeline');
    if (timeline) {
      timeline.setAttribute('aria-valuemax', String(state.totalMs));
      timeline.setAttribute('aria-valuenow', '0');
    }
    renderTimeline();
    renderThumbs();
    setShot(0, { seek: false });
    renderPlayback(0);
    state.playerReady = true;
    (manifest.shots || []).forEach(function (shot) {
      if (!shot.svg) return;
      var image = new Image();
      image.src = shot.svg;
    });
    prepareAudioBlob(audio);
  }

  // 服务器是 Python 标准库静态服务，不实现 HTTP Range；直接把 1.7MB WAV 取进
  // 内存并换成 blob: URL，浏览器即可在整段音频内可靠跳转（时间轴/缩略图/键盘）。
  async function prepareAudioBlob(audio) {
    if (!audio || state.audioObjectUrl || state.audioBlobLoading) return;
    if (typeof fetch !== 'function' || !window.URL || !window.URL.createObjectURL) return;
    var master = (state.manifest && state.manifest.master) || {};
    var source = master.audio || audio.getAttribute('src');
    if (!source) return;
    state.audioBlobLoading = true;
    try {
      var response = await fetch(source, { cache: 'no-store' });
      if (!response.ok) throw new Error('HTTP ' + response.status);
      var blob = await response.blob();
      if (!blob || !blob.size) throw new Error('音频为空');
      state.audioObjectUrl = URL.createObjectURL(blob);
      audio.src = state.audioObjectUrl;
      audio.load();
    } catch (error) {
      // 兜底：仍使用原始 /media/voice/*.wav，播放不依赖内存预载。
      if (window.console && console.warn) console.warn('[ip] audio preload failed, fallback to direct url', error);
      setText('playNote', '音频直连模式 · 点击播放；如跳转失败请用重播。');
    } finally {
      state.audioBlobLoading = false;
    }
  }

  function renderTimeline() {
    var box = $('#timelineSegments');
    if (!box) return;
    var shots = (state.manifest && state.manifest.shots) || [];
    var total = state.totalMs || shots.reduce(function (sum, shot) { return sum + (Number(shot.durationMs) || 0); }, 0);
    if (!shots.length || !total) {
      box.innerHTML = '';
      return;
    }
    box.innerHTML = shots.map(function (shot, index) {
      var dynamic = Number(shot.endMs) - Number(shot.startMs);
      var duration = dynamic > 0 ? dynamic : Number(shot.durationMs) || 0;
      var width = Math.max(0.2, duration / total * 100);
      return '<div class="ip-timeline-seg" data-index="' + index + '" style="width:' + width.toFixed(4) + '%" title="SHOT ' + pad(shot.no) + ' · ' + j(shot.scene) + ' · ' + fmtDuration(duration) + '"><span>' + pad(shot.no) + '</span></div>';
    }).join('');
    var progress = $('#timelineProgress');
    if (progress) progress.style.width = '0%';
    var head = $('#timelineHead');
    if (head) head.style.left = '0%';
  }

  function renderThumbs() {
    var box = $('#shotThumbs');
    if (!box) return;
    var shots = (state.manifest && state.manifest.shots) || [];
    if (!shots.length) {
      box.innerHTML = '<p class="empty-copy">分镜加载中…</p>';
      return;
    }
    box.innerHTML = shots.map(function (shot, index) {
      return '<button type="button" class="ip-thumb' + (index === state.activeIndex ? ' is-active' : '') + '" data-shot="' + index + '" aria-label="跳转分镜 ' + pad(shot.no) + '：' + j(shot.scene) + '">' +
        '<img src="' + j(shot.svg) + '" alt="分镜 ' + pad(shot.no) + ' 场景缩略图" loading="lazy">' +
        '<span class="ip-thumb-meta"><b>SHOT ' + pad(shot.no) + '</b><strong>' + j(shot.scene) + '</strong><span>' + fmtDuration(shot.durationMs) + '</span></span>' +
      '</button>';
    }).join('');
  }

  function updateThumbActive() {
    $$('#shotThumbs .ip-thumb').forEach(function (button) {
      var active = Number(button.getAttribute('data-shot')) === state.activeIndex;
      button.classList.toggle('is-active', active);
      if (active) button.setAttribute('aria-current', 'true');
      else button.removeAttribute('aria-current');
    });
  }

  function setShot(index, options) {
    options = options || {};
    var shots = (state.manifest && state.manifest.shots) || [];
    if (!shots.length) return;
    index = Math.max(0, Math.min(shots.length - 1, Number(index) || 0));
    var shot = shots[index];
    state.activeIndex = index;
    setText('stageNo', 'SHOT ' + pad(shot.no) + ' / ' + pad(shots.length));
    setText('stageScene', shot.scene || '');
    setText('stageSpeaker', shot.speaker || '旁白');
    setText('stageLine', shot.caption || '');
    var image = $('#stageImage');
    if (image && shot.svg && image.getAttribute('src') !== shot.svg) {
      var stage = $('#stageFrame');
      if (stage) stage.classList.add('is-switching');
      image.setAttribute('src', shot.svg);
      image.setAttribute('alt', '分镜 ' + pad(shot.no) + ' 场景卡：' + (shot.scene || ''));
      window.clearTimeout(state.imageTimer);
      state.imageTimer = window.setTimeout(function () {
        if (stage) stage.classList.remove('is-switching');
      }, 180);
    }
    updateThumbActive();
    if (options.seek) {
      seekAudio(shot.startMs);
      renderPlayback(shot.startMs);
      updatePlayButton();
    }
  }

  function seekAudio(ms) {
    var audio = $('#ipAudio');
    state.pendingSeekMs = ms;
    if (audio && audio.readyState >= 1) {
      try {
        audio.currentTime = Math.max(0, Number(ms) || 0) / 1000;
        state.pendingSeekMs = null;
      } catch (error) {
        state.pendingSeekMs = ms;
      }
    }
  }

  function seekToMs(ms) {
    if (!state.totalMs) return;
    var clamped = Math.max(0, Math.min(state.totalMs, Number(ms) || 0));
    hideEndcard();
    seekAudio(clamped);
    renderPlayback(clamped);
    updatePlayButton();
  }

  function shotIndexAt(ms) {
    var shots = (state.manifest && state.manifest.shots) || [];
    if (!shots.length) return 0;
    for (var index = 0; index < shots.length; index += 1) {
      if (ms < Number(shots[index].endMs) - 1) return index;
    }
    return shots.length - 1;
  }

  function renderPlayback(ms) {
    var shots = (state.manifest && state.manifest.shots) || [];
    if (!shots.length) return;
    var total = state.totalMs || 1;
    var clamped = Math.max(0, Math.min(total, Number(ms) || 0));
    var index = shotIndexAt(clamped);
    if (index !== state.activeIndex) setShot(index, { seek: false });
    setText('timeNow', fmtClock(clamped));
    var percent = clamped / total * 100;
    var progress = $('#timelineProgress');
    if (progress) progress.style.width = percent.toFixed(4) + '%';
    var head = $('#timelineHead');
    if (head) head.style.left = percent.toFixed(4) + '%';
    var timeline = $('#timeline');
    if (timeline) timeline.setAttribute('aria-valuenow', String(Math.round(clamped)));
    $$('#timelineSegments .ip-timeline-seg').forEach(function (segment, segmentIndex) {
      var shot = shots[segmentIndex];
      if (!shot) return;
      segment.classList.toggle('is-active', segmentIndex === index);
      segment.classList.toggle('is-played', segmentIndex < index || (segmentIndex === index && clamped >= Number(shot.endMs) - 1));
    });
  }

  function updatePlayButton() {
    var audio = $('#ipAudio');
    var label = '播放';
    if (state.playing) label = '暂停';
    else if (state.atEnd) label = '重播';
    else if (audio && audio.currentTime > 0.05) label = '继续';
    setText('playLabel', label);
    var button = $('#btnPlay');
    if (button) button.setAttribute('aria-label', label + '样片');
  }

  function hideEndcard() {
    state.atEnd = false;
    var endCard = $('#endCard');
    if (endCard) endCard.classList.remove('is-visible');
  }

  function showEndcard() {
    state.atEnd = true;
    var endCard = $('#endCard');
    if (endCard) endCard.classList.add('is-visible');
  }

  function playSample() {
    var audio = $('#ipAudio');
    if (!audio) return;
    var atEnd = state.atEnd || (state.totalMs && audio.currentTime * 1000 >= state.totalMs - 40);
    hideEndcard();
    if (atEnd) {
      try { audio.currentTime = 0; } catch (error) { state.pendingSeekMs = 0; }
      setShot(0, { seek: false });
      renderPlayback(0);
    }
    var result = audio.play();
    if (result && typeof result.catch === 'function') {
      result.catch(function (error) {
        state.playing = false;
        updatePlayButton();
        setText('playNote', '浏览器未允许播放：请再次点击「播放」（需要用户手势）。');
        toast('无法自动播放，请点击播放按钮', 'error');
        console.warn('[ip] audio play failed', error);
      });
    }
  }

  function togglePlay() {
    var audio = $('#ipAudio');
    if (!audio) return;
    if (!audio.paused) {
      audio.pause();
    } else {
      playSample();
    }
  }

  function restartSample() {
    var audio = $('#ipAudio');
    if (!audio) return;
    try {
      audio.pause();
      audio.currentTime = 0;
      state.pendingSeekMs = null;
    } catch (error) {
      state.pendingSeekMs = 0;
    }
    hideEndcard();
    setShot(0, { seek: false });
    renderPlayback(0);
    updatePlayButton();
    playSample();
  }

  function onAudioTimeUpdate() {
    var audio = $('#ipAudio');
    if (!audio || !state.playerReady) return;
    renderPlayback(audio.currentTime * 1000);
  }

  function onAudioEnded() {
    state.playing = false;
    state.atEnd = true;
    showEndcard();
    renderPlayback(state.totalMs);
    setText('playLabel', '重播');
    setText('playNote', '样片结束 · 可重播，或点击右侧分镜回看任意一格');
    var button = $('#btnPlay');
    if (button) button.setAttribute('aria-label', '重播样片');
  }

  /* ---------- 审核台 ---------- */

  function updateReviewChars() {
    var textarea = $('#reviewText');
    var counter = $('#reviewChars');
    if (!textarea || !counter) return;
    var max = (state.config && state.config.review && state.config.review.maxTextLength) || 1000;
    counter.textContent = textarea.value.length + ' / ' + max;
  }

  function fillReviewSample(kind) {
    var review = (state.config && state.config.review) || {};
    var samples = review.samples || {};
    var text = samples[kind] || '';
    var textarea = $('#reviewText');
    if (!textarea) return;
    textarea.value = text;
    updateReviewChars();
    textarea.focus();
  }

  function reviewCounts(findings) {
    var counts = { blockers: 0, majors: 0, minors: 0 };
    (findings || []).forEach(function (finding) {
      if (finding.severity === 'blocker') counts.blockers += 1;
      else if (finding.severity === 'major') counts.majors += 1;
      else counts.minors += 1;
    });
    return counts;
  }

  function renderFinding(finding) {
    var severity = finding.severity || 'minor';
    var hits = (finding.hits || []).map(function (hit) {
      return '<span>' + j(hit) + '</span>';
    }).join('');
    return '<div class="ip-finding" data-severity="' + j(severity) + '">' +
      '<div class="ip-finding-top"><strong>' + j(finding.label || finding.rule) + '</strong>' +
        tag(SEVERITY_LABELS[severity] || severity, SEVERITY_TONES[severity] || 'muted') +
      '</div>' +
      (hits ? '<div class="ip-finding-hits">' + hits + '</div>' : '') +
      '<div class="ip-finding-fix">建议：' + j(finding.fix || '请调整文案后重审。') + '</div>' +
    '</div>';
  }

  function renderReviewResult(payload) {
    var box = $('#reviewResult');
    if (!box) return;
    var verdict = payload.verdict || 'revise';
    var label = payload.verdictLabel || { pass: '通过', revise: '需修改', reject: '拒绝' }[verdict] || verdict;
    var findings = payload.findings || [];
    var counts = payload.counts || reviewCounts(findings);
    var review = payload.review || {};
    var meta = [];
    if (payload.reviewId) meta.push('审核编号 ' + payload.reviewId);
    if (payload.reviewedAt) meta.push(when(payload.reviewedAt));
    if (review.target) meta.push('对象 ' + review.target);
    meta.push('阻断 ' + (counts.blockers || 0) + ' · 重要 ' + (counts.majors || 0) + ' · 提示 ' + (counts.minors || 0));
    var verdictTone = verdict === 'pass' ? 'green' : verdict === 'reject' ? 'red' : 'amber';
    var findingsHtml = findings.length
      ? '<div class="ip-findings">' + findings.map(renderFinding).join('') + '</div>'
      : '<div class="ip-pass-note"><strong>✓</strong><span>未命中审核规则中的任何一条阻断 / 重要 / 提示项。</span></div>';
    box.innerHTML = '<div class="ip-verdict-card is-' + j(verdict) + '">' +
      '<div class="ip-verdict-head">' +
        '<div class="ip-verdict-title"><span class="ip-result-icon">审</span><strong>' + j(label) + '</strong></div>' +
        tag(verdict, verdictTone) +
      '</div>' +
      '<div class="ip-verdict-meta">' + j(meta.join(' · ')) + '</div>' +
      findingsHtml +
    '</div>';
  }

  function renderReviewError(error) {
    var box = $('#reviewResult');
    if (!box) return;
    var payload = (error && error.payload) || {};
    var status = error && error.status ? error.status : '';
    var message = payload.message || (error && error.message) || '审核请求失败';
    var allowed = (payload.allowedRoles || []).map(roleName).join(' / ');
    box.innerHTML = '<div class="ip-verdict-card is-reject">' +
      '<div class="ip-verdict-head">' +
        '<div class="ip-verdict-title"><span class="ip-result-icon">审</span><strong>' + (status === 403 ? '权限拦截' : '审核未执行') + '</strong></div>' +
        (status ? tag('HTTP ' + status, 'red') : tag('网络错误', 'red')) +
      '</div>' +
      '<div class="ip-verdict-meta">' + j(message) + (allowed ? ' · 可执行角色：' + j(allowed) : '') + '</div>' +
      '<div class="ip-pass-note"><strong>!</strong><span>服务端逐次校验角色；这个错误不是前端故意隐藏按钮造成的。</span></div>' +
    '</div>';
  }

  function renderReviewHistory(data) {
    var box = $('#reviewHistory');
    var chip = $('#reviewHistoryChip');
    var payload = data || {};
    var reviews = payload.reviews || [];
    if (chip) chip.textContent = (payload.total != null ? payload.total : reviews.length) + ' 条留痕';
    if (!box) return;
    if (!reviews.length) {
      box.innerHTML = '<p class="empty-copy">暂无审核记录。提交一条文案后，服务端会写入 SQLite 留痕。</p>';
      return;
    }
    box.innerHTML = '<div class="ip-history">' + reviews.map(function (review) {
      var verdict = review.verdict || 'revise';
      var tone = verdict === 'pass' ? 'green' : verdict === 'reject' ? 'red' : 'amber';
      var findingLabels = (review.findings || []).map(function (finding) { return finding.label || finding.rule; }).join('、');
      return '<div class="ip-history-item">' +
        '<span class="ip-history-time">' + j(when(review.at)) + '<br>' + j(roleName(review.role)) + '</span>' +
        '<div class="ip-history-text">' + j(review.target || '未命名文案') + '<small>' + j(clip(review.text, 100)) + (findingLabels ? ' · 命中：' + j(clip(findingLabels, 54)) : '') + '</small></div>' +
        '<span>' + tag(review.verdictLabel || verdict, tone) + '</span>' +
      '</div>';
    }).join('') + '</div>';
  }

  async function submitReview(form) {
    var textarea = form.querySelector('[name="text"]');
    var targetInput = form.querySelector('[name="target"]');
    var text = textarea ? String(textarea.value || '').trim() : '';
    var target = targetInput ? String(targetInput.value || '').trim() : '';
    var min = (state.config && state.config.review && state.config.review.minTextLength) || 4;
    if (text.length < min) {
      toast('文案至少需要 ' + min + ' 个字', 'error');
      if (textarea) textarea.focus();
      return;
    }
    var button = form.querySelector('button[type="submit"]');
    busy(button, true);
    try {
      var payload = await post('/api/ip/review', { text: text, target: target });
      renderReviewResult(payload);
      if (payload.verdict === 'pass') toast('审核通过：' + payload.verdictLabel);
      else toast('审核结论：' + payload.verdictLabel + '（命中 ' + (payload.findings || []).length + ' 条规则）', 'error');
      loadReviews().catch(function (error) { console.warn('[ip] reload reviews failed', error); });
      loadDashboard().catch(function (error) { console.warn('[ip] reload dashboard failed', error); });
    } catch (error) {
      renderReviewError(error);
      toast(error.message || '审核失败', 'error');
    } finally {
      busy(button, false);
    }
  }

  /* ---------- 授权草稿 ---------- */

  function renderLicenseResult(license) {
    var box = $('#licenseResult');
    if (!box || !license) return;
    var clauses = license.clauses || [];
    var fullText = license.fullText || '';
    var fee = license.baseFee || (license.baseFeeCents != null ? fmtYuan(license.baseFeeCents) : '—');
    var royalty = license.derivativeRoyalty || (license.derivativeRoyaltyBps != null ? fmtPct(license.derivativeRoyaltyBps) : '—');
    box.innerHTML = '<div class="ip-draft-scroll"><div class="ip-draft">' +
      '<div class="ip-draft-head">' +
        '<div><div class="ip-draft-no">' + j(license.draftNo || license.id || '') + ' · ' + j(license.templateVersion || '') + '</div><h3>短剧 IP 授权合同（草稿）</h3></div>' +
        '<div>' + tag(license.statusLabel || '模板草稿', 'amber') + ' ' + tag('不构成法律意见', 'muted') + '</div>' +
      '</div>' +
      '<div class="ip-draft-meta">' +
        '<div><span>被许可方</span><b>' + j(license.licensee) + '</b></div>' +
        '<div><span>用途</span><b>' + j(license.purpose) + '</b></div>' +
        '<div><span>区域</span><b>' + j(license.territory) + '</b></div>' +
        '<div><span>期限</span><b>' + j(license.termMonths) + ' 个月</b></div>' +
        '<div><span>基础授权费</span><b>' + j(fee) + '</b></div>' +
        '<div><span>衍生品分成</span><b>' + j(royalty) + '</b></div>' +
      '</div>' +
      '<div class="ip-clauses">' + clauses.map(function (clause) {
        return '<div class="ip-clause"><strong>第 ' + j(clause.no) + ' 条 · ' + j(clause.title) + '</strong><p>' + j(clause.text) + '</p></div>';
      }).join('') + '</div>' +
      '<div class="ip-draft-disclaimer">' + j(license.disclaimer || license.notice || '模板样例，不构成法律意见。') + '</div>' +
      (fullText ? '<details class="ip-fulltext"><summary>查看完整纯文本草稿</summary><pre>' + j(fullText) + '</pre></details>' : '') +
      '<div class="ip-draft-actions">' + tag('本地模板 · 已留痕', 'muted') + '<span class="form-hint">生成时间 ' + j(when(license.generatedAt)) + '</span></div>' +
    '</div></div>';
  }

  function renderLicenseError(error) {
    var box = $('#licenseResult');
    if (!box) return;
    var payload = (error && error.payload) || {};
    var status = error && error.status ? error.status : '';
    var allowed = (payload.allowedRoles || []).map(roleName).join(' / ');
    box.innerHTML = '<div class="ip-verdict-card is-reject">' +
      '<div class="ip-verdict-head"><div class="ip-verdict-title"><span class="ip-result-icon">约</span><strong>' + (status === 403 ? '权限拦截' : '草稿未生成') + '</strong></div>' +
      (status ? tag('HTTP ' + status, 'red') : tag('网络错误', 'red')) + '</div>' +
      '<div class="ip-verdict-meta">' + j(payload.message || (error && error.message) || '授权草稿生成失败') + (allowed ? ' · 可执行角色：' + j(allowed) : '') + '</div>' +
      '<div class="ip-pass-note"><strong>!</strong><span>正式签署前须由执业律师审核；本页模板不产生真实授权效力。</span></div>' +
    '</div>';
  }

  function renderLicenseHistory(data) {
    var box = $('#licenseHistory');
    var chip = $('#licenseHistoryChip');
    var payload = data || {};
    var licenses = payload.licenses || [];
    if (chip) chip.textContent = (payload.total != null ? payload.total : licenses.length) + ' 份草稿';
    var licenseChip = $('#licenseChip');
    if (licenseChip) licenseChip.textContent = (payload.total != null ? payload.total : licenses.length) + ' 份 · 模板';
    if (!box) return;
    if (!licenses.length) {
      box.innerHTML = '<p class="empty-copy">暂无授权草稿。生成后会写入本地 SQLite 留痕。</p>';
      return;
    }
    box.innerHTML = '<div class="ip-history">' + licenses.map(function (license) {
      return '<div class="ip-history-item is-license">' +
        '<span class="ip-history-time">' + j(when(license.generatedAt)) + '<br>' + j(license.draftNo || '') + '</span>' +
        '<div class="ip-history-text">' + j(license.licensee) + '<small>' + j(license.purpose) + ' · ' + j(license.territory) + ' · ' + j(license.termMonths) + ' 个月 · ' + j((license.clauseCount || 12) + ' 条') + '</small></div>' +
        '<span>' + tag('模板草稿', 'amber') + '</span>' +
      '</div>';
    }).join('') + '</div>';
  }

  async function previewLicense(form) {
    var formData = new FormData(form);
    var licensee = String(formData.get('licensee') || '').trim();
    var purpose = String(formData.get('purpose') || '');
    var territory = String(formData.get('territory') || '');
    var term = Number(formData.get('term') || 12);
    if (licensee.length < 2) {
      toast('请填写被许可方名称（2–60 字）', 'error');
      return;
    }
    var button = form.querySelector('button[type="submit"]');
    busy(button, true);
    try {
      var payload = await post('/api/ip/license/preview', {
        licensee: licensee,
        purpose: purpose,
        territory: territory,
        term: term
      });
      if (!payload.license) throw new Error('服务端未返回合同草稿');
      state.lastLicense = payload.license;
      renderLicenseResult(payload.license);
      toast('授权草稿已生成：' + payload.license.draftNo);
      loadLicenses().catch(function (error) { console.warn('[ip] reload licenses failed', error); });
      loadDashboard().catch(function (error) { console.warn('[ip] reload dashboard failed', error); });
    } catch (error) {
      renderLicenseError(error);
      toast(error.message || '授权草稿生成失败', 'error');
    } finally {
      busy(button, false);
    }
  }

  /* ---------- 素材校验 ---------- */

  async function validateAssets() {
    var button = $('#btnValidateAssets');
    busy(button, true);
    try {
      var data = await post('/api/ip/assets/validate', {});
      var summary = data.summary || {};
      renderAssetSummary(summary, state.manifest);
      renderAssetChecks(data.checks || []);
      var chip = $('#assetChip');
      if (chip) chip.textContent = (summary.present || 0) + ' / ' + (summary.total || 0) + ' 存在 · ' + (summary.missing || 0) + ' 缺失';
      if (summary.missing) {
        renderAssetResultError({ status: 200, payload: data });
      } else {
        renderAssetResultPass('六项硬校验通过：存在性、WAV 头、配音入槽、SRT 条数、主音轨时长。',
          '时间轴 ' + fmtSeconds(data.timelineMs) + ' · 主音轨 ' + fmtSeconds(data.masterAudioMs) + ' · 缺失 ' + (summary.missing || 0));
      }
      toast('素材校验完成：' + (summary.present || 0) + ' / ' + (summary.total || 0) + ' 项存在');
    } catch (error) {
      renderAssetResultError(error);
      toast(error.message || '素材校验失败', 'error');
    } finally {
      busy(button, false);
    }
  }

  /* ---------- 一键全链路 ---------- */

  function scenarioValue(key, value) {
    if (Array.isArray(value)) {
      if (!value.length) return '0 项';
      if (typeof value[0] === 'object') {
        if (key === 'findings') return value.length + ' 项 · ' + value.map(function (item) { return item.label || item.rule || '规则'; }).join('、');
        if (key === 'checks') {
          var okCount = value.filter(function (item) { return item.ok; }).length;
          return value.length + ' 项 / ' + okCount + ' 项通过';
        }
        return value.length + ' 项';
      }
      var shown = value.slice(0, 6).map(function (item) { return String(item); }).join('、');
      return shown + (value.length > 6 ? '…' : '');
    }
    if (value && typeof value === 'object') {
      if (key === 'summary') {
        return '存在 ' + (value.present != null ? value.present : '—') + ' / ' + (value.total != null ? value.total : '—') + ' · 缺失 ' + (value.missing != null ? value.missing : '—');
      }
      if (key === 'duration') {
        return (value.ok === false ? '校验失败' : '区间通过') + ' · ' + fmtSeconds(value.totalMs) + ' · 最小 ' + fmtDuration(value.minMs) + ' / 最大 ' + fmtDuration(value.maxMs);
      }
      if (key === 'first') {
        return 'SHOT ' + pad(value.no) + ' · ' + (value.scene || '');
      }
      if (key === 'verdicts') {
        return '通过 ' + (value.pass || 0) + ' / 需修改 ' + (value.revise || 0) + ' / 拒绝 ' + (value.reject || 0);
      }
      if (key === 'counts') {
        return '阻断 ' + (value.blockers || 0) + ' · 重要 ' + (value.majors || 0) + ' · 提示 ' + (value.minors || 0);
      }
      return clip(JSON.stringify(value), 90);
    }
    if (typeof value === 'boolean') return value ? '是' : '否';
    if (value == null) return '—';
    if (key === 'totalSeconds') return Number(value).toFixed(1) + ' 秒';
    if (/Ms$/.test(key) || key === 'timelineMs' || key === 'masterAudioMs') return fmtSeconds(value) + ' (' + value + 'ms)';
    if (key === 'disclaimer' || key === 'message' || key === 'detail') return clip(String(value), 90);
    return String(value);
  }

  function scenarioEvidence(step) {
    if (step.expectError) {
      var parts = [];
      if (step.status) parts.push('HTTP ' + step.status);
      if (step.error) parts.push(step.error);
      if (step.message) parts.push(step.message);
      var extra = step.extra || {};
      if (extra.missing && extra.missing.length) parts.push('缺失：' + extra.missing.join('、'));
      if (extra.allowedRoles && extra.allowedRoles.length) parts.push('允许角色：' + extra.allowedRoles.join(' / '));
      if (extra.expected) parts.push(String(extra.expected));
      return parts.map(j).join(' · ') || '预期错误已被服务端拦截';
    }
    if (!step.ok) return j(step.message || '步骤执行失败');
    var result = step.result || {};
    var facts = [];
    Object.keys(result).forEach(function (key) {
      if (key === 'ok') return;
      if (facts.length >= 6) return;
      facts.push('<span><b>' + j(RESULT_LABELS[key] || key) + '</b> ' + j(scenarioValue(key, result[key])) + '</span>');
    });
    return facts.join(' · ') || '步骤执行成功';
  }

  function renderScenario(data) {
    var body = $('#scenarioBody');
    var chip = $('#scenarioChip');
    if (!body) return;
    var steps = data.steps || [];
    var summary = data.summary || {};
    var passed = summary.passed != null ? summary.passed : steps.filter(function (step) { return step.ok || step.satisfied; }).length;
    var total = summary.steps != null ? summary.steps : steps.length;
    var expected = summary.expectedFailures || 0;
    var unexpected = summary.unexpected || 0;
    if (chip) chip.textContent = passed + ' / ' + total + ' 步通过 · ' + expected + ' 预期失败';
    var summaryHtml = '<div class="scenario-summary">' +
      '<div><strong>' + j(passed) + ' / ' + j(total) + '</strong> <span class="muted">步通过</span></div>' +
      '<div><span class="tag tag-green">预期失败 ' + j(expected) + '</span> <span class="tag ' + (unexpected ? 'tag-red' : '') + '">意外 ' + j(unexpected) + '</span></div>' +
      '<div class="muted">场景 ' + j(data.scenario || 'ip-full-chain') + ' · ' + j(when(data.generatedAt)) + '</div>' +
      (summary.licenseNo ? '<div class="mono muted">' + j(summary.licenseNo) + '</div>' : '') +
    '</div>';
    var stepsHtml = '<div class="scenario-steps">' + steps.map(function (step, index) {
      var satisfied = !!step.satisfied || (step.ok && !step.unexpected);
      var stateClass = satisfied ? (step.expectError ? 'is-expected' : 'is-ok') : 'is-fail';
      var flagLabel = step.expectError ? (satisfied ? '预期拦截' : '意外成功') : (satisfied ? '通过' : '失败');
      var flagTone = step.expectError ? (satisfied ? 'amber' : 'red') : (satisfied ? 'green' : 'red');
      return '<div class="result-item ' + stateClass + '">' +
        '<div class="result-index">' + pad(index + 1) + '</div>' +
        '<div><div class="result-title">' + j(step.title) + '<span class="result-flag">' + tag(flagLabel, flagTone) + '</span></div>' +
        '<div class="result-meta">' + scenarioEvidence(step) + '</div></div>' +
      '</div>';
    }).join('') + '</div>';
    body.innerHTML = summaryHtml + stepsHtml;
  }

  async function runScenario() {
    var button = $('#btnScenario');
    var chip = $('#scenarioChip');
    if (state.scenarioRunning) return;
    state.scenarioRunning = true;
    busy(button, true);
    if (chip) chip.textContent = '运行中…';
    try {
      var data = await post('/api/ip/scenario', {});
      state.scenario = data;
      renderScenario(data);
      var summary = data.summary || {};
      toast('全链路自检完成：' + (summary.passed || 0) + ' / ' + (summary.steps || 0) + ' 步通过');
      await Promise.all([
        loadDashboard(),
        loadReviews(),
        loadLicenses(),
        loadAssets()
      ]);
      renderKpis();
    } catch (error) {
      if (chip) chip.textContent = '运行失败';
      var body = $('#scenarioBody');
      if (body) body.innerHTML = '<div class="ip-verdict-card is-reject"><div class="ip-verdict-head"><div class="ip-verdict-title"><strong>自检未完成</strong></div>' + tag('HTTP ' + (error.status || '—'), 'red') + '</div><div class="ip-verdict-meta">' + j(error.message || '未知错误') + '</div></div>';
      toast(error.message || '全链路自检失败', 'error');
    } finally {
      state.scenarioRunning = false;
      busy(button, false);
    }
  }

  async function resetDemo() {
    if (!window.confirm('确定清空本模块的审核留痕与授权草稿吗？媒体素材不会删除。')) return;
    var button = $('#btnReset');
    busy(button, true);
    try {
      await post('/api/ip/demo/reset', {});
      state.scenario = null;
      state.reviews = null;
      state.licenses = null;
      state.lastLicense = null;
      var scenarioBody = $('#scenarioBody');
      if (scenarioBody) {
        scenarioBody.innerHTML = '<p class="empty-copy">点击右上角「一键跑通 16 步自检」，或直接调用 <code>POST /api/ip/scenario</code>。</p>';
      }
      setText('scenarioChip', '未运行');
      var reviewResult = $('#reviewResult');
      if (reviewResult) reviewResult.innerHTML = '<div class="ip-result-empty"><span class="ip-result-icon">审</span><strong>等待审核</strong><p>提交一条文案后，这里显示 verdict、命中规则、严重级别与服务端给出的修改建议。</p></div>';
      var licenseResult = $('#licenseResult');
      if (licenseResult) licenseResult.innerHTML = '<div class="ip-result-empty"><span class="ip-result-icon">约</span><strong>尚未生成</strong><p>填写左侧表单后，这里显示完整合同草稿、12 条条款与免责声明。</p></div>';
      var textarea = $('#reviewText');
      if (textarea && state.config && state.config.review && state.config.review.samples) {
        textarea.value = state.config.review.samples.pass || '';
        updateReviewChars();
      }
      await Promise.all([
        loadDashboard(),
        loadReviews(),
        loadLicenses(),
        loadDerivatives(),
        loadAssets()
      ]);
      renderKpis();
      toast('演示数据已重置；媒体素材未改动');
    } catch (error) {
      toast(error.message || '重置失败', 'error');
    } finally {
      busy(button, false);
    }
  }

  /* ---------- 播放器事件与全局绑定 ---------- */

  function toggleMute() {
    var audio = $('#ipAudio');
    var button = $('#btnMute');
    if (!audio) return;
    audio.muted = !audio.muted;
    if (button) {
      button.textContent = audio.muted ? '取消静音' : '静音';
      button.setAttribute('aria-pressed', String(audio.muted));
      button.classList.toggle('is-on', audio.muted);
    }
  }

  function onAudioLoadedMetadata() {
    var audio = $('#ipAudio');
    if (!audio) return;
    var durationMs = audio.duration * 1000;
    if (isFinite(durationMs) && durationMs > 0) {
      state.audioDurationMs = durationMs;
      if (state.pendingSeekMs != null) {
        try {
          audio.currentTime = Math.max(0, Math.min(durationMs, state.pendingSeekMs)) / 1000;
          state.pendingSeekMs = null;
        } catch (error) { /* currentTime 尚不可写时等下一次 timeupdate */ }
      }
      var total = state.totalMs || 0;
      var diff = Math.abs(durationMs - total);
      if (total && diff > 250) {
        setText('playNote', '音频时长 ' + fmtSeconds(durationMs) + '，与分镜时间轴 ' + fmtSeconds(total) + ' 相差 ' + fmtDuration(diff) + '，请核验主音轨。');
      } else {
        setText('playNote', '音频已就绪 · ' + fmtSeconds(durationMs) + ' · 点击播放（需用户手势，不自动播放）');
      }
    } else {
      setText('playNote', '音频元数据读取中；点击播放后浏览器会再加载。');
    }
  }

  function onAudioPlay() {
    state.playing = true;
    hideEndcard();
    updatePlayButton();
    setText('playNote', '正在播放 · 本地 SAPI 配音 + SVG 分镜 + SRT 字幕');
  }

  function onAudioPause() {
    var audio = $('#ipAudio');
    if (!audio || audio.ended) return;
    state.playing = false;
    updatePlayButton();
    if (audio.currentTime > 0.02) {
      setText('playNote', '已暂停 · ' + fmtClock(audio.currentTime * 1000) + ' · 可继续或拖动时间轴');
    } else {
      setText('playNote', '已暂停 · 点击播放开始样片');
    }
  }

  function bindEvents() {
    document.addEventListener('click', function (event) {
      var target = event.target;
      if (!target || !target.closest) return;
      var actionElement = target.closest('[data-action]');
      if (!actionElement || actionElement.tagName === 'FORM') return;
      var action = actionElement.getAttribute('data-action');
      if (action === 'fill-review-pass') {
        event.preventDefault();
        fillReviewSample('pass');
        return;
      }
      if (action === 'fill-review-reject') {
        event.preventDefault();
        fillReviewSample('reject');
        return;
      }
      if (action === 'run-scenario') {
        event.preventDefault();
        runScenario();
        return;
      }
      if (action === 'reset-demo') {
        event.preventDefault();
        resetDemo();
        return;
      }
      if (action === 'validate-assets') {
        event.preventDefault();
        validateAssets();
        return;
      }
      if (action === 'restart-sample') {
        event.preventDefault();
        restartSample();
      }
    });

    document.addEventListener('submit', function (event) {
      var form = event.target;
      if (!form || !form.getAttribute) return;
      var action = form.getAttribute('data-action');
      if (!action) return;
      if (action === 'submit-review') {
        event.preventDefault();
        submitReview(form);
      } else if (action === 'preview-license') {
        event.preventDefault();
        previewLicense(form);
      }
    });

    document.addEventListener('craft-role-change', function () {
      renderRoleStrip();
      updateRoleHints();
    });

    var reviewText = $('#reviewText');
    if (reviewText) reviewText.addEventListener('input', updateReviewChars);

    var playButton = $('#btnPlay');
    if (playButton) playButton.addEventListener('click', togglePlay);
    var restartButton = $('#btnRestart');
    if (restartButton) restartButton.addEventListener('click', restartSample);
    var muteButton = $('#btnMute');
    if (muteButton) muteButton.addEventListener('click', toggleMute);

    var timeline = $('#timeline');
    if (timeline) {
      timeline.addEventListener('click', function (event) {
        if (!state.totalMs) return;
        var rect = timeline.getBoundingClientRect();
        if (!rect.width) return;
        var ratio = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
        seekToMs(state.totalMs * ratio);
      });
      timeline.addEventListener('keydown', function (event) {
        if (!state.totalMs) return;
        var step = event.shiftKey ? 2000 : 1000;
        if (event.key === 'ArrowRight') {
          event.preventDefault();
          seekToMs((($('#ipAudio') && $('#ipAudio').currentTime * 1000) || 0) + step);
        } else if (event.key === 'ArrowLeft') {
          event.preventDefault();
          seekToMs((($('#ipAudio') && $('#ipAudio').currentTime * 1000) || 0) - step);
        } else if (event.key === 'Home') {
          event.preventDefault();
          seekToMs(0);
        } else if (event.key === 'End') {
          event.preventDefault();
          seekToMs(state.totalMs);
          showEndcard();
          updatePlayButton();
        }
      });
    }

    var thumbs = $('#shotThumbs');
    if (thumbs) {
      thumbs.addEventListener('click', function (event) {
        var button = event.target.closest('[data-shot]');
        if (!button) return;
        var index = Number(button.getAttribute('data-shot'));
        if (isNaN(index)) return;
        setShot(index, { seek: true });
        updatePlayButton();
      });
    }

    var audio = $('#ipAudio');
    if (audio) {
      audio.addEventListener('loadedmetadata', onAudioLoadedMetadata);
      audio.addEventListener('durationchange', onAudioLoadedMetadata);
      audio.addEventListener('timeupdate', onAudioTimeUpdate);
      audio.addEventListener('play', onAudioPlay);
      audio.addEventListener('pause', onAudioPause);
      audio.addEventListener('ended', onAudioEnded);
      audio.addEventListener('error', function () {
        state.playing = false;
        updatePlayButton();
        setText('playNote', '音频加载失败：请检查 /media/voice/ip_sample.wav 是否存在。');
        toast('音频加载失败', 'error');
      });
    }
  }

  /* ---------- 启动 ---------- */

  async function boot() {
    try {
      var results = await Promise.all([
        loadConfig(),
        loadStory(),
        loadAssets(),
        loadDashboard(),
        loadReviews(),
        loadLicenses(),
        loadDerivatives(),
        U.api('/api/ip/media-manifest')
      ]);
      state.manifest = results[7];
      initPlayer();
      renderKpis();
      if (state.assets && state.assets.summary) renderAssetSummary(state.assets.summary, state.manifest);
    } catch (error) {
      console.error('[ip] boot failed', error);
      toast('页面初始化失败：' + (error.message || error), 'error');
      var body = $('#scenarioBody');
      if (body && !state.scenario) {
        body.innerHTML = '<p class="empty-copy">页面初始化失败：' + j(error.message || error) + '。请检查本地服务与 /api/ip/* 路由。</p>';
      }
    }
  }

  bindEvents();
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
