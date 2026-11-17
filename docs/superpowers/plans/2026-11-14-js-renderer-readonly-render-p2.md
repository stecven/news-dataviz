# P2 · JS 只读渲染器 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `frontend/` 里建一个只读渲染库：读 `pagelayout.json`（P1 已冻结的契约），用 D3 风格的手写 SVG 把它画成一整页，几何与 Python 的 `preview.png` 逐元素对得上；不做编辑（P3 才做）。

**Architecture:** 纯前端 ESM，无构建步骤（浏览器直接 `<script type="module">` 加载，Node 里 vitest 直接 import）。渲染分三层：`units.js` 负责 inch↔px 的取整口径（这是与 Python 对齐的关键），`theme.js` 是唯一读色值/字号的地方，`render/` 把 8 个图元画成 SVG 节点。整版 = 一个 `<svg>` + 每张卡片一个嵌套 `<svg viewBox>`（天然获得契约 C2 的卡片内相对坐标 + 天然裁切）+ 整版文本块 + 插图。D3 不引入依赖，只借它的做法（数据驱动、`<g transform>` 分组）；ECharts 属 v2（D4：黑盒图 v1 不做）。

**Tech Stack:** Node 24 + ESM。测试 vitest 2.1.9 + jsdom（不依赖 `getBBox`）+ sharp（把 SVG 光栅化做像素对拍）。**不引入 d3 / echarts / vite 运行时依赖**。

**Spec:** `docs/superpowers/specs/2026-11-12-pagespec-contract-and-js-renderer-design.md`（§5 契约规格、§6 库结构、§7 验收 V1/V2、§8 留给 builder 的决定）

---

## Scope Check

P2 只做「读图纸 → 画出来」。编辑（选中/拖动/改字/撤销）、CLI、MCP server、素材导出、`chart` 的 ECharts 实现、draw.io 出口都**不在**本计划里，各自单独立计划。因此本计划不产生任何写回图纸的代码路径。

Python 侧（`loop/`、`tests/`）**一行都不许改**。P2 全部落在 `frontend/`。

## Global Constraints

逐字来自 spec 与既有仓储约定，执行者不许"顺手修正"：

1. **单位是英寸不是 px**（spec C1）。契约里所有 `*_in` 保持英寸；px 换算只在 `units.js` 里发生，`PX_PER_IN = 100`（与 `loop/preview.py:13` 同值，**不是** 96）。
2. **卡片内元素坐标相对卡片左上角**（spec C2）。实测夹具卡片内 `frame` 元素在 `(0.0, 0.0)`，卡片本身的 `x_in/y_in` 才是版面上的绝对值。
3. **取整口径分两处，不能混**：
   - 单卡 `render_preview`（`loop/preview.py:51`）：画布与元素 box 都用 **`int()` 截断** → JS 用 `Math.trunc`。
   - 整版 `compose_preview`（`loop/render_page.py:148`）：画布、卡片贴图位置、`_draw_block` 的 x/y 都用 **`int(round())`** → JS 用 `Math.round`。
   - **但 `int(round(x))` 不是 `Math.round(x)`**：Python 的 `round()` 是 **half-to-even（银行家舍入）**，`Math.round` 是 half-up。实测真实产物里落 `.5` 的地方会分叉：`pxFromPt(9.0)`（= `9*100/72 = 12.5`）Python 得 **12**、JS 得 13，全 11 份夹具有 **12 个 `title` 元素**用 `font_pt = 9.0`；`roundPx(1.065)`（= `106.5`）Python 得 **106**、JS 得 107，有 **5 张插图的 `rect[1]`** 是 `1.065`。所以 `pxFromPt` / `roundPx` / `lineHeightPx` 一律走 `pyRound(x)`（half-to-even），`truncPx` / `boxPxTrunc` 仍走 `Math.trunc`。判据：`pxFromPt(9) === 12`、`roundPx(1.065) === 106`、`roundPx(1.825) === 182`。（**别用 `0.5625`**：`0.5625*100 = 56.25` 不落中点，两种口径都 56，验不出东西。）
4. **先画形状，后画文字**（`loop/preview.py:39 _render_order`）。半圆 sector 是整圆 PIE 的 180° 楔形，bbox 覆盖整个下半平面，先画文字会被盖掉。
5. **文字优先用契约里冻结的 `lines` 与 `font_pt`**（spec D10）。`loop/preview.py::_draw_text` 是现场重新折行、字号从 role 重算的，**不要照抄那部分**；只有 `lines` 为空的老样本才退回按 `text` 折行。
6. **最多画 4 行**（`loop/preview.py:164` 的 `lines[:4]`）。契约里的 `lines` 可能长于 4 行，JS 必须同样截断到 4 行，多出来的不画。
7. **颜色与字号只有一个来源**（`frontend/README.md:82` 铁律 1 + spec D11）。`frontend/src/` 下**除 `theme.js` 外**任何文件不许出现十六进制色值、不许出现写死字号——guard 已在 `tests/test_step36_contract_guards.py`，P2 一建 `frontend/src/` 它就从 skip 变真跑，每次提交前必须绿。
8. **契约里 `fill` 是不带 `#` 的 6 位 hex**（`loop/preview.py:172 _hex` 会补前导 `#`）。缺 `fill` 时用 `palette.surface`。
9. **不许手设 `xmlns`**：手动 `setAttribute('xmlns', ...)` 会让 sharp 报 `Input buffer has corrupt header: glib: XML parse error: ... Attribute xmlns redefined`。`XMLSerializer` 自己会加。
10. **不许用 `getBBox`**：jsdom 没有布局 API（`typeof el.getBBox === 'undefined'`）。文本宽度一律靠 `text-anchor` + 契约已冻结的折行，禁止现场测量。
11. **`npm install` 必须显式加 `--registry=https://registry.npmmirror.com`**（`registry.npmjs.org` 在本机不可达，会挂死）。
12. **`node_modules` 不入库**：新建 `frontend/.gitignore`（不要动仓库根的 `.gitignore`，那是高危文件）。
13. **不改 `loop/`、`tests/`、`ingest/`、`assets/`、`db/`、`CONTRIBUTING.md`、`.gitignore`、`.gitattributes`、`.github/`**（spec C6 + CODEOWNERS）。
14. **Python 全量测试必须一直绿**：`python -m unittest discover -s tests -t . -q` → `Ran 722 tests` / `OK`。注意：**T1 之前**是 `OK (skipped=1)`，那次 skip 就是 V6 guard（`frontend/src` 还不存在）；**T1 一建 `frontend/src/`，guard 立刻真跑，skip 数从 1 变 0**。测试总数 722 始终不变。任何 Task 里若看到 `skipped=1` 或总数变动，都是错的。
15. **整版块字号要按画布缩放并钳位**（`loop/palette.py::scaled_font_size` + `canvas_scale`）。`pt = max(6, min(24, round(font_size(style) * page_scale, 2)))`，`page_scale = min(width_in/baseW, height_in/baseH)`（基准取 `theme.base_canvas_in`，任一维 ≤0 返 1）。11 份样本恒 10×15 ⇒ `page_scale = 1.0` ⇒ 期望值不变（title 28px / body 15px）。卡片内文字**不走这条**：卡片的 `font_pt` 已是契约冻结值。
16. **`mountPage.on('warning')` 必须覆盖两个阶段**：`normalizeDoc` 的读契约警告 **和** `renderPage` 的渲染期降级警告（缺 `spec.elements`、插图资源取不到、`chart`/未知 type 占位）。只转发前者会让 v1 唯一的公开降级通道在"最该看见的地方"失效。

### 已知偏差（执行者须知，不要"顺手修正"）

- **`theme` 里没有 `line_height_ratio`（1.35），也没有角色别名表**。`palette.summary()` 只导出 10 个键，缺 `LINE_HEIGHT_RATIO` 与 `ROLE_ALIASES`。P2 **不扩 `palette.summary()`**（那属契约变更，要另开 spec 修订），改由 `src/theme.js` 持有这两个常量并注明出处，同时登记进 `frontend/README.md` 的已知限制。
- **JS 侧不做完整 JSON Schema 校验**。P2 的 `doc.js` 只做结构检查（必备键、类型、版本），给元素级错误消息；完整 schema 求值留 P3。理由：写一个 draft 2020-12 求值器是一个独立工程，而 V5 的权威校验已在 Python 侧（P1 Task 6）。
- **P2 不引入 Vite**。demo 页用原生 ESM，起一个静态服务器即可看。理由：P2 没有任何需要打包的东西，多一个构建链就多一处会坏的地方。等到 P3 需要打包成 npm 包时再引入。
- **描边差 1px 是已知且接受的**。Pillow 的 `draw.rectangle(..., width=2)` 向内画，SVG 的 `stroke-width="2"` 居中画。这类边缘像素在 V2 里单独记账，不进总体百分比。
- **字体靠系统**（spec D16）。不给 webfont；`font-family` 用 `"Microsoft YaHei", "微软雅黑", sans-serif`。缺字体的机器上 V2 会 skip。

## File Structure

| 路径 | 动作 | 责任 |
|---|---|---|
| `frontend/package.json` | Create | ESM，`"type":"module"`，devDeps: vitest 2.1.9 / jsdom / sharp；scripts: `test`、`test:ui` |
| `frontend/vitest.config.mjs` | Create | `environment:'node'`，`include:['test/**/*.test.mjs']` |
| `frontend/.gitignore` | Create | `node_modules/`、`coverage/` |
| `frontend/src/units.js` | Create | inch↔px，`trunc`/`round` 两套取整，`ascentPx`，`cardScale` |
| `frontend/src/theme.js` | Create | **唯一**允许出现色值/字号的读取层；`ROLE_ALIASES`、`LINE_HEIGHT_RATIO` 常量 |
| `frontend/src/doc.js` | Create | 读图纸 / 归一化 / 版本检查 / 结构校验 / 元素级错误 |
| `frontend/src/shapes/ticks.js` | Create | 照抄 `loop/thermo_shape.py:17 tick_rects` |
| `frontend/src/shapes/outline.js` | Create | 照抄 `loop/thermo_shape.py:48 outline_polyline`（含 `_quad`） |
| `frontend/src/render/text.js` | Create | `lines` + `font_pt` → `<text>` 多行（含基线、行高、4 行截断、三档对齐） |
| `frontend/src/render/primitives.js` | Create | rect / ellipse / arc / text / ticks / outline / image / chart 占位 |
| `frontend/src/render/stage.js` | Create | 整版骨架：画布 + 卡片嵌套 svg + 整版块 + 插图 + 绘制顺序 |
| `frontend/src/index.js` | Create | 公开 API `mountPage(container, doc, opts)` |
| `frontend/demo/index.html` | Create | demo 页（原生 ESM） |
| `frontend/demo/demo.js` | Create | 加载 `pagelayout.json` 并 mount |
| `frontend/test/helpers/svgwalk.mjs` | Create | 遍历 SVG、按 `data-el-id` 聚合、attr→inch 换算 |
| `frontend/test/helpers/golden.mjs` | Create | 定位 `out/demo/**` 金样本；不存在则 `null`（供 skip） |
| `frontend/test/units.test.mjs` | Create | T1 |
| `frontend/test/theme.test.mjs` | Create | T1 |
| `frontend/test/doc.test.mjs` | Create | T1 |
| `frontend/test/shapes.test.mjs` | Create | T2（与 Python 生成的期望点集对比） |
| `frontend/test/fixtures/thermo_shapes.json` | Create | T2 期望点集（由 Python 一次性生成后入库） |
| `frontend/test/primitives.test.mjs` | Create | T3 |
| `frontend/test/stage.test.mjs` | Create | T4 |
| `frontend/test/v1-structure.test.mjs` | Create | T5（V1 结构对拍） |
| `frontend/test/v2-pixels.test.mjs` | Create | T6（V2 像素对拍） |
| `frontend/README.md` | Modify | 补 JS 侧公开 API、取整口径、已知偏差 |

`frontend/src/` 里**不建** `render/chart.js`、`render/echarts.js`、`edit/*`、`io/*` —— 那是 P3/v2 的东西，现在建空文件只会让 V6 白扫。

## Review Focus

spec 隐含、但最容易咬人的六个点。每条都在指定 Task 的指定测试里钉住：

1. **截断 vs 四舍五入混用** → 差 1px 就会让整页错位累积。钉在 T1 `units.test.mjs::trunc_and_round_are_not_interchangeable`（用夹具里真实的 `3.37654 in` → trunc 337 / round 338）。
2. **`lines` 超过 4 行时没截断** → 卡片内文字溢出压到别的元素上，肉眼在缩略图里看不出来。钉在 T3 `primitives.test.mjs::text_never_draws_more_than_four_lines`。
3. **基线算错**（用 `dominant-baseline` 或想当然的 `0.8em`）→ 整块文字上下漂 2-6px，与 Python 对不上却不报错。钉在 T3 `primitives.test.mjs::text_baseline_matches_pillow_ascender`（断言 `y_attr == ink_top + ceil(px*1.058)`）。
4. **卡片内坐标没做嵌套变换**（把卡片内 `x_in` 当页面坐标用）→ 卡片内容整体偏移到页面左上角。钉在 T5 `v1-structure.test.mjs::card_element_coords_are_relative_to_card`。
5. **形状/文字绘制顺序反了** → 半圆卡的中心百分比文字被 sector 盖住（`loop/preview.py:39` 的原始 bug）。钉在 T4 `stage.test.mjs::text_nodes_come_after_shape_nodes_within_a_card`。
6. **`chart` 元素抛异常** → 老样本里没有 `chart`，但 P3 一接 ECharts 就会遇到；现在必须"退化画占位 + 记警告"而不是崩。钉在 T3 `primitives.test.mjs::chart_degrades_to_placeholder_without_throwing`。

---

## Task 1: 工程地基（units / theme / doc）

**Files:**
- Create: `frontend/package.json`、`frontend/vitest.config.mjs`、`frontend/.gitignore`
- Create: `frontend/src/units.js`、`frontend/src/theme.js`、`frontend/src/doc.js`
- Test: `frontend/test/units.test.mjs`、`frontend/test/theme.test.mjs`、`frontend/test/doc.test.mjs`

**Interfaces:**
- Consumes: 无（本 Task 是地基）
- Produces:
  - `units.js`：`PX_PER_IN = 100`、`PX_PER_PT = PX_PER_IN / 72`、`truncPx(inches)`、`roundPx(inches)`、`boxPxTrunc(el) -> [x0,y0,x1,y1]`、`pxFromPt(pt)`、`lineHeightPx(pt)`、`ascentPx(px)`、`cardScale(card, baseCanvasIn) -> number`
  - `theme.js`：`ROLE_ALIASES`、`LINE_HEIGHT_RATIO = 1.35`、`BORDER_ROLE = 'neutral_mid'`、`createTheme(themeObj) -> { color(role), fontPt(role), sectorStrokePt(), palette }`（`color` 对未知角色抛 `Error`，对齐 `loop/palette.py` 的 KeyError）
  - `doc.js`：`normalizeDoc(doc) -> { doc, warnings }`、`assertDoc(doc) -> void`（抛 `ContractError`-式的 `Error`，消息含 `$.cards[0].spec.elements[3].x_in` 这种路径）

- [ ] **Step 1: 建工程骨架（无测试，先让它能跑）**

```bash
cd frontend
npm install --registry=https://registry.npmmirror.com --save-dev vitest@2.1.9 jsdom sharp
```
`package.json` 手工写好 `"type":"module"`、`"private":true`、`"scripts":{"test":"vitest run"}`。`vitest.config.mjs` 里 `include` 写 `['test/**/*.test.mjs']`（**相对 config 所在目录**，写错会得到 `No test files found`）。`frontend/.gitignore` 写 `node_modules/` 与 `coverage/`。

- [ ] **Step 2: 写 units 的失败测试**

`units.test.mjs` 至少 6 条，逐条用夹具里的真实数字：

- `truncPx(3.37654) === 337`，`roundPx(3.37654) === 338`（这条就是 Review Focus #1）
- `boxPxTrunc({x_in:0.45,y_in:0.3,w_in:5.172,h_in:0.5})` 四个值各自截断，不是整体截断
- `pxFromPt(11.26) === 16`（`Math.round(11.26*100/72)`）
- `lineHeightPx(11.26) === 21`（`round(11.26 * 100/72 * 1.35)`）
- `ascentPx(17) === 18`（`ceil(17*1.058)`）；`ascentPx(6) === 7`
- `cardScale({w_in:6.072,h_in:3.37654}, [10,6])` ≈ `0.562757`，且宽高为 0 时返回 1（对齐 `palette.canvas_scale` 的兜底）

- [ ] **Step 3: 跑测试看它失败**

```bash
cd frontend && npm test -- units
```
预期：`Cannot find module '../src/units.js'` 之类的 import 错误。

- [ ] **Step 4: 实现 units.js**

只有换算与取整，不含任何绘制逻辑。`ascentPx` 的常数 `1.058` 是实测结论（`px=6..64` 与 Pillow `getmetrics()[0]` 零偏差；`1.059` 在 px=17/34/51 就错，`1.0625` 错 19 处），实现里加注释写明，别改。

- [ ] **Step 5: 跑 units 测试通过**

```bash
cd frontend && npm test -- units
```
预期：`6 passed`。

- [ ] **Step 6: 写 theme 的失败测试**

至少 5 条：

- `createTheme(pagelayoutTheme).color('text') === '#222222'`（经 `ROLE_ALIASES.text → neutral_dark`）
- `color('neutral_mid') === '#A8AEB6'`（直接命中 PALETTE，不经别名）
- `color('nope')` 抛错（对齐 Python 的"故意不炸不设默认值"）
- `fontPt('value') === 11`（经 `role_to_font.value === 'body'` → `font_sizes.body === 11`）
- `createTheme` 对缺 `palette` 的 theme 抛错（不许静默给空色板）
- `LINE_HEIGHT_RATIO === 1.35` 且 `ROLE_ALIASES.liquid === 'primary'`

- [ ] **Step 7: 跑测试看它失败**

```bash
cd frontend && npm test -- theme
```

- [ ] **Step 8: 实现 theme.js**

从 `doc.theme` 读，不 import 任何 Python 产物。`ROLE_ALIASES` 与 `LINE_HEIGHT_RATIO` 是**常量表**（值抄 `loop/palette.py:69` 与 `:146`），文件顶部注释写明"这两项契约里没有，出处是 loop/palette.py，属 P2 已知偏差"。**注意**：本文件允许出现色值（V6 豁免），但仍不许出现写死的字号数字——`fontPt` 必须查表。

- [ ] **Step 9: 跑 theme 测试通过，并立刻验证 V6 guard 变真跑**

```bash
cd frontend && npm test -- theme
cd .. && python -m unittest tests.test_step36_contract_guards -v
```
预期：theme 全绿；guard 三条全绿且 **`skipped=0`**（`frontend/src` 已存在，那条 `skipTest` 不再触发）。

- [ ] **Step 10: 写 doc 的失败测试**

至少 5 条，用 `tests/fixtures/contract/legacy/_plain.pagelayout.json` 与 `out/demo/auto_layout/pagelayout.json`（后者不在则 skip）：

- 读 1.0 样本：`warnings === []`、`doc.version === '1.0'`
- 读 0.x 样本（`_plain` 夹具，无 `version`/`theme`/`images`）：不抛，`warnings` 各含 `$.version` / `$.theme` / `$.images` 三条
- `assertDoc({})` 抛错，消息含 `$.width_in`
- `assertDoc(改坏 cards[0].spec.elements[0].x_in 为字符串)` 抛错，消息含 `$.cards[0].spec.elements[0].x_in`
- `normalizeDoc` 对缺 `rows` 的文档补 `rows: []`（P1 实测有 6 份老样本没有 `images` 键，同理兜底）

- [ ] **Step 11: 跑测试看它失败**

```bash
cd frontend && npm test -- doc
```

- [ ] **Step 12: 实现 doc.js**

结构校验只查"必备键存在 + 基本类型"，**不实现 JSON Schema 求值**（已知偏差）。错误消息必须带 JSONPath 风格路径，对齐 `loop/schema_check.py` 的习惯。

- [ ] **Step 13: 跑 doc 测试通过 + Python 全量回归**

```bash
cd frontend && npm test
cd .. && python -m unittest discover -s tests -t . -q
```
预期：JS 全绿；Python `Ran 722 tests` / `OK`（**没有 skipped**：Step 9 之后 `frontend/src/` 已存在，V6 guard 那条 `skipTest` 不再触发，skip 数从 1 变 0）。

- [ ] **Step 14: 提交**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vitest.config.mjs frontend/.gitignore frontend/src/units.js frontend/src/theme.js frontend/src/doc.js frontend/test/
git commit -m "feat(frontend): JS 渲染库地基——单位/主题/图纸校验（P2 Task 1）"
```

---

## Task 2: 复合图元照抄（ticks / outline）

**Files:**
- Create: `frontend/src/shapes/ticks.js`、`frontend/src/shapes/outline.js`
- Create: `frontend/test/fixtures/thermo_shapes.json`（生成后入库）
- Test: `frontend/test/shapes.test.mjs`

**Interfaces:**
- Consumes: 元素的 `x_in/y_in/w_in/h_in` + `geometry`
- Produces:
  - `ticks.js`：`tickRects(el) -> [[x,y,w,h], ...]`（英寸，自下而上）
  - `outline.js`：`outlinePolyline(el) -> [[x,y], ...]`（英寸，首尾闭合）、内部 `quad(p0,p1,p2,n=6)`

- [ ] **Step 1: 用 Python 生成期望点集夹具**

对 `out/demo/auto_layout/pagelayout.json` 里**所有** `ticks` 与 `outline` 元素，调 `loop.thermo_shape.tick_rects` / `outline_polyline`，把 `{ elId: { ticks: [...] } }` 写成 `frontend/test/fixtures/thermo_shapes.json`（浮点保留 12 位，`sort_keys`）。顺便挑一个单独的 `out/demo/end_to_end/thermometer/pagespec.json` 的元素也放进去，覆盖另一组 `geometry` 参数。

- [ ] **Step 2: 写 shapes 的失败测试**

- 逐元素、逐点 `assertClose(jsPoint, pyPoint, 1e-9)`（两边都是英寸，纯算术，不需要容差放水）
- `tickRects` 返回条数 === `geometry.count`，且**第一根在最下、最后一根在最上**（`i=0` 的 y 最大）
- `outlinePolyline` 首尾相等（闭合）且点数 === 期望里 Python 的点数。**实测夹具 `outline_1` 是 74 点**（半圆顶 9 + 右侧壁 1 + 右收口 `_quad(n=6)` 去掉重复端点后 6 + 球环 50 + 左收口 6 + 左壁 1 + 闭合 1）；**不要在这个数字上写 `>=`，写 `===`**
- 空 `geometry` 抛错（不给默认值，对齐"拼错参数就炸"）

- [ ] **Step 3: 跑测试看它失败**

```bash
cd frontend && npm test -- shapes
```

- [ ] **Step 4: 实现 ticks.js / outline.js**

逐行对照 `loop/thermo_shape.py:17-98` 抄。三处必须带注释：① `tick_rects` 的 `count-1-i` 是**自下而上**；② `outline_polyline` 以外接盒为锚（`ox = x_in - (cx - R)`、`oy = y_in - cap_top`）；③ 球环取 50 步是为了让 0°/90°/180° 极点**恰好落在采样点**上，改步数会让球泡看着被削平。

- [ ] **Step 5: 跑测试通过**

```bash
cd frontend && npm test -- shapes
```

- [ ] **Step 6: 验证 V6 guard 仍绿（本 Task 新增两个 `src` 文件）**

```bash
python -m unittest tests.test_step36_contract_guards -q
```

- [ ] **Step 7: 提交**

```bash
git add frontend/src/shapes/ frontend/test/shapes.test.mjs frontend/test/fixtures/thermo_shapes.json
git commit -m "feat(frontend): 温度计复合图元照抄 Python 几何（P2 Task 2）"
```

---

## Task 3: 图元渲染（text / rect / ellipse / arc / ticks / outline / image / chart）

**Files:**
- Create: `frontend/src/render/text.js`、`frontend/src/render/primitives.js`
- Test: `frontend/test/primitives.test.mjs`

**Interfaces:**
- Consumes: `units.js`、`theme.js`、`shapes/*`
- Produces:
  - `text.js`：`renderText(parent, el, { theme, pxPerIn, mode }) -> SVGGElement`；`mode` ∈ `{'card','block'}`（决定用 `el.font_pt` 还是按 role 查表）
  - `primitives.js`：`renderElement(parent, el, ctx) -> SVGElement[]`（返回该元素画出的所有节点，`ticks` 返回 N 个 `rect`）；`ctx = { theme, mode, resolveAsset, warnings }`；未知 `type` → 画占位并 push 一条警告，**不抛**

- [ ] **Step 1: 写 text 的失败测试**

- **Review Focus #2**：`lines` 有 6 行时只产出 4 个 `<text>` 节点，且第 5/6 行内容不出现在 SVG 字符串里
- **Review Focus #3**：`font_pt = 11.26`、`lines=['a']`、`align='left'`、盒高 `h_in` **恰好能放下一行**（`h == lineHeightPx(11.26)/100`，即 `dy=0`）→ 第一个 `<text>` 的 `y` 属性 === `boxTopPx + ascentPx(16)`；用 `ceil(px*1.058)` 复算一遍对上。**另立一条**用真实 `title`（`h_in=0.5`、`font_pt=11.26`，`boxPxTrunc` 得 `[45,30,562,80]`、`dy=14.5`）断言 `y === 61.5`——因为真实元素 `dy` 非零，`y` 不等于 `boxTopPx+ascent`。
- 行间距 === `lineHeightPx(font_pt)`（11.26 → 21）
- `align` 三档：`left` → `text-anchor="start"` + `x = x0`；`center`（缺省）→ `"middle"` + `x = x0 + w/2`；`right` → `"end"` + `x = x0 + w`
- `left` 且多行时整体垂直居中（`dy = (h - line_h*lines.length)/2`，不小于 0）；非 `left` 时 `dy = 0`
- `lines` 为空且 `text` 有值（老样本）→ 退回按 `text` 单行画，不崩

- [ ] **Step 2: 跑测试看它失败**

```bash
cd frontend && npm test -- primitives
```

- [ ] **Step 3: 实现 text.js**

基线用 `y = inkTop + ascentPx(px)`（alphabetic 基线），**不要**用 `dominant-baseline`（实测 `text-before-edge` 会多漂一整个行高）。`font-size` 用 `px`（不是 pt）。颜色从 `theme.color('text')` 取——契约里 text 元素全都**没有** `fill`（实测 20/20）。

- [ ] **Step 4: 写其余图元的失败测试**

每个图元一条，直接用夹具里真实元素的数字：

- `rect` + `role='frame'` → 一个 `<rect>`，`fill` 带 `#` 前缀，`stroke` 取 `geometry.border`，`stroke-width="2"`
- `rect` + `role='title_band'` → 一个 `<rect>`，**无 `stroke`**
- `rect` + `role='liquid'` → 走兜底分支：`fill` + `stroke = neutral_mid`（这是 `loop/preview.py:127` 的 else 分支，别当成 track）
- `rect` + `role='track'` → 一个 `<rect>` **无描边** + 一个半圆 `<path>`（管口圆头），断言节点数 === 2（加描边会在管口横一道直角灰线）
- `ellipse` → `<ellipse>`，`fill` + `stroke = neutral_mid`
- `arc` → 一个 `<path>`，`d` 里含两段弧线与 `Z`，`fill` + `stroke` 取 `theme.sectorStrokePt()` 对应的颜色；角度 180→194.4 时起点落在盒左端点
- `ticks` → N 个 `<rect>`，`fill` 取元素的 `fill`（`C9C9C9`）
- `outline` → 一个 `<polyline>`，`stroke-width="3"`，`fill="none"`，`stroke-linejoin="round"`
- `image`：`image_path` 存在且 `resolveAsset` 能取到 → 一个 `<image>`，`width/height` === `boxPxTrunc` 的宽高
- `image`：`resolveAsset` 返回 `null`（缺文件）→ 画虚线占位框 + push 警告，**不抛**（对齐 spec D13）
- **Review Focus #6**：`type='chart'` → 虚线占位 + 一条警告，不抛

- [ ] **Step 5: 跑测试看它失败**

```bash
cd frontend && npm test -- primitives
```

- [ ] **Step 6: 实现 primitives.js**

绘制分支顺序必须与 `loop/preview.py:66-127` 的优先级一致（`text` → `frame` → `title_band` → `ticks` → `outline` → `ellipse` → `arc` → `image` → `track` → 兜底）。`arc` 的 path：`M cx,cy L p(start) A R R 0 largeArc sweep p(end) Z`，角度按 y 向下、从 3 点方向起算（与 Pillow 一致），`largeArc = (end-start) > 180 ? 1 : 0`。

- [ ] **Step 7: 跑测试通过**

```bash
cd frontend && npm test
```

- [ ] **Step 8: 验证 V6 guard 绿 + 提交**

```bash
python -m unittest tests.test_step36_contract_guards -q
git add frontend/src/render/ frontend/test/primitives.test.mjs
git commit -m "feat(frontend): 八个图元的 SVG 渲染（P2 Task 3）"
```

---

## Task 4: 整版骨架 + 公开 API + demo 页

**Files:**
- Create: `frontend/src/render/stage.js`、`frontend/src/index.js`
- Create: `frontend/demo/index.html`、`frontend/demo/demo.js`
- Test: `frontend/test/stage.test.mjs`

**Interfaces:**
- Consumes: `doc.js`、`theme.js`、`units.js`、`render/primitives.js`
- Produces:
  - `stage.js`：`renderPage(container, doc, opts) -> { svg, warnings }`；`opts = { scale = 96, assetsBase = 'assets', resolveAsset }`。渲染时 px 换算仍按 `PX_PER_IN=100`，`scale` 只用于把结果缩放到容器（外层 `viewBox` + `width/height` 属性），**不要**把它混进取整口径。
  - `index.js`：`mountPage(container, doc, opts) -> { svg, doc, on(type, fn), destroy() }`。v1 只支持 `on('warning')`；`change`/`exportSVG` 是 P3 的接口，**现在不实现也不 stub 抛错**，留注释。

- [ ] **Step 1: 写 stage 的失败测试**

- 整页 `<svg>` 的 `width/height`（px）=== `roundPx(width_in)` / `roundPx(height_in)`（**整版用 round**，对齐 `loop/render_page.py:148`）
- 卡片数量 === `doc.cards.length`，每张卡片是一个**嵌套 `<svg>`**，其 `x/y` 是 `roundPx(card.x_in/y_in)`、`viewBox="0 0 <w> <h>"`（w/h 是卡片自己的 px 尺寸）
- **Review Focus #5**：单张卡片内，所有 `text` 节点的 DOM 顺序**晚于**所有形状节点（用 `Array.from(card.querySelectorAll('*'))` 的下标比较）
- 整版块：每个 `block` 产出 `lines.length` 个 `<text>`（`columns===1` 时），起始 `y = roundPx(block.y_in + 0.05) + ascentPx(px)`，行距 `lineHeightPx(px)`，其中 `px = pxFromPt(clampPt(fontSize(style)))`；空行不画但仍占一行高度
- 插图：`doc.images` 每张产出 1 个 `<image>`，位置 = `roundPx(placed.x_in + rect[0])`（`rect` 是盒内真实绘制矩形，**不许拉伸外盒**）
- `doc.images === undefined` 的老样本 → 不抛，当空数组
- `opts.resolveAsset` 收到的是 `image_path` 原文（`assets/icons/radiator_soft.png`）

- [ ] **Step 2: 跑测试看它失败**

```bash
cd frontend && npm test -- stage
```

- [ ] **Step 3: 实现 stage.js**

顺序：画布底色（`theme.color('surface')`）→ 卡片（嵌套 svg，卡内先形状后文字）→ 整版块 → 插图。卡片容器用 `<svg x= y= width= height= viewBox= overflow="hidden">`，**不要**用 `<g transform="translate()">`（`viewBox` 才自带裁切，实测已验）。不手设 `xmlns`。

- [ ] **Step 4: 跑测试通过**

```bash
cd frontend && npm test
```

- [ ] **Step 5: 写 demo 页并手工验一眼**

`demo/index.html` 用 `<script type="module" src="./demo.js">`，`demo.js` 里 `fetch('../out/demo/auto_layout/pagelayout.json')` 后 `mountPage`。跑 `python -m http.server 8765`（从仓库根）打开 `http://127.0.0.1:8765/frontend/demo/`，**截图留证**，与 `out/demo/auto_layout/preview.png` 并排贴到 `frontend/README.md` 的 demo 段（图放 `out/handoff/`，不入库）。

- [ ] **Step 6: 验证 V6 guard 绿 + 提交**

```bash
python -m unittest tests.test_step36_contract_guards -q
git add frontend/src/render/stage.js frontend/src/index.js frontend/demo/
git commit -m "feat(frontend): 整版渲染骨架与 mountPage 公开 API（P2 Task 4）"
```

---

## Task 5: V1 结构对拍

**Files:**
- Create: `frontend/test/helpers/svgwalk.mjs`、`frontend/test/helpers/golden.mjs`
- Test: `frontend/test/v1-structure.test.mjs`

**Interfaces:**
- Consumes: `renderPage`、夹具 `out/demo/**/pagelayout.json`（11 份）
- Produces: `svgwalk.mjs`：`collectByElId(svg) -> Map<string, SVGElement[]>`（**键是卡片定域的**，见下）、`attrToInch(node, attr) -> number`、`boxOf(nodes) -> [x0,y0,x1,y1]|null`；`golden.mjs`：`goldenDoc(relPath) -> object|null`、`demoLayoutPaths() -> string[]`（排序、缺失返回 `[]`）

- [ ] **Step 1: 写失败测试（V1）**

- **`collectByElId` 的键必须带卡片名**（实测缺陷，务必照做）：`frame`/`title_band`/`title`/`scale_note` 这四个 id **在每张卡片里都各有一个**（`auto_layout` 54 个卡片元素 / 4 个重复 id；11 份样本里凡 ≥2 卡的全部 `dups=4`）。按裸 `elId` 建索引会把卡1 的 `frame`(0,0,607,337) 与卡2 的 `frame`(0,0,607,496) 合并成 union bbox `[0,0,607,496]` → 假 FAIL。
  签名定为 `collectByElId(svg) -> Map<key, SVGElement[]>`，`key` 规则：卡片内元素 = `` `${cardName}\u0000${elId}` ``（遍历 `[data-card-name]` 容器取 `data-card-name`），页面级块/插图 = `elId` 本身。docstring 写上这条实测例子。
- 节点总数：**口径是「DOM 里带 `data-el-id` 的节点数」，且必须由公式推导，不许只写死总数。**
  - 卡片内推导公式（按元素累加）：形状（`rect` 非 track / `ellipse` / `arc` / `image`）各 **1**；`role='track'` **2**（矩形 + 下半圆 `<path>`）；`text` = **1 个 `<g>` + `min(非空行数, 4)` 个 `<text>`**；`ticks` = **`geometry.count` 个 rect**；`outline` **1** 条 `<polyline>`；占位（`chart` / 未知 type / 取不到图）**1**（只有虚线框；它挂的 `<title>` 不带 `data-el-id`，不计入）。
  - 页面级推导公式：每块 = **`line_groups.length` 个 `<g>`**（多栏块会出多个 `<g>`，且**共用同一个 `data-el-id`**）+ **非空行数** 个 `<text>`；每张插图 **1**。
  - 实测值（用上面两条公式算，与渲染逐份核对过 **11/11 零偏差**）：`auto_layout` 卡1 `heat_ratio_top5` = **116**、卡2 `heat_age` = **23**、页级 **10**、全页 **149**；`_plain` = **6**（3 块 × 1 行 × 1 组，**不是 3**）；`multicol` **154**、`multicol/_spread` **159**、`illustrated` / `illustrated/_no_asset` **154**、`illustrated/_spread` **151**、`page` **146**、`paper` **155**、`theme_match` **153**、`theme_match/_no_theme` **123**。占位卡（`multicol/_spread`、`page`、`paper`）每张 = **7**（frame 1 + title_band 1 + title 2 + scale_note 2 + 占位 1）。
  - **不要**用 `renderElement()` 的返回值计数（那是 104 / 15）：它把每个 text 的 `<g>` 只记 1 个、漏掉逐行 `<text>`，两套口径差恰为「非空行总数」。
  - 测试里把公式与逐项累加写成显式代码（每个分支一行 `expected += ...` 加注释），总数断言用累加结果而不是字面量；**对全 11 份样本逐份跑，每份一个带样本名的子用例**（失败时报出是哪份）。
- 逐元素 bbox 回算：**px 空间精确相等**，期望值在测试里内联算（**不调 `units.js`，避免自证**）：
  `exp = [Math.trunc(x*100), Math.trunc(y*100), Math.trunc((x+w)*100), Math.trunc((y+h)*100)]`，与渲染 attr **零容差**比对。
  **绝不写 `< 1e-6` 英寸**：渲染按整像素截断，回算成英寸必然差到 1px = 0.01in；实测全 11 份 `max |trunc(boundary) - inch*100| = 1.0`，天真的 1e-6 判据在卡1 单独就 68 个分量里 63 个失败。另加一条**只用于报错可读性**的英寸空间断言（容差 `1e-2`），不做闸门。
- bbox 回算只覆盖能精确回算的四类：`rect`（**非 track**）、`ellipse`、`image` / 占位。其余**必须跳过但要有显式计数断言**（`skipped === expected`，不许静默 `continue`）：`track` 是 2 节点且 cap 底部比元素盒底多 +22.36px；`ticks` 是 `count` 个 rect，并集不是元素盒；`outline` 只有 `points`；`arc` 只有 `d`（楔形只覆盖整圆盒的一部分）；`text` 的 `<g>` 无任何几何属性。实测可覆盖数：`auto_layout` 卡1 `12/39`、卡2 `2/15`，每页 **14** 个、px 空间 14/14 精确。
- `arc` 单独一条判据：从 `d` 里解析 `M cx,cy` 与 `A r r`，断言 `cx,cy` === 盒中心且 `r === box.width/2`（实测 5 个 sector 全精确：`353.5,305.5,123.5`）。
- **Review Focus #4**：卡1 的 `frame` 元素 `x_in=0`、卡片 `x_in=0.4` → 该 `rect` 的 `x` 属性必须 == `0`（相对卡片），而不是 `40`。
- `_plain` 夹具（0 卡片 3 块）：卡片数为 0 不抛，页级字符节点数 === **6**。
- **必须留一条不依赖金样本的判据**（`out/` 是 gitignore，fresh clone 上金样本组会 `skip`）：对一份极简合成 doc（1 卡 1 块，手写 3 个元素）断言节点公式成立。不许让整组在 fresh clone 上静默全绿。

- [ ] **Step 2: 跑测试看它失败**

```bash
cd frontend && npm test -- v1
```

- [ ] **Step 3: 实现 helpers + 让测试通过**

`attrToInch` 用 `parseFloat(attr) / PX_PER_IN`。`collectByElId` 只认 `data-el-id`，**键必须按卡片定域**（见 Step 1）。渲染侧每个元素的所有节点都已在 T3/T4 打上 `data-el-id`，本 Task 不需要回改 `src/`；若真发现漏打，先停下核对是不是口径理解错了（评审已实测 `MISSING=0`，唯一例外是占位框的 `<title>`，它本来就不该带）。

- [ ] **Step 4: 跑测试通过 + Python 回归**

```bash
cd frontend && npm test
cd .. && python -m unittest discover -s tests -t . -q
```

- [ ] **Step 5: 提交**

```bash
git add frontend/test/helpers/ frontend/test/v1-structure.test.mjs frontend/src/
git commit -m "test(frontend): V1 结构对拍——节点数与逐元素 bbox 回算（P2 Task 5）"
```

---

## Task 6: V2 像素对拍

**Files:**
- Test: `frontend/test/v2-pixels.test.mjs`

**Interfaces:**
- Consumes: `renderPage`、sharp、`out/demo/auto_layout/preview.png`、`out/demo/auto_layout/_cards/card_00_heat_ratio_top5.png`、`card_01_heat_age.png`
- Produces: `rasterize.mjs` 里的 `svgToPng(svg, {width, height}) -> Buffer`、`comparePixels(goldenBuf, mineBuf, mask) -> {considered, exact, within1px, edge, inner}`

- [ ] **Step 1: 写失败测试**

判据（全部来自实测，不要改数字）：

- **光栅化前必须把外层 `<svg>` 的展示尺寸改写成 viewBox 尺寸**：`renderPage` 缺省 `scale=96` → `width="960" height="1440"`，而金样本 `preview.png` 是 `1000×1500`（`PX_PER_IN=100` 口径）。不改写会直接 SIZE MISMATCH（sharp 出 960×1440）。做法：正则取 `viewBox="0 0 W H"`，把 `width="960" height="1440"` 替成 `width="W" height="H"`。改写后实测 `rasterized: 1000 x 1500`。
- 光栅化两边都 `.removeAlpha()`（**必做**：不这么做通道错位会把相似度砸到 49%，这是踩过的坑）
- **文字 bbox 掩膜必须用契约的 `x_in/y_in/w_in/h_in` 算，不能用 `<text>` 的 `x`/`y`/`font-size` 粗估**：粗估（宽 = 字数 × 字号）会多掩 30.55% 画面、把整页相似度压到 `94.97% ~ 95.60%`（**假红**）。用契约盒转 px 再外扩 2px 后，整页非文字像素 `1041690`，`exact 98.61% / 1px 99.09%`。
- 卡片级（**主判据**）：`card_00_heat_ratio_top5.png`(607×337) 与 `card_01_heat_age.png`(607×496) 的非文字像素，**1px 容差内 ≥ 98%**。实测：卡1 `exact 96.79% / 1px 99.37%`、卡2 `exact 99.04% / 1px 99.76%`。
- 整页级：`preview.png` 的**卡片区域内**非文字像素，1px 容差内 ≥ 98%。实测 `exact 98.22% / 1px 99.62%`（非文字像素 356810）。
- 差值分类记账：断言"描边差"（边缘带内的像素）占全部差异的 **≥ 60%**（实测卡1 98.8%、卡2 96.5%、整页 97.9%），其余差异打印出来（这条不静默放过，而是逼着实现者看清剩下的 2% 是什么）。
- `0.5` 平局用例（R12/R36 遗留）：显式加 `font_pt=9.0` 的 label 字号与 `y_in=1.825` 的 `roundPx` 两条断言，盯住 half-to-even 与 `Math.round` 的分歧（`pyRound(12.5)=12` 而 `Math.round(12.5)=13`；`pyRound(182.5)=182` 而 `Math.round(182.5)=183`）。差异记进边缘像素账本，不进总体百分比。
- 字体不可用（用 sharp 渲染一段中文探针得 0 暗像素）→ 整组 `skipTest`
- 金样本不存在（`out/` 未生成）→ `skipTest`，**但另留一条不依赖金样本的判据**：对合成 doc 光栅化后断言尺寸与背景色正确，不许整组静默全绿。

- [ ] **Step 2: 跑测试看它失败（并输出真实百分比）**

```bash
cd frontend && npm test -- v2
```
预期：先拿到一个数字（首轮很可能在 95-98% 之间）。**把这个数字写进回复，不要自己调阈值**。

- [ ] **Step 3: 按失败原因修渲染，不修阈值**

顺序：先查轴对齐（`trunc` vs `round`）→ 再查 `arc` 的 path 方向（`sweep` 反了会让扇形镜像）→ 再查 `track` 的圆头是否多画了描边 → 最后看 `outline` 的折线点数。每修一处重跑，记录百分比变化。

- [ ] **Step 4: 跑测试通过**

```bash
cd frontend && npm test
```
预期：全绿（或 v2 因缺字体/缺金样本 skip，但本机两者都在，**必须真跑绿**）。

- [ ] **Step 5: 提交**

```bash
git add frontend/test/v2-pixels.test.mjs frontend/src/
git commit -m "test(frontend): V2 像素对拍——1px 容差 ≥98% 且差值记账（P2 Task 6）"
```

---

## Task 7: 文档与收尾

**Files:**
- Modify: `frontend/README.md`
- Modify: `docs/superpowers/specs/2026-11-12-pagespec-contract-and-js-renderer-design.md`（只在 §9 分期表里把 P2 标成已完成 + 补一条"P2 落地时的偏差"引用，**不改任何决策**）

**Interfaces:**
- Consumes: 前六个 Task 的全部产出
- Produces: 无代码接口

- [ ] **Step 1: 补 `frontend/README.md`**

必须写清四件事：① 公开 API（`mountPage` 签名 + `opts` 各字段含义 + 返回值）；② **取整口径**（卡片内 trunc / 整版 round、`pyRound` 是银行家舍入、为什么）；③ 文字口径（优先用契约的 `lines`/`font_pt`、最多 4 行、基线用 ascent、整版块按画布缩放并钳位到 `font_pt_clamp`）；④ 五条已知偏差（`line_height_ratio` 与 `ROLE_ALIASES` 在 `theme.js` 里、无完整 schema 校验、无 Vite、描边 1px、字体靠系统）。

另加两条**必须写**的操作须知（都是实测踩出来的）：
- **`assetsBase` 与 `image.path` 会双拼**：契约里 `image.path` 已经是 `assets/icons/xxx.png`（自带 `assets/` 前缀），而缺省 `assetsBase` 也是 `'assets'` ⇒ 拼出 `assets/assets/icons/xxx.png`。要么传 `resolveAsset` 覆盖（demo 就是这么做的：`(path) => '../../' + path`），要么传 `assetsBase: ''` —— 但**注意 `''` 会拼出前导斜杠**（模板是 `${base}/${path}`），浏览器从根路径解析。两条路选一条，别默认值直接用。
- **`on('warning')` 覆盖两个阶段**：`normalizeDoc` 的读契约警告 + `renderPage` 的渲染期降级警告（缺 `spec.elements`、插图取不到、`chart`/未知 type 占位）。要么订阅它、要么降级就是静默的。

**保留原有三条铁律原文不动**。

- [ ] **Step 2: 更新 spec 的分期表**

`§9` 表里 P2 行加 `✅ 已完成（2026-11-14）`，并在 §9 下方加一句"P2 的五条已知偏差见 `frontend/README.md`"。除此外不动 spec。

- [ ] **Step 3: 全量回归**

```bash
cd frontend && npm test
cd .. && python -m unittest discover -s tests -t . -q
```
预期：JS 全绿；Python `Ran 722 tests` / `OK`（无 skipped）。

- [ ] **Step 4: 越界核查**

```bash
git diff --stat HEAD~6..HEAD
git status --porcelain
git diff --name-only HEAD~6..HEAD | grep -E '^(loop/|tests/|ingest/|assets/|db/|CONTRIBUTING\.md|\.gitignore|\.gitattributes|\.github/)' || echo "NO OUT-OF-SCOPE FILES"
```
预期：越界清单为空；`node_modules` 不在 `git status` 里。

- [ ] **Step 5: 提交并推送**

```bash
git add frontend/README.md docs/superpowers/specs/2026-11-12-pagespec-contract-and-js-renderer-design.md
git commit -m "docs(frontend): JS 渲染库公开 API、取整口径与五条已知偏差（P2 Task 7）"
git push -u origin frontend/pagespec-contract
```

---

## Self-Review

**1. Spec 覆盖**

| spec 要求 | 落在哪 |
|---|---|
| §6 库结构（`src/{index,theme,units,doc}.js`、`shapes/`、`render/`） | T1/T2/T3/T4 的 Files 表 |
| §6 公开 API `mountPage` | T4 |
| §7 V1 结构对拍（容差 1e-6） | T5（**改判**：`1e-6` 英寸做不到——渲染按整像素截断，回算必然差 1px。改成 px 空间精确相等 + 公式推导节点数，理由见 T5 Step 1） |
| §7 V2 像素对拍（结构重合度） | T6（阈值取实测：1px ≥98%，抠文字 bbox） |
| §7 V6 主题单一来源 | T1 Step 9 起每个 Task 都验 |
| §5.5 八个图元 | T3（7 个）+ T3 的 `chart` 占位分支 |
| §5.5 `ticks`/`outline` 照抄 `thermo_shape.py` | T2 |
| §8 只出 ESM / 不上 TS / 命中测试用 SVG hit-testing | 只出 ESM：T1；不上 TS：全局（无 `tsconfig`）；hit-testing 属编辑，P3 |
| spec §9 说 P2 含 `demo/` 页 | T4 Step 5 |

未覆盖且**故意**未覆盖：`edit/*`、`io/*`、`render/chart.js` 与 `echarts.js`（P3/v2）、完整 schema 校验（登记为已知偏差）。

**2. Step 扫描**：每个 Task 都是"写失败测试 → 跑它看失败 → 最小实现 → 跑通 → 提交"的循环；没有任何 Task 只有实现没有测试；T7 是文档任务，用全量回归代替新测试。

**3. 类型一致性**：`boxPxTrunc` 返回四元组数组（不是对象）；`tickRects`/`outlinePolyline` 返回点数组的数组；`renderElement` 一律返回节点数组（即使只有一个），`renderText` 返回 `<g>`；`ctx` 对象在各 Task 间保持 `{ theme, mode, resolveAsset, warnings }` 同一形状。

**4. Review Focus**：六条各自钉死的测试见该节表格，六条全部有 owner Task 和具体 test method。

**5. 篇幅比例**：本计划约 470 行，spec 553 行 —— 计划与 spec 同量级，没有把 spec 抄一遍。

---

## Execution Handoff

计划已写完，两种执行方式：

1. **subagent-driven-development（推荐）** —— 每个 Task 派一个全新的 implementer subagent，每轮后派 reviewer 复核，我在中间记账；P1 的七个 Task 就是这么跑的，两次抓出"绿但没在验"的测试。
2. **executing-plans** —— 我自己一路做下来。

推荐 **1**，理由：P2 的视频/像素判据比 P1 更容易出"看起来绿了其实没验"的坑（V1 的节点数、V2 的通道与掩膜），fresh reviewer 对着 diff 复算比我自己复查更可靠。
