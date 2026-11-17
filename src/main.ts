import './styles.css';
import type { AppMode, Booth, BoothType, FrameStats, Tool } from './types';
import { HALL } from './core/config';
import { BoothStore } from './data/BoothStore';
import { generateHall } from './data/generator';
import { PlanView } from './ui/PlanView';
import { Minimap } from './ui/Minimap';
import { Scene3D } from './three/Scene3D';

const STORAGE_KEY = 'hall3d-booths-v1';
const EXHIBITOR_KEY = 'hall3d-exhibitor-v1';

class App {
  private store = new BoothStore();
  private mode: AppMode = 'plan';
  private planView!: PlanView;
  private scene3d!: Scene3D;
  private minimap!: Minimap;
  private planRaf = 0;
  private selectedBooth: Booth | null = null;
  private portalBoothId = -1;

  constructor(private root: HTMLElement) {
    this.root.innerHTML = this.template();
    this.cacheDom();
    this.initPlan();
    this.initWalk();
    this.bindEvents();
    this.loadOrGenerate();
    this.startPlanLoop();
    this.setMode('plan');
  }

  private el!: Record<string, HTMLElement>;
  private cacheDom(): void {
    const ids = [
      'planView', 'walkView', 'btnPlan', 'btnWalk', 'searchInput', 'searchResults',
      'toolbar', 'statusLine', 'propPanel', 'hud', 'minimap', 'walkHint', 'crosshair',
      'boothCard', 'portalMask', 'toast', 'btnExport', 'btnImport', 'btnRegen',
      'btnPortal', 'btnOcclusion', 'batchRows', 'batchCols',
    ];
    this.el = {};
    for (const id of ids) this.el[id] = document.getElementById(id)!;
  }

  private template(): string {
    const tools: { id: Tool; label: string }[] = [
      { id: 'select', label: '选择/移动' },
      { id: 'rect', label: '矩形展位' },
      { id: 'batch', label: '批量生成' },
      { id: 'polygon', label: '手画异形' },
      { id: 'erase', label: '擦除' },
    ];
    const types: BoothType[] = ['standard', 'peninsula', 'island', 'double', 'custom'];
    const typeLabel: Record<BoothType, string> = {
      standard: '标摊', peninsula: '半岛', island: '岛式', double: '双面', custom: '异形',
    };
    return `
      <header class="topbar">
        <div class="logo">云<span>展馆</span> · 3D 漫游与布展</div>
        <div class="mode-switch">
          <button id="btnPlan" class="active">底图编辑</button>
          <button id="btnWalk">三维漫游</button>
        </div>
        <div class="search-box">
          <input id="searchInput" placeholder="搜索展商名称或展位号，回车自动寻路…" />
          <div class="search-results" id="searchResults" style="display:none"></div>
        </div>
        <div class="top-actions">
          <button class="btn" id="btnOcclusion">遮挡查询: 开</button>
          <button class="btn" id="btnPortal">展商入口</button>
          <button class="btn" id="btnExport">导出</button>
          <button class="btn" id="btnImport">导入</button>
          <button class="btn" id="btnRegen">重新生成</button>
        </div>
      </header>
      <main class="main">
        <section class="view" id="planViewWrap">
          <canvas id="planView"></canvas>
          <aside class="toolbar" id="toolbar">
            <h3>工具</h3>
            <div class="tool-grid">
              ${tools.map((t) => `<button data-tool="${t.id}">${t.label}</button>`).join('')}
            </div>
            <h3>展位类型</h3>
            <div class="type-grid">
              ${types.map((t, i) => `<button data-type="${t}" class="${i === 0 ? 'active' : ''}">${typeLabel[t]}</button>`).join('')}
            </div>
            <h3>批量行列</h3>
            <div class="batch-cfg">
              <input id="batchRows" type="number" min="1" max="40" value="4" /> 行 ×
              <input id="batchCols" type="number" min="1" max="40" value="6" /> 列
            </div>
          </aside>
          <div class="status-line" id="statusLine">
            馆内 ${HALL.width}m × ${HALL.depth}m，消防通道净距要求 ≥ ${HALL.fireLaneWidth}m。违规展位实时标红。
          </div>
          <aside class="prop-panel" id="propPanel" style="display:none"></aside>
        </section>
        <section class="view" id="walkViewWrap">
          <canvas id="walkView"></canvas>
          <div class="crosshair" id="crosshair"></div>
          <div class="hud" id="hud"></div>
          <div class="minimap-wrap">
            <canvas id="minimap" width="220" height="150"></canvas>
            <div class="cap">小地图 · 蓝线为导航路线</div>
          </div>
          <div class="walk-hint" id="walkHint">点击画面锁定鼠标，WASD 移动 · Shift 加速 · 点击展位查看</div>
          <div class="booth-card" id="boothCard" style="display:none"></div>
        </section>
        <div class="modal-mask" id="portalMask">
          <div class="modal">
            <h3>展商入口</h3>
            <label>输入展位号认领（如 A1、T12）</label>
            <input id="portalCode" placeholder="展位号" />
            <div class="booth-list" id="portalList"></div>
            <label>展商名称</label>
            <input id="portalName" placeholder="公司名称" />
            <label>门头主题色</label>
            <input id="portalColor" type="color" value="#9fc7e8" />
            <div class="actions">
              <button class="btn" id="portalCancel">取消</button>
              <button class="btn primary" id="portalSave">保存布展信息</button>
            </div>
          </div>
        </div>
        <div class="toast" id="toast"></div>
      </main>`;
  }

  private initPlan(): void {
    this.planView = new PlanView(this.el.planView as HTMLCanvasElement, this.store);
    this.planView.onSelect = (b) => {
      this.selectedBooth = b;
      this.renderPropPanel();
    };
    this.planView.onMessage = (msg, ok) => this.flash(msg, ok);
  }

  private initWalk(): void {
    this.scene3d = new Scene3D(
      this.el.walkView as HTMLCanvasElement,
      this.el.minimap as HTMLCanvasElement,
      this.store,
    );
    this.minimap = this.scene3d.minimap;
    this.scene3d.onStats = (s) => this.renderHud(s);
    this.scene3d.onPickBooth = (id) => this.showBoothCard(id);
    this.scene3d.setOcclusionEnabled(true);
  }

  private bindEvents(): void {
    this.el.btnPlan.addEventListener('click', () => this.setMode('plan'));
    this.el.btnWalk.addEventListener('click', () => this.setMode('walk'));

    this.el.toolbar.querySelectorAll('[data-tool]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const tool = (btn as HTMLElement).dataset.tool as Tool;
        this.planView.setTool(tool);
        this.el.toolbar.querySelectorAll('[data-tool]').forEach((b) => b.classList.toggle('active', b === btn));
      });
    });
    (this.el.toolbar.querySelector('[data-tool="select"]') as HTMLElement).classList.add('active');

    this.el.toolbar.querySelectorAll('[data-type]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const t = (btn as HTMLElement).dataset.type as BoothType;
        this.planView.setBoothType(t);
        this.el.toolbar.querySelectorAll('[data-type]').forEach((b) => b.classList.toggle('active', b === btn));
      });
    });

    const syncBatch = () => {
      this.planView.setBatchSize(
        Number((this.el.batchRows as HTMLInputElement).value) || 4,
        Number((this.el.batchCols as HTMLInputElement).value) || 6,
      );
    };
    this.el.batchRows.addEventListener('change', syncBatch);
    this.el.batchCols.addEventListener('change', syncBatch);

    // 搜索
    const input = this.el.searchInput as HTMLInputElement;
    input.addEventListener('input', () => this.renderSearch(input.value));
    input.addEventListener('keydown', (e) => {
      if (e.code === 'Enter') {
        const first = this.store.search(input.value)[0];
        if (first) this.gotoBooth(first.booth.id);
      }
      if (e.code === 'Escape') this.el.searchResults.style.display = 'none';
    });
    document.addEventListener('click', (e) => {
      if (!(e.target as HTMLElement).closest('.search-box')) {
        this.el.searchResults.style.display = 'none';
      }
    });

    // 数据 IO
    this.el.btnExport.addEventListener('click', () => this.exportData());
    this.el.btnImport.addEventListener('click', () => this.importData());
    this.el.btnRegen.addEventListener('click', () => {
      if (confirm('重新生成将覆盖当前全部展位，确定？')) {
        localStorage.removeItem(STORAGE_KEY);
        this.store.clear();
        this.store.addAll(generateHall());
        this.afterDataChange();
      }
    });

    // 遮挡查询开关
    let occ = true;
    this.el.btnOcclusion.addEventListener('click', () => {
      occ = !occ;
      this.scene3d.setOcclusionEnabled(occ);
      this.el.btnOcclusion.textContent = `遮挡查询: ${occ ? '开' : '关'}`;
    });

    // 展商入口
    this.el.btnPortal.addEventListener('click', () => this.openPortal());
    this.el.portalMask.querySelector('#portalCancel')!.addEventListener('click', () => this.closePortal());
    this.el.portalMask.querySelector('#portalSave')!.addEventListener('click', () => this.savePortal());

    // 多边形回车闭合
    document.addEventListener('keydown', (e) => {
      if (e.code === 'Enter' && this.mode === 'plan') this.planView.finishPolygon();
      if (e.code === 'Escape' && this.mode === 'plan') this.planView.cancelPolygon();
    });

    this.store.on('change', () => {
      this.minimap?.markDirty();
      this.renderPropPanel();
    });

    window.addEventListener('resize', () => {
      this.planView.resize();
      this.scene3d.resize();
    });
  }

  private loadOrGenerate(): void {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) {
      try {
        this.store.load(saved);
        this.flash(`已从本地恢复 ${this.store.booths.length} 个展位`, true);
      } catch {
        this.store.addAll(generateHall());
      }
    } else {
      this.store.addAll(generateHall());
    }
    this.afterDataChange();
  }

  private afterDataChange(): void {
    this.scene3d.rebuild();
    this.minimap?.markDirty();
    localStorage.setItem(STORAGE_KEY, this.store.serialize());
  }

  private setMode(mode: AppMode): void {
    this.mode = mode;
    this.el.btnPlan.classList.toggle('active', mode === 'plan');
    this.el.btnWalk.classList.toggle('active', mode === 'walk');
    document.getElementById('planViewWrap')!.classList.toggle('active', mode === 'plan');
    document.getElementById('walkViewWrap')!.classList.toggle('active', mode === 'walk');

    if (mode === 'walk') {
      cancelAnimationFrame(this.planRaf);
      this.scene3d.resize();
      this.scene3d.rebuild();
      this.scene3d.start();
      this.el.walkHint.classList.remove('hidden');
      setTimeout(() => this.el.walkHint.classList.add('hidden'), 6000);
    } else {
      this.scene3d.stop();
      this.startPlanLoop();
      this.planView.resize();
    }
  }

  private startPlanLoop(): void {
    const loop = () => {
      this.planRaf = requestAnimationFrame(loop);
      this.planView.render();
      const violationCount = this.store.violations.size;
      if (violationCount > 0) {
        this.el.statusLine.className = 'status-line error';
        this.el.statusLine.textContent =
          `⚠ ${violationCount} 个展位消防通道净距不足 ${HALL.fireLaneWidth}m（红色），请移开后再保存。`;
      } else {
        this.el.statusLine.className = 'status-line ok';
        this.el.statusLine.textContent =
          `共 ${this.store.booths.length} 个展位，消防通道全部达标（≥ ${HALL.fireLaneWidth}m）。`;
      }
    };
    this.planRaf = requestAnimationFrame(loop);
  }

  // ---------------- 搜索与导航 ----------------

  private renderSearch(q: string): void {
    const box = this.el.searchResults;
    const hits = this.store.search(q);
    if (!q.trim() || hits.length === 0) {
      box.style.display = 'none';
      return;
    }
    box.innerHTML = hits.map((h) => `
      <div class="item" data-id="${h.booth.id}">
        <span>${h.booth.exhibitor}</span>
        <span class="code">${h.booth.code}</span>
      </div>`).join('');
    box.style.display = 'block';
    box.querySelectorAll('.item').forEach((it) => {
      it.addEventListener('click', () => this.gotoBooth(Number((it as HTMLElement).dataset.id)));
    });
  }

  private gotoBooth(id: number): void {
    this.el.searchResults.style.display = 'none';
    const b = this.store.byId(id);
    if (!b) return;
    if (this.mode === 'plan') {
      this.planView.setSelected(id);
      this.flash(`已选中 ${b.code} · ${b.exhibitor}`, true);
    } else {
      const ok = this.scene3d.navigateTo(id);
      this.flash(ok ? `正在前往 ${b.code} · ${b.exhibitor}` : '无法到达该展位', ok);
    }
  }

  private showBoothCard(id: number): void {
    const b = this.store.byId(id);
    if (!b) return;
    const card = this.el.boothCard;
    card.style.display = 'block';
    card.innerHTML = `
      <h4>${b.exhibitor}</h4>
      <div class="muted">展位号 ${b.code} · 类型 ${b.type}</div>
      <div class="muted">位置 (${b.x.toFixed(1)}, ${b.z.toFixed(1)}) · ${b.w}m × ${b.d}m</div>
      <button class="btn primary" id="cardGo">走到这里</button>
      <button class="btn" id="cardClose">关闭</button>`;
    card.querySelector('#cardGo')!.addEventListener('click', () => {
      const ok = this.scene3d.navigateTo(id);
      this.flash(ok ? '开始自动寻路' : '无法到达', ok);
    });
    card.querySelector('#cardClose')!.addEventListener('click', () => (card.style.display = 'none'));
  }

  // ---------------- 属性面板 ----------------

  private renderPropPanel(): void {
    const panel = this.el.propPanel;
    const b = this.selectedBooth;
    if (!b) {
      panel.style.display = 'none';
      return;
    }
    panel.style.display = 'block';
    panel.innerHTML = `
      <h3>展位 ${b.code}</h3>
      <label>展商名称</label>
      <input id="propName" value="${b.exhibitor}" />
      <div class="row">
        <div><label>宽 (m)</label><input id="propW" type="number" step="0.5" value="${b.w}" /></div>
        <div><label>深 (m)</label><input id="propD" type="number" step="0.5" value="${b.d}" /></div>
      </div>
      <label>主题色</label>
      <input id="propColor" type="color" value="#${b.color.toString(16).padStart(6, '0')}" />
      ${this.store.violations.has(b.id) ? `<span class="violation-tag">消防净距不足，禁止保存此位置</span>` : ''}
      <div class="actions" style="margin-top:14px; display:flex; gap:8px; justify-content:flex-end">
        <button class="btn" id="propDelete">删除</button>
        <button class="btn primary" id="propSave">应用</button>
      </div>`;

    panel.querySelector('#propSave')!.addEventListener('click', () => {
      const next: Booth = {
        ...b,
        exhibitor: (panel.querySelector('#propName') as HTMLInputElement).value || b.exhibitor,
        w: Number((panel.querySelector('#propW') as HTMLInputElement).value),
        d: Number((panel.querySelector('#propD') as HTMLInputElement).value),
        color: parseInt((panel.querySelector('#propColor') as HTMLInputElement).value.slice(1), 16),
      };
      const check = this.store.canPlace(next, b.id);
      if (!check.ok) {
        this.flash(check.reason ?? '修改被拒绝', false);
        return;
      }
      this.store.update(next);
      this.afterDataChange();
      this.flash('展位信息已更新', true);
    });
    panel.querySelector('#propDelete')!.addEventListener('click', () => {
      this.store.remove(b.id);
      this.selectedBooth = null;
      panel.style.display = 'none';
      this.afterDataChange();
    });
  }

  // ---------------- 展商入口 ----------------

  private openPortal(): void {
    const mask = this.el.portalMask;
    mask.classList.add('open');
    const list = mask.querySelector('#portalList')! as HTMLElement;
    list.innerHTML = this.store.booths.slice(0, 60).map((b) => `
      <div class="item" data-id="${b.id}">
        <span>${b.code}</span><span class="muted">${b.exhibitor}</span>
      </div>`).join('');
    list.querySelectorAll('.item').forEach((it) => {
      it.addEventListener('click', () => {
        this.portalBoothId = Number((it as HTMLElement).dataset.id);
        list.querySelectorAll('.item').forEach((x) => x.classList.toggle('sel', x === it));
        const b = this.store.byId(this.portalBoothId)!;
        (mask.querySelector('#portalCode') as HTMLInputElement).value = b.code;
        (mask.querySelector('#portalName') as HTMLInputElement).value = b.exhibitor;
        (mask.querySelector('#portalColor') as HTMLInputElement).value =
          `#${b.color.toString(16).padStart(6, '0')}`;
      });
    });
    const claimed = JSON.parse(localStorage.getItem(EXHIBITOR_KEY) ?? '{}') as Record<string, string>;
    void claimed;
  }

  private closePortal(): void {
    this.el.portalMask.classList.remove('open');
  }

  private savePortal(): void {
    const mask = this.el.portalMask;
    const code = (mask.querySelector('#portalCode') as HTMLInputElement).value.trim();
    const name = (mask.querySelector('#portalName') as HTMLInputElement).value.trim();
    const color = parseInt((mask.querySelector('#portalColor') as HTMLInputElement).value.slice(1), 16);
    const b = this.portalBoothId >= 0 ? this.store.byId(this.portalBoothId) : this.store.byCode(code);
    if (!b) {
      this.flash('未找到该展位号', false);
      return;
    }
    this.store.update({ ...b, exhibitor: name || b.exhibitor, color });
    const claimed = JSON.parse(localStorage.getItem(EXHIBITOR_KEY) ?? '{}') as Record<string, string>;
    claimed[b.code] = name;
    localStorage.setItem(EXHIBITOR_KEY, JSON.stringify(claimed));
    this.afterDataChange();
    this.closePortal();
    this.flash(`展商信息已保存到 ${b.code}`, true);
  }

  // ---------------- HUD / IO ----------------

  private renderHud(s: FrameStats): void {
    const fpsCls = s.fps >= 55 ? 'good' : s.fps >= 40 ? '' : 'bad';
    const pickCls = s.pickMs <= 50 ? 'good' : 'bad';
    this.el.hud.innerHTML = `
      帧率 <b class="${fpsCls}">${s.fps.toFixed(0)} FPS</b>（帧耗 ${s.frameMs.toFixed(1)}ms）<br/>
      展位 <b>${s.booths}</b> · 视锥内 <b>${s.visible}</b> · 遮挡剔除 <b>${s.occluded}</b><br/>
      Draw calls <b>${s.drawCalls}</b> · 三角形 <b>${(s.triangles / 1000).toFixed(0)}k</b><br/>
      平均拾取延迟 <b class="${pickCls}">${s.pickMs.toFixed(2)}ms</b>`;
  }

  private exportData(): void {
    const blob = new Blob([this.store.serialize()], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `hall3d-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
    this.flash('已导出展馆数据', true);
  }

  private importData(): void {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'application/json';
    input.onchange = () => {
      const file = input.files?.[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => {
        try {
          this.store.load(String(reader.result));
          this.afterDataChange();
          this.flash(`导入成功，共 ${this.store.booths.length} 个展位`, true);
        } catch {
          this.flash('文件格式错误', false);
        }
      };
      reader.readAsText(file);
    };
    input.click();
  }

  private toastTimer = 0;
  private flash(msg: string, ok: boolean): void {
    const t = this.el.toast;
    t.textContent = msg;
    t.className = `toast show ${ok ? '' : 'error'}`;
    clearTimeout(this.toastTimer);
    this.toastTimer = window.setTimeout(() => (t.className = 'toast'), 2600);
  }
}

new App(document.getElementById('app')!);
