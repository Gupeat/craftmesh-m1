const fs = require('fs');
const CDP = 'http://127.0.0.1:9225';
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const list = await (await fetch(CDP + '/json/list')).json();
  const target = list.find(t => t.url.includes('/pages/ai.html'));
  if (!target) throw new Error('AI page target not found: ' + list.map(t => t.url).join(','));
  console.log('TARGET', target.id, target.url);
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
  await send('Page.reload', { ignoreCache: true });
  await sleep(4500);
  const ev = async expr => {
    const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error((r.exceptionDetails.exception && r.exceptionDetails.exception.description) || JSON.stringify(r.exceptionDetails).slice(0, 400));
    return r.result.value;
  };
  console.log('TITLE', await ev('document.title'));
  console.log('KPI', (await ev('document.querySelector("#kpis")?.innerText') || '').replace(/\s+/g, ' ').slice(0, 400));
  console.log('DOCS', await ev('document.querySelectorAll("#knowledgeList .ai-doc-card").length'));
  console.log('DETAIL', await ev('document.querySelector("#knowledgeDetail")?.innerText.slice(0,120)'));
  console.log('SEARCH_EXAMPLES', await ev('document.querySelector("#searchExamples")?.innerHTML.length'));
  console.log('ROLE', await ev('document.querySelector("#roleStrip")?.innerText.slice(0,100)'));
  console.log('BOOT_ERRORS', errors.length);
  if (errors.length) console.log(errors.map(e => (e.exception && e.exception.description) || e.text).join('\n---\n').slice(0, 2000));
  const bad = logs.filter(l => l.level === 'error');
  console.log('LOG_ERRORS', bad.length, bad.map(l => l.text + ' ' + (l.url || '')).join(' | ').slice(0, 1000));

  await ev('document.querySelector("[data-action=run-scenario]").click()');
  let count = 0;
  for (let i = 0; i < 40; i++) {
    await sleep(500);
    count = await ev('document.querySelectorAll("#scenarioBody .result-item").length');
    if (count >= 17) break;
  }
  console.log('SCENARIO_STEPS', count);
  console.log('SCENARIO_SUMMARY', (await ev('document.querySelector("#scenarioBody .scenario-summary")?.innerText') || '').replace(/\s+/g, ' ').slice(0, 600));
  console.log('SCENARIO_TEXT', (await ev('document.querySelector("#scenarioBody")?.innerText') || '').replace(/\s+/g, ' ').slice(0, 900));
  console.log('AFTER_ERRORS', errors.length);
  if (errors.length) console.log(errors.map(e => (e.exception && e.exception.description) || e.text).join('\n---\n').slice(0, 2000));
  ws.close();
  process.exit(0);
})().catch(err => { console.error('FAILED', err && err.stack || err); process.exit(1); });
