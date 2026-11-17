/** 消防违规实时标红：直接通过 store 构造 2m 净距，验证 violations 与底图状态行 */
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

// 应用没有把 store 挂到 window，先通过展商入口拿到的更新路径间接验证。
// 改为读取初始状态 + 用属性面板修改尺寸制造违规。
const r = await evalJs(`(async () => {
  const out = [];
  out.push(['initial', document.getElementById('statusLine').textContent]);

  // 选中一个标摊
  const canvas = document.getElementById('planView');
  const rect = canvas.getBoundingClientRect();
  document.querySelector('[data-tool="select"]').click();
  canvas.dispatchEvent(new PointerEvent('pointerdown', {
    bubbles: true, clientX: rect.left + 60, clientY: rect.top + 100, pointerId: 1,
  }));
  canvas.dispatchEvent(new PointerEvent('pointerup', {
    bubbles: true, clientX: rect.left + 60, clientY: rect.top + 100, pointerId: 1,
  }));
  await new Promise(r => setTimeout(r, 200));
  const title = document.querySelector('#propPanel h3')?.textContent;
  out.push(['selected', title]);

  // 把深度从 3 改成 5（向北凸出 1m，与通道对面行块的 4m 净距变成 3m）
  const dInput = document.getElementById('propD');
  dInput.value = '5';
  dInput.dispatchEvent(new Event('input', { bubbles: true }));
  document.querySelector('#propSave').click();
  await new Promise(r => setTimeout(r, 400));
  out.push(['after_resize_toast', document.getElementById('toast').textContent]);
  out.push(['after_resize_status', document.getElementById('statusLine').textContent]);

  // 改回 3m，违规应消除
  dInput.value = '3';
  dInput.dispatchEvent(new Event('input', { bubbles: true }));
  const saveBtn = document.querySelector('#propSave');
  if (saveBtn) saveBtn.click();
  await new Promise(r => setTimeout(r, 400));
  out.push(['after_restore_status', document.getElementById('statusLine').textContent]);
  return out;
})()`);
console.log(JSON.stringify(r, null, 2));
console.log('ERRORS:', errors.length, errors.slice(0, 5));
ws.close();
process.exit(errors.length ? 1 : 0);
