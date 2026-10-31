const fs = require('fs');
const path = require('path');
const CDP = 'http://127.0.0.1:9225';
const OUT = 'C:/Users/xibei/Documents/deepseek-harness/default-workspace/.scratch';
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const list = await (await fetch(CDP + '/json/list')).json();
  const target = list.find(t => t.url.includes('/pages/ai.html'));
  if (!target) throw new Error('AI page target not found');
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  let id = 0;
  const pending = new Map();
  const errors = [], logs = [];
  ws.onmessage = ev => {
    const m = JSON.parse(ev.data);
    if (m.id) { const p = pending.get(m.id); if (p) { pending.delete(m.id); m.error ? p.reject(new Error(JSON.stringify(m.error))) : p.resolve(m.result); } return; }
    if (m.method === 'Runtime.exceptionThrown') errors.push(m.params.exceptionDetails);
    if (m.method === 'Log.entryAdded') logs.push(m.params.entry);
  };
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  const send = (method, params = {}) => new Promise((res, rej) => { const mid = ++id; pending.set(mid, { resolve: res, reject: rej }); ws.send(JSON.stringify({ id: mid, method, params })); });
  await send('Runtime.enable'); await send('Page.enable'); await send('Log.enable');
  const ev = async expr => {
    const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error((r.exceptionDetails.exception && r.exceptionDetails.exception.description) || JSON.stringify(r.exceptionDetails).slice(0, 400));
    return r.result.value;
  };
  const waitFor = async (expr, ms = 15000) => {
    const end = Date.now() + ms;
    while (Date.now() < end) {
      try { if (await ev(expr)) return true; } catch (e) {}
      await sleep(300);
    }
    return false;
  };
  const shot = async name => {
    const metrics = await send('Page.getLayoutMetrics');
    const h = Math.min(Math.ceil(metrics.cssContentSize.height), 12000);
    const result = await send('Page.captureScreenshot', { format: 'png', fromSurface: true, captureBeyondViewport: true, clip: { x: 0, y: 0, width: 1680, height: h, scale: 1 } });
    const file = path.join(OUT, name);
    fs.writeFileSync(file, Buffer.from(result.data, 'base64'));
    console.log('SHOT', file, h + 'px', fs.statSync(file).size + 'B');
  };
  const txt = async sel => (await ev('(document.querySelector(' + JSON.stringify(sel) + ')||{}).innerText || ""')).replace(/\s+/g, ' ').slice(0, 700);

  await send('Page.reload', { ignoreCache: true });
  await sleep(4500);
  console.log('BOOT_ERRORS', errors.length, errors.map(e => (e.exception && e.exception.description) || e.text).join(' | ').slice(0, 1000));
  console.log('SEARCH_EXAMPLES', await ev('document.querySelectorAll("#searchExamples .ai-chip").length'));
  console.log('DOC_DETAIL', (await txt('#knowledgeDetail')).slice(0, 140));

  // 1) search via example chip
  await ev('document.querySelector("#searchExamples .ai-chip")?.click()');
  await waitFor('document.querySelectorAll("#searchResults .ai-result-card").length > 0', 12000);
  console.log('SEARCH_HITS', await ev('document.querySelectorAll("#searchResults .ai-result-card").length'));
  console.log('SEARCH_FIRST', (await txt('#searchResults .ai-result-card')).slice(0, 500));

  // 2) agent starter question
  await ev('document.querySelector("#starterQuestions .ai-chip")?.click()');
  await waitFor('document.querySelectorAll("#agentChat .bubble").length >= 2', 16000);
  console.log('AGENT_BUBBLES', await ev('document.querySelectorAll("#agentChat .bubble").length'));
  console.log('AGENT_LAST', (await txt('#agentChat .bubble:last-child')).slice(0, 700));
  console.log('TOOL_TRAIL', (await txt('#toolTrail')).slice(0, 500));
  console.log('CITES', (await txt('#agentCitations')).slice(0, 400));

  // 3) workflow success
  const hadInstance = await ev('document.querySelectorAll("#workflowInstances .ai-workflow-card").length');
  if (!hadInstance) {
    await ev('document.querySelector("#workflowTemplates [data-action=create-workflow]")?.click()');
    await waitFor('document.querySelectorAll("#workflowInstances .ai-workflow-card").length > 0', 12000);
  }
  await ev('document.querySelector("#workflowInstances .ai-workflow-card")?.click()');
  await waitFor('document.querySelector("#runForm")', 12000);
  console.log('RUN_FORM', !!await ev('document.querySelector("#runForm")'));
  await ev('document.querySelector("#runForm button[type=submit]").click()');
  await waitFor('document.querySelectorAll("#runResult .ai-run-step").length >= 5', 15000);
  console.log('RUN_SUCCESS', (await txt('#runResult')).slice(0, 800));

  // 4) workflow failure: clear email then run
  await ev('const f=document.querySelector("#runForm"); if(f){f.querySelector("[name=email]").value=""; f.querySelector("button[type=submit]").click()}');
  await waitFor('document.querySelector("#retryForm")', 15000);
  console.log('RUN_FAILED', (await txt('#runResult')).slice(0, 700));

  // 5) retry with email
  await ev('const f=document.querySelector("#retryForm"); if(f){f.querySelector("[name=email]").value="retry-demo@example.com"; f.querySelector("button[type=submit]").click()}');
  await waitFor('document.querySelector("#runResult .ai-run-meta") && document.querySelector("#runResult").innerText.includes("attempt 2")', 15000);
  console.log('RUN_RETRIED', (await txt('#runResult')).slice(0, 800));

  // 6) CRM stage advance
  await ev('document.querySelector("#leadTable tbody tr[data-action=select-lead]")?.click()');
  await waitFor('document.querySelector("#leadForm")', 12000);
  console.log('LEAD_BEFORE', (await txt('#leadDetail')).slice(0, 300));
  await ev('const f=document.querySelector("#leadForm"); if(f){const s=f.querySelector("[name=stage]"); s.selectedIndex=Math.min(1,s.options.length-1); f.querySelector("[name=note]").value="CDP 验证：已电话联系（合成样例）"; f.querySelector("button[type=submit]").click()}');
  await waitFor('document.querySelector("#leadDetail") && document.querySelector("#leadDetail").innerText.includes("CDP 验证")', 12000);
  console.log('LEAD_AFTER', (await txt('#leadDetail')).slice(0, 500));

  // 7) language switch
  await ev('document.querySelector("#langTabs [data-lang=en]")?.click()');
  await waitFor('document.querySelector("#sitePreview") && document.querySelector("#sitePreview").innerText.includes("Shanmen")', 12000);
  console.log('SITE_EN', (await txt('#sitePreview')).slice(0, 500));
  console.log('SEO_EN', (await txt('#seoPanel')).slice(0, 300));

  // 8) handbook expand
  await ev('document.querySelector("[data-action=expand-handbook]")?.click()');
  await sleep(600);
  console.log('HANDBOOK_SECTIONS', await ev('document.querySelectorAll("#handbookBody .ai-md-section").length'));
  console.log('HANDBOOK_VISIBLE', await ev('Array.from(document.querySelectorAll("#handbookBody .ai-md-section")).filter(x=>x.offsetHeight>0).length'));

  await shot('ai-verified-full.png');
  console.log('ERRORS', errors.length, errors.map(e => (e.exception && e.exception.description) || e.text).join(' | ').slice(0, 1500));
  console.log('LOG_ERRORS', logs.filter(l => l.level === 'error').map(l => l.text).join(' | ').slice(0, 1000));
})();
