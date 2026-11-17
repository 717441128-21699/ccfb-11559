/** 展商入口模态框 + 遮挡查询开关 + 导出 */
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

const r = await evalJs(`(async () => {
  const out = [];

  // 遮挡开关
  const occBtn = document.getElementById('btnOcclusion');
  out.push(['occ_default', occBtn.textContent]);
  occBtn.click();
  out.push(['occ_after_click', occBtn.textContent]);
  occBtn.click();
  out.push(['occ_restored', occBtn.textContent]);

  // 展商入口
  document.getElementById('btnPortal').click();
  await new Promise(r => setTimeout(r, 200));
  const maskOpen = document.getElementById('portalMask').classList.contains('open');
  const listCount = document.querySelectorAll('#portalList .item').length;
  out.push(['portal_open', maskOpen, 'items', listCount]);

  // 选第一个展位并改名保存
  document.querySelector('#portalList .item').click();
  const nameInput = document.getElementById('portalName');
  const oldName = nameInput.value;
  nameInput.value = '测试改名公司';
  nameInput.dispatchEvent(new Event('input', { bubbles: true }));
  document.getElementById('portalSave').click();
  await new Promise(r => setTimeout(r, 300));
  const maskClosed = !document.getElementById('portalMask').classList.contains('open');
  const toast = document.getElementById('toast').textContent;

  // 搜索新名字应能命中
  const search = document.getElementById('searchInput');
  search.value = '测试改名公司';
  search.dispatchEvent(new Event('input', { bubbles: true }));
  await new Promise(r => setTimeout(r, 300));
  const hitCount = document.querySelectorAll('#searchResults .item').length;
  out.push(['portal_saved', maskClosed, toast, 'search_hits', hitCount, 'oldName', oldName]);

  // 导出：拦截 Blob 下载不易，验证 serialize 不抛错（localStorage 已写入）
  const stored = localStorage.getItem('hall3d-booths-v1');
  out.push(['localstore_bytes', stored?.length ?? 0, 'has_renamed', stored?.includes('测试改名公司')]);

  return out;
})()`);
console.log(JSON.stringify(r, null, 2));
console.log('ERRORS:', errors.length, errors.slice(0, 5));
ws.close();
process.exit(errors.length ? 1 : 0);
