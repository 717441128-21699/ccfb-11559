# 云展馆 · 三维漫游与布展编辑

浏览器内运行的展会三维展馆系统：底图布展编辑 + 第一人称三维漫游，面向 **5000 个展位**
规模，在普通办公电脑独显上以 60 FPS 为目标。纯 TypeScript + Three.js + Vite，无后端依赖，
数据存 localStorage，可导入/导出 JSON。

## 运行

```bash
npm install
npm run dev        # 开发服务器
npm run build      # 类型检查 + 生产构建
npm run preview    # 预览构建产物
```

逻辑层冒烟测试（Node，不依赖浏览器）：

```bash
npx tsx scripts/smoke.ts
```

无头浏览器端到端验证（先 `npm run dev`，再启动带 `--remote-debugging-port` 的 Chrome）：

```bash
node scripts/cdp-test.mjs       # 渲染/帧率/HUD/搜索
node scripts/cdp-editor.mjs     # 底图绘制/拾取/异形/擦除
node scripts/cdp-firelane.mjs   # 消防净距拦截与标红
node scripts/cdp-portal.mjs     # 展商入口/遮挡开关/持久化
node scripts/cdp-features.mjs   # 门头排版/小地图
```

## 功能与需求对照

| 需求 | 实现 |
| --- | --- |
| 底图画展位，规则批量生成、异形手画 | `ui/PlanView.ts`：矩形/批量（行列拖框）/多边形（双击或回车闭合）/擦除，0.5m 吸附 |
| 按类型生成三维模型，门头写展商名 | `three/geometry.ts` 五类共享模板；`three/SignAtlas.ts` 把门头名打包进 2048 纹理图集 |
| BVH 视锥剔除 | `core/bvh.ts` 二维 BVH + `three/CullingSystem.ts` 八交点视锥测试 |
| 遮挡剔除用硬件查询 | WebGL2 `ANY_SAMPLES_PASSED`，每代理盒一个查询、隔帧轮询，时间切片（默认每帧 4 个） |
| 相同模型实例化合批 | 每类展位的墙体/门头各一个 `InstancedMesh`，全馆主体仅约 12 个 draw call |
| 门头字自动缩字/折行 | `three/signText.ts`：先缩字到下限，仍超宽则折两行 |
| 搜索后自动寻路绕开展台 | `nav/PathFinder.ts` 0.5m 栅格 A* + 视线弦切；`nav/WalkController.ts` 自动行走与滑动碰撞 |
| 小地图同步位置 | `ui/Minimap.ts` 静态层离屏缓存，每帧只画箭头/路线 |
| 消防通道 <4m 实时标红、禁止放置 | `data/BoothStore.ts` 的 `canPlace`/`recomputeViolations`，底图与三维同步红色 |
| 5000 展位 60 FPS、拾取 <50ms | 实例化 + 图集 + 双级剔除；拾取走 BVH 粗筛 + slab 射线求交，实测亚毫秒 |

## 架构

```
src/
├── core/          纯逻辑：BVH、几何工具、配置、可复现随机数
├── data/          BoothStore（数据中枢/消防规则/搜索）、规则生成器
├── nav/           栅格 A* 寻路、第一人称行走控制器
├── three/         Three.js 渲染：实例化、纹理图集、剔除、拾取、路线、场景编排
├── ui/            2D 底图编辑器、小地图
├── types.ts
└── main.ts        应用装配与 UI 交互
```

关键设计：

- **数据单一来源**：`BoothStore` 同时服务底图、三维、寻路，编辑后重建 BVH、实例缓冲与
  阻挡栅格，三个视图不会出现状态漂移。
- **合批优先**：同类型展位共享一份几何体，配合 `aCull` 实例属性在着色器里把被剔除实例
  坍缩为退化三角形，避免每帧重写实例矩阵缓冲。
- **消防规则语义**：贴邻（共享隔断，gap=0）合法；只有“正对方向最近邻居”的净距落在
  (0, 4m) 且缝隙未被第三个展位占据时才判违规，隔位展位不会被误报。
- **遮挡查询无阻塞**：查询对象池轮转，只在结果可用时读取，不造成 CPU/GPU 同步停顿；
  近处 18m 内豁免，避免走近展位时闪现。

## 已知边界

- 异形（手画多边形）展位的三维表现为占位盒 + 门头，未做任意多边形挤出；其消防校验按
  包围盒保守处理。
- 无头测试环境回退到 SwiftShader 软渲染（上限约 20 FPS），真实独显上的帧率请在本机
  `npm run dev` 后查看左上角 HUD。
- 数据持久化使用 localStorage（约 700KB/5800 展位），超大规模需切换到 IndexedDB。
