const fs = require('fs');
const path = require('path');
const CDP = 'http://127.0.0.1:9225';
const OUT = 'C:/Users/xibei/Documents/deepseek-harness/default-workspace/.scratch';
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const list = await (await fetch(CDP + '/json/list')).json();
  const target = list.find(t => t.url.includes('/pages/ai.html'));
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  let id = 0; const pending = new Map(); const errors = []; const logs = [];
  ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id) { const p = pending.get(m.id); if (p) { pending.delete(m.id); m.error ? p.reject(new Error(JSON.stringify(m.error))) : p.resolve(m.result); } return; } if (m.method === 'Runtime.exceptionThrown') errors.push(m.params.exceptionDetails); if (m.method === 'Log.entryAdded') logs.push(m.params.entry); };
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  const send = (method, params = {}) => new Promise((res, rej) => { const mid = ++id; pending.set(mid, { resolve: res, reject: rej }); ws.send(JSON.stringify({ id: mid, method, params })); });
  await send('Runtime.enable'); await send('Log.enable');
  const ev = async expr => { const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true }); if (r.exceptionDetails) throw new Error((r.exceptionDetails.exception && r.exceptionDetails.exception.description) || JSON.stringify(r.exceptionDetails).slice(0, 300)); return r.result.value; };
  const waitFor = async (expr, ms = 15000) => { const end = Date.now() + ms; while (Date.now() < end) { try { if (await ev(expr)) return true; } catch (e) {} await sleep(300); } return false; };
  const txt = async sel => (await ev('(document.querySelector(' + JSON.stringify(sel) + ')||{}).innerText || ""')).replace(/\s+/g, ' ').slice(0, 900);
  const shotEl = async (sel, name) => {
    const rect = await ev('(function(){var e=document.querySelector(' + JSON.stringify(sel) + ');if(!e)return null;var r=e.getBoundingClientRect();return {x:r.left+window.scrollX,y:r.top+window.scrollY,w:r.width,h:r.height};})()');
    if (!rect) { console.log('NO_RECT', sel); return; }
    const result = await send('Page.captureScreenshot', { format: 'png', fromSurface: true, captureBeyondViewport: true, clip: { x: 0, y: Math.max(0, rect.y - 16), width: 1680, height: Math.min(rect.h + 60, 10000), scale: 1 } });
    const file = path.join(OUT, name); fs.writeFileSync(file, Buffer.from(result.data, 'base64'));
    console.log('SHOT', file, Math.round(rect.h) + 'px', fs.statSync(file).size + 'B');
  };
  const shotFull = async name => {
    const metrics = await send('Page.getLayoutMetrics'); const h = Math.min(Math.ceil(metrics.cssContentSize.height), 14000);
    const result = await send('Page.captureScreenshot', { format: 'png', fromSurface: true, captureBeyondViewport: true, clip: { x: 0, y: 0, width: 1680, height: h, scale: 1 } });
    const file = path.join(OUT, name); fs.writeFileSync(file, Buffer.from(result.data, 'base64'));
    console.log('SHOT', file, h + 'px', fs.statSync(file).size + 'B');
  };

  // current page should show failed run with retry form
  console.log('RETRY_FORM', !!await ev('document.querySelector("#retryForm")'));
  if (!await ev('document.querySelector("#retryForm")')) {
    await ev('document.querySelector("#workflowInstances .ai-workflow-card")?.click()');
    await waitFor('document.querySelector("#runForm")', 8000);
    await ev('(function(){var f=document.querySelector("#runForm");if(f){f.querySelector("[name=email]").value="";f.querySelector("button[type=submit]").click();}})()');
    await waitFor('document.querySelector("#retryForm")', 10000);
  }
  await shotEl('#workflowPanel', 'ai-workflow-failed.png');
  console.log('FAILED', (await txt('#runResult')).slice(0, 500));

  await ev('(function(){var f=document.querySelector("#retryForm");if(f){f.querySelector("[name=email]").value="retry-demo@example.com";f.querySelector("button[type=submit]").click();}})()');
  await waitFor('document.querySelector("#runResult") && document.querySelector("#runResult").innerText.includes("attempt 2")', 15000);
  console.log('RETRIED', (await txt('#runResult')).slice(0, 800));
  await shotEl('#workflowPanel', 'ai-workflow-retried.png');

  // CRM
  await ev('document.querySelector("#leadTable tbody tr[data-action=select-lead]")?.click()');
  await waitFor('document.querySelector("#leadForm")', 10000);
  console.log('LEAD_BEFORE', (await txt('#leadDetail')).slice(0, 320));
  await shotEl('#crmPanel', 'ai-crm-before.png');
  await ev('(function(){var f=document.querySelector("#leadForm");if(f){var s=f.querySelector("[name=stage]");s.selectedIndex=Math.min(1,s.options.length-1);f.querySelector("[name=note]").value="CDP 验证：已电话联系，约下周复尺（合成样例）";f.querySelector("button[type=submit]").click();}})()');
  await waitFor('document.querySelector("#leadDetail") && document.querySelector("#leadDetail").innerText.includes("CDP 验证")', 12000);
  console.log('LEAD_AFTER', (await txt('#leadDetail')).slice(0, 500));
  await shotEl('#crmPanel', 'ai-crm-after.png');

  // lang
  await ev('document.querySelector("#langTabs [data-lang=en]")?.click()');
  await waitFor('document.querySelector("#sitePreview") && document.querySelector("#sitePreview").innerText.includes("Shanmen")', 12000);
  console.log('SITE_EN', (await txt('#sitePreview')).slice(0, 500));
  console.log('SEO_EN', (await txt('#seoPanel')).slice(0, 300));
  await shotEl('#growthPanel', 'ai-growth-en.png');

  // handbook
  await ev('document.querySelector("[data-action=expand-handbook]")?.click()');
  await sleep(600);
  console.log('HANDBOOK_SECTIONS', await ev('document.querySelectorAll("#handbookBody .ai-md-section").length'));
  console.log('HANDBOOK_VISIBLE', await ev('Array.from(document.querySelectorAll("#handbookBody .ai-md-section")).filter(x=>x.offsetHeight>0).length'));
  await shotEl('#handbookPanel', 'ai-handbook.png');
  await shotFull('ai-verified-full.png');
  console.log('ERRORS', errors.length, errors.map(e => (e.exception && e.exception.description) || e.text).join(' | ').slice(0, 1200));
  console.log('LOG_ERRORS', logs.filter(l => l.level === 'error').map(l => l.text).join(' | ').slice(0, 800));
})();
