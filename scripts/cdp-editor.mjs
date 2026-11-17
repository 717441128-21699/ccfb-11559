/** 编辑器端到端：在底图上合成指针事件，验证放置/拦截/标红/删除 */
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
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  if (m.method === 'Runtime.exceptionThrown')
    errors.push(m.params.exceptionDetails.exception?.description ?? m.params.exceptionDetails.text);
};
await new Promise((r) => (ws.onopen = r));
const send = (method, params = {}) => {
  const id = ++msgId;
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((res) => pending.set(id, res));
};
await send('Runtime.enable');
await send('Page.enable');
await send('Page.navigate', { url: BASE });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
await sleep(5000);
const evalJs = async (expr) => (
  await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true })
).result?.result?.value;

const result = await evalJs(`(async () => {
  const out = [];
  const canvas = document.getElementById('planView');
  const rect = canvas.getBoundingClientRect();
  const before = document.getElementById('statusLine').textContent;
  out.push(['initial', before]);

  // 选矩形工具
  document.querySelector('[data-tool="rect"]').click();
  await new Promise(r => setTimeout(r, 100));

  const fire = (type, x, y) => canvas.dispatchEvent(new PointerEvent(type, {
    bubbles: true, clientX: rect.left + x, clientY: rect.top + y, pointerId: 1,
  }));

  // 1) 在中央主通道空白处画一个合法展位（通道宽 5m，画 3m 盒子，与两侧仍有 >=1m —— 会被 4m 规则拦截，验证拦截）
  // 底图缩放比：取状态行无法直接拿，用一个很大的拖拽确保覆盖真实世界米数
  fire('pointerdown', canvas.width / 2, 100);
  fire('pointermove', canvas.width / 2 + 30, 130);
  fire('pointerup', canvas.width / 2 + 30, 130);
  await new Promise(r => setTimeout(r, 300));
  out.push(['after_first_draw', document.getElementById('toast').textContent, document.getElementById('statusLine').textContent]);

  // 2) 切回选择工具，点选一个展位，验证属性面板
  document.querySelector('[data-tool="select"]').click();
  await new Promise(r => setTimeout(r, 100));
  fire('pointerdown', 60, 100);
  fire('pointerup', 60, 100);
  await new Promise(r => setTimeout(r, 200));
  const propVisible = document.getElementById('propPanel').style.display !== 'none';
  const propTitle = document.querySelector('#propPanel h3')?.textContent ?? '';
  out.push(['prop_panel', propVisible, propTitle]);

  // 3) 多边形工具：点 4 个点后双击闭合
  document.querySelector('[data-tool="polygon"]').click();
  await new Promise(r => setTimeout(r, 100));
  const pts = [[500, 500], [560, 500], [560, 560], [500, 560]];
  for (const [x, y] of pts) fire('pointerdown', x, y);
  canvas.dispatchEvent(new MouseEvent('dblclick', { bubbles: true, clientX: rect.left + 500, clientY: rect.top + 500 }));
  await new Promise(r => setTimeout(r, 300));
  out.push(['after_polygon', document.getElementById('toast').textContent]);

  // 4) 擦除工具
  document.querySelector('[data-tool="erase"]').click();
  await new Promise(r => setTimeout(r, 100));
  fire('pointerdown', 60, 100);
  fire('pointerup', 60, 100);
  await new Promise(r => setTimeout(r, 200));
  out.push(['after_erase', document.getElementById('toast').textContent]);

  return out;
})()`);
console.log(JSON.stringify(result, null, 2));
console.log('ERRORS:', errors.length, errors.slice(0, 5));
ws.close();
process.exit(errors.length ? 1 : 0);
