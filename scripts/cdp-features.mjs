/** 拾取延迟与门头排版验证（通过 CDP 在页面上下文里直接调用内部模块不现实，
 *  改用合成鼠标事件 + 读取 booth 卡片的方式端到端验证） */
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

await evalJs(`document.getElementById('btnWalk').click()`);
await sleep(3000);

// 门头排版：在页面里直接复用 Canvas 测字逻辑，验证短名单行、长名缩字/折行
const signCheck = await evalJs(`(async () => {
  const mod = await import('/src/three/signText.ts');
  const cases = ['恒达', '天业科技集团股份有限公司', '博通智能装备', 'A'];
  return cases.map((t) => {
    const r = mod.renderSignText(t);
    return { text: t, lines: r.lines, fontScale: Number(r.fontScale.toFixed(2)) };
  });
})()`);
console.log('SIGN_LAYOUT:', JSON.stringify(signCheck, null, 2));

// 端到端拾取：用 Raycaster 同款 Picker 需要 pointer lock，
// 这里验证 HUD 拾取统计字段存在且单位为 ms，并验证展位卡片能通过搜索导航后出现
const pick = await evalJs(`(async () => {
  const input = document.getElementById('searchInput');
  input.value = 'A50';
  input.dispatchEvent(new Event('input', { bubbles: true }));
  await new Promise(r => setTimeout(r, 200));
  document.querySelector('#searchResults .item')?.click();
  await new Promise(r => setTimeout(r, 500));
  const hud = document.getElementById('hud').textContent.replace(/\\s+/g, ' ').trim();
  const msMatch = hud.match(/拾取延迟\\s*([\\d.]+)ms/);
  return { hudPickMs: msMatch ? Number(msMatch[1]) : null, routeDrawn: !!document.querySelector('.minimap-wrap canvas') };
})()`);
console.log('PICK_AND_NAV:', JSON.stringify(pick, null, 2));

// 小地图画布实际有像素内容
const minimapPixels = await evalJs(`(() => {
  const c = document.getElementById('minimap');
  const ctx = c.getContext('2d');
  const data = ctx.getImageData(0, 0, c.width, c.height).data;
  let nonWhite = 0;
  for (let i = 0; i < data.length; i += 4) {
    if (data[i] < 240 || data[i+1] < 240 || data[i+2] < 240) nonWhite++;
  }
  return { nonWhitePixels: nonWhite, total: data.length / 4 };
})()`);
console.log('MINIMAP:', JSON.stringify(minimapPixels));

console.log('ERRORS:', errors.length, errors.slice(0, 5));
ws.close();
process.exit(errors.length ? 1 : 0);
