# frontend/ · 前端出图线

这条线干的事：**调用绘图引擎，把数据（和素材库里的图）变成人能看的图像**。
爬图片、写数据库不在这一线——那些在 `ingest/`。

## 归属与边界

| 你负责 | 不要碰 |
|---|---|
| `frontend/`（界面、调用层） | `ingest/`（爬虫与入库脚本） |
| `loop/`（求解、渲染、排版、编排） | `assets/`（别人采的图） |
| `docs/`、`tests/`（公共） | `db/assets.db`（**只读，唯一写者是素材线**） |

## 三档出图入口

| 场景 | 入口 | 产出 |
|---|---|---|
| 单张卡片 | `loop/scaffold.py::build_pagespec(points, chart_title=..., template_name=..., target_width_in=..., target_height_in=...)` | `PageSpec` → `loop/render.py` / `render_arc.py` / `render_thermo.py` |
| 整版版面 | `loop/layout.py::flow_layout(LayoutSpec(...), [TextBlock(...), CardSpec(...), ImageBlock(...)])` | `PageLayoutSpec` → `loop/render_page.py::render_layout(...)` |
| 全自动 | `loop/compose.py::compose_page(text, out_dir, column_count=2, ...)` | 拆段 + 匹配数据 + 组流 + 出图一条龙 |

最省事的试法（不写代码）：

```bash
python scripts/build_theme_match_demo.py    # 自动编排 + 按文本主题配插图
python scripts/build_multicol_demo.py       # 2 栏排版 + 卡片跨栏
python scripts/build_illustrated_demo.py    # 图文并茂 + 跳过验证
```

## JS 只读渲染库（P2）

`frontend/src/` 是一个**零依赖、只读**的渲染库：吃一份 `pagelayout.json`，
吐一页 `<svg>`。它不改文档、不回写 JSON、不猜数据 —— 换色换字号一律照文档里的
`theme` 来。

两个公开入口：

| 入口 | 签名 | 用途 |
|---|---|---|
| `renderPage` | `renderPage(container, doc, opts) -> { svg, warnings }` | 一次性渲染，返回节点与降级告警 |
| `mountPage` | `mountPage(container, doc, opts) -> { svg, doc, on, destroy }` | 带生命周期的挂载，v1 只支持 `on('warning', fn)`（`change` / `exportSVG` 留给 P3） |

### 公开 API

```js
import {
  mountPage, renderPage, normalizeDoc, assertDoc, ContractError,
  createTheme, CONTRACT_VERSION,
} from './src/index.js';

const page = mountPage('#stage', doc, {
  scale: 96,                                // 只管外层 <svg> 的展示尺寸，不参与任何 px 换算
  assetsBase: 'assets',                     // 缺省值；与 image.path 会双拼，见「两条操作须知」
  resolveAsset: (path) => `../../${path}`,  // 给了就原样转发原文 path，不再拼 assetsBase
});

page.svg;    // SVGSVGElement
page.doc;    // 归一化后的副本（深拷贝 + 补缺省键），不是调用方传进来的那个对象
page.on('warning', (msg) => console.warn(msg));  // 注册时补发挂载阶段已产生的全部警告
page.destroy();  // 幂等：摘掉 svg、清空订阅者，之后 on() 会抛
```

**`opts` 只有三个字段**（`renderPage` / `mountPage` 同一份）：

| 字段 | 缺省 | 含义 | 踩错会怎样 |
|---|---|---|---|
| `scale` | `96` | 每英寸展示像素数，**只写进外层 `<svg>` 的 `width`/`height`** | 混进任何坐标取整→与 Pillow 像素结果错开。非正数直接抛 |
| `assetsBase` | `'assets'` | 图片前缀，模板 `${assetsBase}/${path}` | 与自带前缀的 `image.path` 双拼成 `assets/assets/...` |
| `resolveAsset` | 无 | `(path) => href`，**收到的是原文 path、不做预拼** | 返回 `null`/`''` 时退化成虚线占位框 + 一条警告 |

**没有 `editable` 参数**：编辑属 P3，`change` / `exportSVG` / `relayout` 现在既不实现也没有假 stub——`on('change')` 注册不抛但永远不会有事件。

`mountPage` 内部顺序是 **`normalizeDoc` → `createTheme` → `renderPage`**：`theme` 缺失会在建 DOM **之前**抛（不留一棵画了一半的空 SVG）。

其余导出：

| 导出 | 用途 |
|---|---|
| `renderPage(container, doc, opts) -> { svg, warnings }` | 一次性渲染；`container` 可为选择器 / DOM 节点 / `null`（只建不挂） |
| `normalizeDoc(doc) -> { doc, warnings }` | 宽松读契约（深拷贝、补缺省键、**不抛**） |
| `assertDoc(doc)` | 受限结构校验，不合规抛 `ContractError`（`err.errors` 是 `[{ path, message }]`） |
| `ContractError` | 上面那个错误类 |
| `createTheme(themeObj)` | 色板/字号访问器；缺 `theme` / `palette` / `font_sizes` 直接抛 |
| `CONTRACT_VERSION` | 契约版本字面量 `'1.0'` |

### 取整口径（最容易踩的一处）

内部坐标固定 `PX_PER_IN = 100`，**两套取整不可互换**——它们是 Python 侧的两种真实行为，
不是笔误。每个出口都必须显式选边，库故意不提供「默认取整」：

| 画什么 | 走哪个函数 | 对应 Python | 口径 |
|---|---|---|---|
| 卡片**内**元素几何（rect/ellipse/arc/text 盒、ticks、outline 锚点） | `truncPx` / `boxPxTrunc` | `int(...)` | `Math.trunc`，向零截断 |
| 整版块 `x`/`y`、插图 `x`/`y`/`width`/`height` | `roundPx` / `boxPxRound` | `int(round(...))` | `pyRound`（银行家舍入） |
| 卡片容器 `<svg>` 的 `width`/`height`/`viewBox` | `truncPx` | `int(...)` | `Math.trunc` |
| 卡片容器 `<svg>` 的 `x`/`y` | `roundPx` | `int(round(...))` | `pyRound` |
| 外层 `<svg>` 的 `width`/`height`（展示尺寸） | `pyRound(scale * in)` | — | `pyRound` |
| 外层 `<svg>` 的 `viewBox` | `roundPx` | — | `pyRound` |
| 字号 `px`、行高 | `pxFromPt` / `lineHeightPx` | `int(round(...))` | `pyRound` |
| 文字基线抬升 | `ascentPx` | Pillow `getmetrics()[0]` | `Math.ceil(px * 1.058)` |

**卡片容器的 `x`/`y` 用 `pyRound`、`width`/`height`/`viewBox` 用 `trunc`** —— 混成一种会让
整张卡缩 0.3%。真实卡1 是 `w=6.072 → 607`、`h=3.37654` 走 trunc 是 **337**、走 round 是
**338**（差 `1/338 = 0.296%`，就是那 0.3% 的来源）；它贴在 `y = 239`
（`2.3875 × 100 = 238.75`，round 进位到 239，trunc 会落 238，差 **1px**）。

**为什么有 `pyRound`，不能直接用 `Math.round`**：Python 的 `round()` 是 half-to-even（银行家舍入），
JS 的 `Math.round` 是 half-up，恰好落 `.5` 时分叉。真实产物里有两处分叉是可观测的：

- **字号 `font_pt = 9.0`** → `9 × 100/72` 在双精度里**精确**等于 `12.5`。`pyRound(12.5) = 12`，
  `Math.round(12.5) = 13`。全 11 份产物里有 **12 个** `title` 元素用这个字号，差 1px 字号会让
  墨迹宽多 8%、基线再低 1px。
- **插图 `rect[1] = 1.065`** → `106.5`。`pyRound` 给 106、`Math.round` 给 107，**5 张插图**受影响。

反过来，`truncPx` 用 `Math.trunc` 是**对的**：Python `int()` 就是向零截断，两者本来就一致，
别顺手改成 `Math.floor`（负坐标会错）或 `pyRound`（尺寸会整体偏大）。

> 一句话记法：**卡内截断、整版四舍五入；四舍五入必须走 `pyRound`。**

### 文字口径

- **行优先用契约里冻结的 `lines`，不要自己折行。** 卡片元素取 `el.lines`（其次 `geometry.lines`），
  整版块取 `geometry.lines`（其次 `el.lines`）；两者都空时才退回 `[el.text]` 当**唯一一行**画。
  折行由 Python 排版层（`loop/text_flow.py`）算好写进图纸，渲染器再折一次就与冻结结果错开。
- **字号分两套**：卡片用 `el.font_pt`（已按卡片缩放并钳位，渲染器**不再缩放**）；
  整版块用 `theme.fontPt(style)` 乘页面缩放比 `pageScale`、保留两位小数，再钳进
  `theme.fontPtClamp()`（缺省 `[6, 24]`）。卡片 `font_pt` 为 `null`/`undefined`/`''` 时**直接抛**
  ——静默当 0 会画出彻底不可见的字；`font_pt = 0` 不抛。
- **最多画 4 行**（`MAX_LINES = 4`），第 5 行起丢弃。**空行占行距但不落笔**（`continue`）。
- **基线**：`y = 盒顶 + dy + i × 行高 + ascent`，其中 `ascent = ceil(px × 1.058)`。
  `dy` 只在 `align = 'left'` 且盒高够高时非零（`max(0, (盒高 - 行高×行数) / 2)`），另外两档与
  整版块（`noDy`）恒为 0。
- **行距** = `pyRound(pt × 100/72 × 1.35)`，注意是拿**未取整**的 px 去乘：11.26 磅 →
  `round(15.6388… × 1.35) = 21`，先取整再乘会得到 22。
- **`align` 三档只用 `text-anchor`，绝不用 `getBBox`**：`left → start`、`center → middle`、
  `right → end`，`x` 由盒边界算（`left` 取 `x0`、`right` 取 `x1`、`center` 取中点）。
  jsdom 根本没有 `getBBox`，真实浏览器里用它也会让测试依赖布局结果。
- 基线用 alphabetic（默认），**不要加 `dominant-baseline="text-before-edge"`** —— 实测会多漂一整行高。

### 两条操作须知（都是实测踩出来的）

**① `assetsBase` 与 `image.path` 会双拼。** 契约里 `image.path` 已经是
`assets/icons/radiator_soft.png`（自带 `assets/` 前缀），而缺省 `assetsBase` 也是 `'assets'`，
模板是 `${base}/${path}` ⇒ 拼出 `assets/assets/icons/radiator_soft.png`，图片必然取不到。
两条路**选一条**，别直接用缺省值：

```js
// 路 A：传 resolveAsset 覆盖（demo/demo.js 就是这么做的）
mountPage('#stage', doc, { resolveAsset: (path) => `../../${path}` });

// 路 B：传 assetsBase: '' —— 注意会拼出**前导斜杠** `/assets/icons/x.png`，从站点根解析
mountPage('#stage', doc, { assetsBase: '' });
```

**② `on('warning')` 覆盖两个阶段。** 收到的是**合集**：`normalizeDoc` 的读契约警告
（缺 `version`/`images`/`theme`、版本不匹配）+ `renderPage` 的渲染期降级警告
（卡片缺 `spec.elements`、插图资源取不到、`chart` 或未知 type 画虚线占位）。
**不订阅就是静默降级**——降级本身不抛，只在 `warnings` 数组里留档。

### 五条已知偏差（别当成 bug 反复修）

| # | 偏差 | 后果 |
|---|---|---|
| 1 | `line_height_ratio`（1.35）与 `ROLE_ALIASES` **不在契约 `theme` 里** | 它们是 Python 的模块级常量，JS 侧落在 `frontend/src/theme.js`（1.35 的数值定义在 `units.js`，由 `theme.js` re-export，只此一处）。Python 侧改系数时 JS **不会自动跟**，得两边同改 |
| 2 | **没有完整 schema 校验** | `assertDoc` 只查必备键 + 基本类型 + 元素 `type` 枚举，不求值 JSON Schema。权威校验在 Python `loop/contract.py::dump_layout`——JS 放行的文档仍可能被 Python 拒 |
| 3 | **没有 Vite**，也不打算加 | 原生 ESM + `python -m http.server`。没有打包、没有路径别名、没有 HMR；`import` 必须写相对路径并带 `.js` 扩展名。`package.json` 的依赖只有 devDependencies（`vitest` / `jsdom` / `sharp`） |
| 4 | **描边差 1px** | Pillow 的 `width=2` 是**向内**画，SVG 的 `stroke-width` 是**居中**画，卡片边框外侧恒差约 1px。V2 的 98% 阈值主要就是给这条留的（见下「最窄余量」） |
| 5 | **字体靠系统**，不给 webfont | JS 侧不设 `font-family`，吃浏览器默认。机器上缺「微软雅黑」（`C:/Windows/Fonts/msyh.ttc`，Python 侧硬编码于此）时，V2 的字形探针渲不出暗像素 → 整组像素对拍 `skip` |

### V2 判据的最窄余量：98.79%，只有 0.79pp

V2 像素对拍的主判据是**卡片级「1px 容差内 ≥ 98%」**（`frontend/test/v2-pixels.test.mjs`
里的 `MIN_WITHIN_1PX_PCT = 98`）。11 份 demo、15 张有单卡金样本的卡片全部达标，但**最窄处是
`multicol/_spread` 的占位卡 `placeholder`：98.79%**（450×497，`considered = 191618`，
精确命中 97.96%，描边差占比 100.0%）。余量只有 **0.79pp**。

**改渲染时留神，别把这条当宽松阈值**——任何让边缘再多偏 1px 的改动都可能直接判红。

### demo 页

```bash
python -m http.server 8765          # 从仓库根起（demo 要读 out/ 与 assets/）
```

浏览器打开 <http://127.0.0.1:8765/frontend/demo/>，页面会 `fetch`
`out/demo/auto_layout/pagelayout.json` 再 `mountPage` 画出来。

同一份 `pagelayout.json` 的两个后端并排（左：Python Pillow；右：本库 JS/SVG）：

| Python `loop/render_page.py` | JS `frontend/src/render/stage.js` |
|---|---|
| ![Python 整版](<../out/handoff/frontend-preview.png>) | ![JS 整版](<../out/handoff/frontend-demo.png>) |

两张图都落在 `out/handoff/`（`out/` 被 gitignore，不入库）。

## 契约：`pagelayout.json` 与 `theme`

整版版面的数据契约冻结在 **`frontend/schema/pagelayout.schema.json`**（版本 `1.0`）。
Python 侧的读入口是 `loop/contract.py::load_layout`（**宽松**：0.x 老文档缺
`version` / `theme` / `images` 照样读得进来，缺什么降级成 `warnings`，不抛），
写入口是 `loop/contract.py::dump_layout`（**严格**：补齐 `version` / `theme` 后过
schema，不合规抛 `ContractError`）。

**颜色与字号只能从图纸的 `theme` 取。** `theme` 是 `loop/palette.py::summary()`
的原样产物（色板、字号层级、扇区顺序、画布基准、`role_to_font` 全在里面），
它随每份 `pagelayout.json` 一起发出去，所以 JS 渲染库不需要自己带一份色板。

因此 `frontend/src/` 里**禁止**出现：

- 十六进制色值字面量（`#rgb` / `#rrggbb` / `#rrggbbaa`，大小写都算）；
- 函数式颜色（`rgb()` / `rgba()` / `hsl()` / `hsla()`，参数以数字开头）；
- 写死的字号（`font-size: 12px`、`fontSize = 14`、`ctx.font = "12px sans"`、
  `font: 12px/1.5 sans`、`font-size: 1.2rem`）。

**守卫当前识别的形态**（`tests/contract_fixtures.py::find_hardcoded_theme_tokens`，
清单与实现同步维护）：

| 形态 | 例子 | 是否拦截 |
|---|---|---|
| `#` + 3/6/8 位十六进制 | `"#C01F2A"` / `"#abc"` / `"#00ff0080"` | 拦 |
| `rgb()` / `rgba()` / `hsl()` / `hsla()` | `"rgb(192,31,42)"` | 拦 |
| `font-size:` / `fontSize=` / `font:` + 数字 | `fontSize = 14` / `font: 12px/1.5 sans` | 拦 |
| 含 `font` 的语句里的 `\d+px` / `\d+pt` | `ctx.font = "12px sans"` | 拦 |
| `0x` 十六进制字面量 | `0xC01F2A` | **不拦**（见下） |
| 尺寸类长度 | `style.width = "100px"` / `border: "1px solid"` | 不拦（不是字号） |

`0x` **不在覆盖范围内**是有意的：`0xFFFFFF` 与位运算掩码（`& 0xFFFFFF`、
`| 0xFF`）在文本上无法区分，认了会误伤位运算。写死颜色的正路是 `#` 或
`rgb()`，`0x` 本来就不在契约鼓励的写法里。

正确写法是从 `theme` 里按角色取：

```js
const c = theme.palette.primary;      // 而不是 "#C01F2A"
const pt = theme.font_sizes.title;    // 而不是 20
```

**唯一例外是 `frontend/src/theme.js`** —— 它就是读取层（把 `theme` 解析成
一组访问器的那一层），色值字面量天然归它管。

守这条规则的是 `tests/test_step36_contract_guards.py`
（`tests/contract_fixtures.py::find_hardcoded_theme_tokens` 提供扫描器）：
扫 `frontend/src/**/*.js`，放过 `theme.js`，其余有命中就报出文件与行号。
P1 阶段还没有 `frontend/src/`，那条用例会 skip —— 守卫先落地，等 P2 建了目录自动生效。

## 铁律

1. **颜色与字号只有一个来源**：`loop/palette.py`。渲染层出现十六进制色值或 `Pt(10)` 会被测试判红。
2. **折行在排版层算**：`loop/text_flow.py` 折好行写进规格，PPTX/PNG 两个后端照抄。代价是 PPTX 关掉了 `word_wrap`，在 PowerPoint 里改字号不会自动重排。
3. **模板里不许有裸数字**：坐标只能是 `@参数名` 或约束表达式，数值走参数表（`tests/test_step2_templates.py` 在守）。
4. **校验器不信自报值**：`validate_spec` 从几何逐条重新推导，所以「自洽地错」也会被抓——新增图元时记得同步补校验。
5. **数据库只读**：`loop/asset_lookup.py` 一律 `mode=ro`；要新素材 → 开 issue 找素材线。

## 加一个新图形的步骤

1. 在 `loop/templates.py` 写 `TemplateSpec`（参数表 + 约束声明 + 图元表），先在 `TEMPLATES` 里注册为占位；
2. 写测试（先红）：几何手算锚点 + 约束违背必须抛 `SolveError`；
3. 在 `loop/solve.py` 实现求解器并挂进 `_SOLVERS`，同时补 `_chk_*` 校验；
4. 需要新图元类型的话，加渲染分支（`loop/render*.py` 与 `loop/preview.py` 同口径），并进 `loop/render_page.py` 的整版渲染；
5. 补 `docs/` 与 `.superpowers/sdd/.../progress.md` 的对应步骤记录。

## 怎么跑测试

```bash
cd frontend && node node_modules/vitest/vitest.mjs run   # 8 个文件，421 条
cd .. && python -m unittest discover -s tests -t . -q     # 722 条
```

（`frontend/` 下也可以直接 `npm test`，它跑的就是 `vitest run`。）

**金样本在 `out/`，而 `out/` 被 gitignore。** 全新克隆上 `out/demo/**/pagelayout.json`
与 `out/demo/**/preview.png` 都不存在，此时：

- 依赖金样本的组会**整组 skip**（`stage.test.mjs` 47 条、`primitives.test.mjs` 31 条、
  `doc.test.mjs` 6 条、`theme.test.mjs` 8 条、`v1-structure.test.mjs` 5 条、
  `v2-pixels.test.mjs` 5 条，合计 102 条）。本机全量是 `8 files / 421 tests`；
  无金样本时是 `Tests 242 passed | 102 skipped (344)`、`0 failed`，退出码 0。
  **skip 本身是设计如此，不是坏了。**
- `renderElement（其余图元）` 那 15 条同样依赖 `out/demo/page/` 的金样本，无样本时整组 skip。
- 兜底靠**不依赖金样本的「合成 doc」判据**：V2 那 10 条（光栅化尺寸与背景色 4 条、
  0.5 平局 half-to-even 3 条、文字掩膜口径护栏 3 条）与 V1 的 7 条，手写极简 doc 现场断言，
  永远真跑。不许让整组在 fresh clone 上静默全绿。
- 要真跑金样本组，先生成它们：`python scripts/build_theme_match_demo.py` /
  `build_multicol_demo.py` / `build_illustrated_demo.py` 等（产出落在 `out/demo/`）。

Python 侧 `Ran 722 tests` / `OK` 且 **`skipped=0`** 是硬判据：总数或 skip 数一变就说明有问题
（P1 阶段那条 skip 是 V6 guard 等 `frontend/src/` 出现，P2 建好后自动真跑）。
stderr 里 `Image.Image.getdata is deprecated`（Pillow 14 的移除预告）与本次无关。

## 已知限制（别当成 bug 反复修）

- 半圆图分项 > 5 判「不适用」，走占位图兜底；「全相等」档缺专门素材。
- 图文混排只做上下型 + 栏内均分，没有两侧文字环绕；段落不回填上一行空栏。
- 球泡与管身的接合用折线近似，400% 放大可见轻微折角。
