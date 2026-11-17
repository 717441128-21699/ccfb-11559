/**
 * 无头浏览器 CDP 验证：
 * 1. 加载页面，收集 console 错误与页面异常
 * 2. 底图模式检查画布与状态行
 * 3. 切到三维漫游，读取 HUD 的 FPS/draw call/三角形/剔除统计
 * 4. 触发一次搜索，验证结果面板
 */
const BASE = 'http://localhost:5217';

const target = await (
  await fetch('http://localhost:9222/json/new?' + encodeURIComponent(BASE), { method: 'PUT' })
).json();
const ws = new WebSocket(target.webSocketDebuggerUrl);
let msgId = 0;
const pending = new Map();
const errors = [];

ws.onmessage = (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) {
    pending.get(m.id)(m);
    pending.delete(m.id);
  }
  if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
    errors.push(m.params.args.map((a) => a.value ?? a.description ?? a.type).join(' '));
  }
  if (m.method === 'Runtime.exceptionThrown') {
    errors.push(
      'EXCEPTION: ' +
        (m.params.exceptionDetails.exception?.description ?? m.params.exceptionDetails.text),
    );
  }
};

await new Promise((r) => (ws.onopen = r));
function send(method, params = {}) {
  const id = ++msgId;
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve) => pending.set(id, resolve));
}

await send('Runtime.enable');
await send('Page.enable');
await send('Page.navigate', { url: BASE });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
await sleep(6000);

async function evalJs(expr) {
  const r = await send('Runtime.evaluate', {
    expression: expr,
    returnByValue: true,
    awaitPromise: true,
  });
  if (r.result?.exceptionDetails) {
    return { error: r.result.exceptionDetails.text };
  }
  return r.result?.result?.value;
}

const planInfo = await evalJs(`(() => {
  const status = document.getElementById('statusLine')?.textContent ?? '';
  const canvas = document.getElementById('planView');
  return {
    status,
    planCanvasSize: [canvas?.width, canvas?.height],
    toolbarButtons: document.querySelectorAll('[data-tool]').length,
  };
})()`);
console.log('PLAN:', JSON.stringify(planInfo, null, 2));

await evalJs(`document.getElementById('btnWalk').click()`);
await sleep(5000);

const walkInfo = await evalJs(`(() => {
  const hud = document.getElementById('hud')?.textContent ?? '';
  const canvas = document.getElementById('walkView');
  return {
    hud,
    walkCanvasSize: [canvas?.width, canvas?.height],
    webgl2: !!canvas.getContext('webgl2'),
  };
})()`);
console.log('WALK:', JSON.stringify(walkInfo, null, 2));

await sleep(4000);
const hud2 = await evalJs(`document.getElementById('hud')?.textContent`);
console.log('HUD_STABLE:', hud2);

const search = await evalJs(`(async () => {
  const input = document.getElementById('searchInput');
  input.value = '科技';
  input.dispatchEvent(new Event('input', { bubbles: true }));
  await new Promise(r => setTimeout(r, 300));
  const items = document.querySelectorAll('#searchResults .item');
  const first = items[0];
  const label = first?.textContent ?? '';
  first?.click();
  await new Promise(r => setTimeout(r, 200));
  return { resultCount: items.length, firstLabel: label, toast: document.getElementById('toast')?.textContent };
})()`);
console.log('SEARCH:', JSON.stringify(search, null, 2));

console.log('\n=== CONSOLE ERRORS (' + errors.length + ') ===');
for (const e of errors.slice(0, 20)) console.log(e);

ws.close();
process.exit(errors.length ? 1 : 0);
