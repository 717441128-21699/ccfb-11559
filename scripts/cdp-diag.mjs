/** 分阶段诊断：进入漫游后的 HUD 随时间变化，以及导航前后的渲染状态 */
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
const evalJs = async (expr) => {
  const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
  return r.result?.result?.value;
};

await evalJs(`document.getElementById('btnWalk').click()`);
for (let i = 0; i < 4; i++) {
  await sleep(1500);
  console.log(`T+${i}`, await evalJs(`document.getElementById('hud')?.textContent.replace(/\\s+/g, ' ').trim()`));
}

// 相机位置与可见集合诊断
const camState = await evalJs(`(() => {
  // 通过 DOM 无法直接拿到 scene 实例，改读 HUD + 小地图尺寸
  return { hud: document.getElementById('hud')?.textContent.replace(/\\s+/g,' ').trim() };
})()`);
console.log('STATE', JSON.stringify(camState));

// 触发导航并连续观察
await evalJs(`(async () => {
  const input = document.getElementById('searchInput');
  input.value = 'A1';
  input.dispatchEvent(new Event('input', { bubbles: true }));
  await new Promise(r => setTimeout(r, 200));
  document.querySelector('#searchResults .item')?.click();
})()`);
for (let i = 0; i < 5; i++) {
  await sleep(1500);
  console.log(`NAV+${i}`, await evalJs(`document.getElementById('hud')?.textContent.replace(/\\s+/g, ' ').trim()`));
}
console.log('ERRORS', errors.length, errors.slice(0, 5));
ws.close();
process.exit(0);
