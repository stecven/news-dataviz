# 可编辑报纸版式：图纸契约 + JS 渲染库（设计文档）

- 日期：2026-11-12
- 状态：待评审（brainstorming 阶段产出，未动工）
- 相关：`docs/superpowers/specs/2026-11-09-end-to-end-review.md`、`README.md`、`ONBOARDING.md`、`frontend/README.md`、`out/排版项目_对话记录.md`、会话记录 m00001–m00080
- 已过一轮 builder check（独立 subagent 对着真实代码与样本复核，结论已并入本文，见 §12）

---

## 0. 一句话

把已有的 Python 排版引擎当作"排版大脑"**保持不动**，把它已经在写的产物 `pagelayout.json` 提升为**跨语言、跨出口的唯一契约**；在 `frontend/` 里建一个 JS 库，读这份契约在网页上画出**每个元素都可编辑**的报纸版面；最后把整条线包成 CLI + MCP server，让 Codex / DSH / Claude Code 都能做到"输入数据和文案，输出可编辑报纸"。

---

## 1. 为什么做（背景与动机）

### 1.1 用户的诉求

用户原话（m00001）：

> 这是一个绘制可编辑新闻版式的项目，目前画图是靠 ppt 自己画，效果不好，所以需要做一个前端 js 可视化库。

用户原话（m00065）：

> 我的最终目的是把这个项目做成 codex 的插件，输入数据和文案，输出一个报纸的可编辑内容，画图可接入前端 js 库和 draw.io 等工具。

"排版项目"会话第 3 轮里用户已经说清过产品的形状：

> 当前目标不是做一个跟原图一样的，而是做一个项目实现自动化排版，各个元素可编辑……实际使用也没有原图作为参考，只有数据和文本，你根据内容自主从数据库中选择插图。

所以：**输入是数据和文案，不是参考图；输出是能改的版面，不是一张图。**

### 1.2 现状（实测，非推断）

- 仓库 `D:\appmy\news-dataviz`，`origin = git@github.com:stecven/news-dataviz.git`，8 个提交，只有 `main`。
- `loop/` 6342 行 Python，`tests/` 8064 行 / 676 个 unittest。流水线：数据 → 选型 → 约束求解 → 单卡渲染 → 整版排版 → 自动编排 → 主题配图。出口是 python-pptx 生成的原生可编辑 PPTX。
- **`frontend/` 目录存在但只有 `frontend/README.md`（3076 字节）**，全库 0 个 `.js/.ts/.tsx/package.json`。前端一行代码都没有。
- `frontend/README.md` 已有三条"铁律"，其中铁律 2 是「**折行在排版层算**：`loop/text_flow.py` 折好行写进规格，PPTX/PNG 两个后端照抄」；铁律 1 是「**颜色与字号只有一个来源**：`loop/palette.py`」。本文的两条核心决定（D10 / D11）本质上是在**还这两条铁律的欠账** —— 详见 §1.4。

### 1.3 关键发现：图纸其实已经存在

这一点改变了整件事的工作量估计。

`loop/compose.py:527 compose_page()` 已经写出 `<out_dir>/pagelayout.json`（= `loop/layout.py:401 PageLayoutSpec.to_dict()`），里面**已经是一份完整的整版图纸**：

- 画布：`width_in` / `height_in` / `margin_in` / `gutter_in` / `column_count` / `column_gutter_in`
- `rows[]`：行（`kind` / `y_in` / `h_in` / `items`）
- `cards[]`：卡片最终外部坐标（`x_in`/`y_in`/`w_in`/`h_in`/`row`/`column_span`）+ **内嵌完整 `spec`（单卡 PageSpec）**
- `blocks[]`：正文块，坐标 + `columns` / `column_gutter_in` + **`lines` / `line_groups`（已经折好行）**
- `images[]`：插图，`path` + `asset_id` / `tag` / `semantic` + `rect`（盒内真实绘制矩形，"永不变形、居中留白"）

对 `out/demo/auto_layout/pagelayout.json` 做图元普查，**整版只用到 14 种 `(type, role)` 组合、7 个绘制原语**：

| type | role | 出现 |
|---|---|---|
| `rect` | `frame` / `title_band` / `track` / `liquid` | 4 种 |
| `ellipse` | `bulb` | 1 种 |
| `arc` | `sector` | 1 种 |
| `text` | `title` / `scale_note` / `label` / `value` / `legend` / `center` | 6 种 |
| `ticks` | `ticks` | 1 种（复合） |
| `outline` | `outline` | 1 种（复合） |
| `image` | 插图 | 未在该样本出现 |

**结论：缺的不是"引擎"，是"能读这份图纸、画出来还能改"的渲染器。** v1 的工程量是一个 7 原语的渲染器 + 编辑层，不是重写 4500 行引擎。

### 1.4 顺带发现的两个欠账（builder check 复核出来的）

**(1) 铁律 2 在卡片路径上从来没落实。**

实测 `out/demo/auto_layout/pagelayout.json`：

- 页面级 `blocks`：4/4 带 `lines`（折好了）
- **卡片内 20 个 `text` 元素：0 个带 `lines`**

也就是说卡片里的标题、图例、标签、数值**没有预折行**，两个后端各干各的：

- `loop/preview.py:132 _draw_text` 的 docstring 自己写着：「PPTX 端靠 `word_wrap=True`；PNG 端 Pillow 不自动换行，这里手动做等价处理」—— 它按逐字符宽度折行，**只取前 4 行**（`lines[:4]`），字体写死 `C:/Windows/Fonts/msyh.ttc`
- PPTX 侧 `loop/text_style.py` 把 `word_wrap=True` 交给 PowerPoint 自己排

**同一个规格，PNG 和 PPTX 的卡片文本折行结果可以不一样。** 这与铁律 2 直接冲突。D10 就是修这个。

**(2) 色板和字号确实有一个来源，而且已经能导出。**

`loop/palette.py:283 summary()` 已经产出结构化摘要：

```python
{"palette": {...}, "sector_order": [...], "font_sizes": {...},
 "base_canvas_in": [10.0, 6.0], "font_pt_clamp": [6.0, 24.0],
 "sector_stroke": {"color_role": "neutral_mid", "pt": 0.5},
 "role_to_font": {...}, "min_adjacent_delta_e": 20.0,
 "min_text_contrast": 4.5, "problems": [...]}
```

但 `pagelayout.json` 的元素里**没有** `font_pt`、没有文字颜色、没有描边宽、没有画布底色 —— 渲染器要用到的信息一个都没进契约。`tests/test_step19_palette.py:18-19` 的 `RENDER_FILES` 只扫描四个 `.py` 文件，**JS 完全不在扫描范围**，所以 JS 里硬编码色值不会被判红 —— 但会违反成文铁律。D11 就是修这个。

### 1.5 为什么现在做

PPT 出口的天花板已经摸到了：排版算得再准，落到 PPT 上就是 PPT 积木，观感被 PPT 框架卡死（用户 m00001 的"效果不好"）。而"可编辑"这件事，PPT 其实已经做到了 —— 真正缺的是**一个不受 PPT 审美约束、又能被人直接改的出口**。

---

## 2. 目标 / 非目标 / 反目标

### 2.1 目标（v1）

- **G1 契约冻结**：把 `PageSpec` + `PageLayoutSpec` 写成有版本号、有文档、跨语言的 JSON Schema（`spec.schema.json`），并补齐渲染器真正需要的字段（主题、字号、折行）。
- **G2 JS 渲染库**：`frontend/` 里一个库，读图纸 → 画可编辑 SVG；元素级选中 / 拖动 / 改文本 / 改样式；把编辑结果导出回图纸 JSON。
- **G3 保真对拍**：同一份图纸，JS 画的版面与 Python 的 `preview.png` 结构一致（见 §7）。
- **G4 插件外壳**：CLI + MCP server，agent 能"给文案和数据，拿回可编辑版面"。

### 2.2 非目标（v1 不做，但留接口）

- **N1** 不把 Python 引擎搬进浏览器（方案 B 已否决，理由见 §4-D1）。
- **N2** 不做 draw.io 出口，只在出口接口上留位置（理由见 §4-D8）。
- **N3** 不做多页 / 多期排版，先一页。
- **N4** 不做协同编辑。
- **N5** 不做"前端自己算折行"（见 D10 —— 折行由 Python 算好写进契约）。
- **N6** 不做素材库（`ingest/` 爬虫、`db/assets.db`）的改造，完全不动。浏览器打不开 SQLite 的问题用"导出静态资源目录"绕开（D13）。
- **N7** 不做"前端重新决定版面"（见 D15 与反目标 A3；用户 2026-11-12 已确认）。
- **N8** 不做"编辑后的图纸回引擎重排 / 再出 PPTX"。读回入口照建（D14），但 v1 不接这条路（用户 2026-11-12 拍板）。
- **N9** 不补插图素材集。素材库现状（1 张整版大图 + 7 个淡化图标、无语义标注插图）留在原地，v1 只保证插图槽位能正确渲染（用户 2026-11-12 拍板）。

### 2.3 反目标（技术上跑通了也算失败）

- **A1 让用户拖柱子。** 柱子/液柱的长度 = 数值 × 比例。让人拖着改长度，等于把数据弄脏，下次重算就打回原形，或者更糟——数据和图形对不上还留在版面上。正确做法是**改数字，图形跟着重算**。
- **A2 图纸里出现 ECharts 的 option。** 那等于把契约绑死在 ECharts 上，draw.io / PPTX 出口直接读不懂。契约必须后端无关。
- **A3 JS 侧自己生成版面。** 那会变成两套引擎，两边算出不同结果，永远对不上，也永远不知道谁对。JS 侧只做"读图纸 → 画 → 改字段"，不做"决定摆哪多大"。
- **A4 为了好看牺牲可编辑性。** 任何"导出一整张 PNG 交付"的方案在这个项目里都是失败，因为用户的诉求就是可编辑。

---

## 3. 约束

- **C1 单位是英寸，不是 px。** 全库坐标字段都是 `*_in`。JS 侧用一个 `scale`（px per inch，默认 96）换算，同一份图纸可以任意缩放渲染。契约里不引入 px。
- **C2 卡片内元素坐标是相对卡片左上角的。** 实测：卡片 `frame` 元素在 `(0.0, 0.0)`，而卡片的 `x_in`/`y_in` 才是版面上的绝对值。渲染必须做嵌套变换。这是最容易踩的坑，写进 schema 的描述里。
- **C3 契约必须后端无关。** 不得出现任何渲染库特有字段（ECharts option、draw.io XML 片段、PPTX 形状 XML）。
- **C4 现有 676 个 unittest 不能挂。** 契约变更必须向后兼容：新字段一律可空、放在 dataclass 末尾 —— `loop/models.py:35` 已经有这条约定，沿用。
- **C5 浏览器打不开 SQLite。** `db/assets.db` 是 SQLite，`image_path` 是相对项目根的磁盘路径。v1 用"导出静态资源目录 + URL 前缀"解决（D13），不改数据库。
- **C6 目录所有权。** `.github/CODEOWNERS` 把 `/frontend/` 与 `/loop/` 划给前端线；`/ingest/`、`/assets/`、`/db/` 的解析逻辑不碰。高危文件（`CONTRIBUTING.md`、`scripts/*.py`、`.gitignore`、`.gitattributes`）也不碰。

---

## 4. 已定的决策（含考虑过的其他方案）

### D1 引擎留在 Python，不搬进浏览器

考虑过两条别的路：

- **B｜JS 重写引擎**：把 `loop/` 那 4500 行核心逻辑（求解、脚手架、框架、拟合、排版、断行、编排、选型、模板）连同 676 个测试搬进 JS。能让库完全独立，但代价是把整个项目重写一遍。
- **Pyodide｜把 Python 引擎跑在浏览器里**：技术上可行，但要多下 ~10MB 运行时、性能差，而且和"JS 可视化库"这个定位正面冲突。**不推荐**，此处仅记录它存在。

**决定：都不选。** 理由是用户 m00065 的最终目的：插件是 agent 在本地或服务端调用的，**引擎根本不需要进浏览器**。这一条直接把 B 的 4500 行重写省掉。

> 这是**我的判断**，不是用户拍板的结论。如果用户希望库能脱离服务端独立跑完整流程，这条要推翻。

### D2 `pagelayout.json` 就是唯一契约，不新造格式

本来准备新设计一份 `spec.schema.json`。但 §1.3 的普查说明：**要造的东西已经存在，而且结构是对的**（画布 / 行 / 卡片 / 正文块 / 内嵌单卡规格，两层分离干净）。它只是没冻结、没版本、没文档、没有第二个实现去读它。

所以 v1 = 给现有产物写 schema + 补少量字段 + 保证向后兼容，**不是重新设计**。

### D3 双层表达：图元层是硬契约，语义层是可选元数据

- **图元层** `elements[]`（`rect` / `ellipse` / `arc` / `text` / `ticks` / `outline` / `image`）是**所有出口的公共底线**。draw.io、PPTX、SVG、ECharts 都能画这 7 个原语，所以任何出口都保证能出图。
- **语义层**（现有 `chart_key` / `chart_title` / `scale`，v1 补一个 `chart: {kind, series, encoding}`）是**可选元数据**，给"改数据 / 换图型 / 重新选型"用，也给需要原生图表对象的出口（PPTX 原生图表、ECharts）用。
- **出口优先用图元层**；语义层拿不到就退化。**任何出口不得要求图纸里有它专属的东西**（对应反目标 A2）。

### D4 前端绘图分工：D3 是主力，ECharts 是预备队

用户 m00080 给了导师的建议：Apache ECharts + D3.js。核实后的判断：

**现状下 ECharts 一个都用不上。** 图纸里全是 `rect`/`ellipse`/`arc`/`text` 原始图元（一张温度计卡 = 5 × (rect + outline + rect + ellipse + ticks + 2×text)），ECharts 没有对应物。

**D3 是主力**，三个理由：

1. 它直接操作 SVG DOM（[d3-selection](https://d3js.org/d3-selection)：*"Selections allow powerful data-driven transformation of the document object model (DOM): set attributes, styles, properties, HTML or text content"*），而这正是"可编辑"的基础 —— 每个图元是一个真 SVG 节点，能选中、能挂事件、能改属性。
2. `d3-scale` 管"数值 → 长度/位置"，`d3-shape` 管 `arc`/`pie`/`line`，正好覆盖现有图元和未来图型。
3. 用 D3 的子模块 ESM，天然 tree-shakeable。

**ECharts 的价值在下一步兑现**：当版面上要出"标准图型"（柱状、条形、饼图、折线、雷达、地图）时，自己写渲染器就是浪费。ECharts 从 v4.0 起提供 SVG 渲染器（`echarts.init(el, null, {renderer: 'svg'})`，见[官方 Canvas vs SVG](https://echarts.apache.org/handbook/en/best-practices/canvas-vs-svg/)），并且有 `gauge` 系列可以直接画半圆仪表盘（[示例](https://blog.csdn.net/Young_Gao/article/details/80311026)）—— 恰好对上引擎已经会选的两个图型。

**进契约的方式**：图纸里加一个图元类型 `type: "chart"`，内容是**抽象描述**（`kind` + `series` + `encoding`），不含任何 ECharts 字段。JS 出口自己决定把它交给 ECharts 还是 D3 画。这样 ECharts 是**可替换的实现**，不是契约的一部分。

**要付的代价**：两个库都进 bundle。ECharts 用 `echarts/core` 按需引入，D3 用子模块，都可控。

**可编辑性的分野（重要，直接影响 v1 范围）**：

- ECharts 画的东西在它自己的 SVG 根里 —— 是**黑盒图**：可整体移动 / 缩放 / 换数据，**不可拆解内部**。
- D3 画的图元是**白盒图**：每个是 SVG 节点，可选中 / 拖动 / 改属性。

**v1 只有白盒。黑盒图留到 v2 扩图型时才引入。**

### D5 编辑模型：改数据 / 改字段，不拖图形

（对应反目标 A1）

- **白盒元素**（标题、正文、矩形、椭圆、弧、刻度、轮廓、插图）：可自由选中、拖动、改文本、改颜色。
- **图表元素**：只能改它绑定的数据和标题，图形由引擎重算 —— 人碰不到"液柱多长"这个数。
- 唯一的例外是"拖到别的位置 / 改框的大小"，那是版面自由度，不污染数据。

### D6 文本编辑与重排：v1 改字不重排，打 `stale` 标记

`blocks[]` 里正文**已经折好行**（`lines` / `line_groups`，见 `loop/layout.py:251-254`），D10 之后卡片内文本也会带上。改一个字，这些行就作废。三条路：

- **(a) 改字后回传 Python 重排** —— 保真最好，但需要引擎在线，JS 库不独立。
- **(b) JS 侧实现断行** —— 库独立，但要维护两份字体度量，字体差异必然导致细微不一致，而且等于把 `loop/text_flow.py` 的逻辑重写一遍（对应反目标 A3 的同类风险）。
- **(c) v1 只改字不重排** —— 超宽告警 + 给元素打 `stale: true`。

**决定：v1 走 (c)，同时把 (a) 做成一个可选回调 `relayout(text, style) → lines`。** 理由：断行质量直接决定报纸观感，两份实现保证不了一致；而 v1 要验的是"契约 + 绘图 + 编辑"这条链能不能通，不是断行。链通了再决定 (a) 还是 (b)。

### D7 插件外壳 = CLI + MCP server，不做 Codex 专属

一份适配多处：Codex 用 `.codex/config.toml` 挂 MCP，DSH、Claude Code 也接。引擎本来就是 Python，MCP server 用 Python 写最省事。

### D8 v1 不做 draw.io 出口

`draw.io` 是通用画板，本库是领域专用排版机，差别在"谁在做决定"。嵌 draw.io 当编辑器要写「mxGraphModel XML ↔ 图纸 JSON」双向映射，还得先回答"人把液柱拖歪之后谁赢"（人拖的 vs 数据算的）—— 这是 D5 同一个问题的另一种形态。

第一版该验的是最难、最不可替代的部分：**数据 → 图形的推导 + 可编辑渲染**。等能稳定出图、有了真实编辑需求，再决定"自写薄编辑器"还是"嵌 draw.io"。

### D9 版本化契约

`PageLayoutSpec` 增加 `version` 字段（新样本写 `"1.0"`）。JS 库读到不认识的**主版本**要明确报错，不猜。

### D10 卡片内文本的折行也进契约（修铁律 2 的欠账）

（背景见 §1.4(1)）

**决定：契约给卡片内每个 `text` 元素补 `lines`（和 `font_pt`），由 Python 侧在出图纸时算好。** 渲染器一律"照抄行，不自己折行"。

- 计算口径统一到一处：沿用 `loop/text_flow.py::wrap()` 的度量，把 `loop/preview.py::_draw_text` 里那套逐字符折行搬进规格生成阶段。
- 卡片里的 `text` 用的是 `role`（`title`/`label`/`value`/`legend`/`center`/`scale_note`）而不是 block 的 `style`（`title`/`body`/…），适配层要接上 `loop/palette.py::ROLE_TO_FONT` 与 `FONT_SIZES`。
- **顺带修掉一个老问题**：现在 PNG 和 PPTX 的卡片文本折行结果可以不一样（一个 Pillow 手折、一个交给 PowerPoint）。补了 `lines` 之后两个后端就真的照抄同一份了。

> 这是**我的判断**。它确实要动 `loop/`（改产物、可能碰测试），但属于"把已经算出来的东西写进产物"，不是改排版规则 —— 见 §11 的边界澄清。

### D11 主题（色板 + 字号 + 线宽）进契约

（背景见 §1.4(2)）

**决定：`PageLayoutSpec` 增加 `theme` 字段，内容 = `loop/palette.py:283 summary()` 的原样产物**，由 Python 侧在出图纸时一起写进去。

- 不新写一份色板，也不让 JS 硬编码 —— 铁律 1（"颜色与字号只有一个来源"）继续成立。
- 放**契约里**而不是单独一个 `theme.json`：图纸要自包含（可存档、可 diff、可单文件传给插件），而且既然由 `palette.py` 单点生成，重复的风险很低。
- 同时补一步：`tests/test_step19_palette.py` 的 `RENDER_FILES` 只管 `.py`。P1 要加一条**守 JS 的测试**——扫描 `frontend/src/`，禁止出现十六进制色值和写死的 `Pt()`/字号字面量（白名单：`theme` 的读取层）。否则铁律 1 对 JS 就是空的。

### D12 历史的 11 份样本：宽松读、严格写

实测 11 份 `pagelayout.json`：**没有一份有 `version`**；其中 6 份（`auto_layout`、`_plain`、`multicol`、`_spread`、`page`、`paper`）连 `images` 键都没有（早于该特性）。老 `end_to_end/*/pagespec.json` 更没有 `content_bbox` / `frame_bbox`。

**决定：**

- `version` 是**可选**字段。缺失 = 老样本，按 `"0.x"` 宽松处理并给一条警告。
- `spec.schema.json` 对老样本只要求"能读"，对新样本严格。
- V5 因此改成：**P1 之后新生成的样本**做严格校验；老样本做宽松校验。
- 样本来源：挑 2–3 份最小的（`end_to_end/thermometer/pagespec.json` + `auto_layout/pagelayout.json` + 纯文本页）**复制进 `tests/fixtures/contract/`** 当夹具。`out/` 有 `.gitignore` 挡着不入库（`README.md:78` 也这么要求），但 `tests/fixtures/` 不受影响。
- **不接 CI**：`.github/` 下只有 `CODEOWNERS`，没有任何 workflow。V5 就是 `pytest` 的一条本地测试，不假装有门禁。

### D13 素材：脚本导出静态目录，缺图画占位不抛错

实测：`image_path` 是相对项目根的路径（如 `assets/placeholders/placeholder_todo.png`），`loop/render.py` 用项目根解析且**缺图直接抛 `ValueError`/`FileNotFoundError`**。

**决定：**

- 新增 `scripts/export_web_assets.py`：从 `db/assets.db` 导出（或直接镜像 `assets/`）到一个静态目录，附带 `manifest.json`（`asset_id` → 路径 + `tag` + `semantic`）。
- 图纸里的 `image_path` **保持相对项目根不变**；`mountPage({assets})` 的 `assets` 是那个静态目录的 URL 前缀，JS 拼 `assetsBase + '/' + image_path`。这样导出脚本不用改写图纸。
- **缺图不抛错**：画占位框并在图上标注（沿用项目一贯的"不静默兜底"文化 —— `loop/pipeline.py` 就是这么处理"无适用图形"的）。

### D14 加读回入口：契约要双向

实测：`PageLayoutSpec` / `PlacedCard` / `PlacedBlock` / `PlacedImage` **全都没有 `from_dict`**，只有 `PageSpec` 有。今天没有任何路径能把一份 `pagelayout.json` 读回引擎。

**决定：P1 就加** —— 新增 `loop/contract.py`（只做读写 + 版本检查 + schema 校验，不含任何排版规则），给四个 dataclass 补 `from_dict`。

理由：只有能读回，才叫契约而不是日志；成本很低（就是反序列化）；而且它是"编辑完再出 PPTX"这条路的前提。**做不做那条路是 D15/用户问题，但入口现在就该有。**

边界：`loop/contract.py` 不碰 `solve.py` / `layout.py` / `compose.py` 的任何规则，所以不违反 §11。

### D15 v1 的编辑边界 = 不引发重排的操作（用户 2026-11-12 已拍板）

**决定：v1 的编辑只做"不触发重排"的那些** —— 移动、缩放框、改文字（打 `stale`）、改颜色、改数据（回引擎）、换插图、调图层顺序。

**任何会引发重排的操作（增删元素、改栏数、换整版版式、改字号导致溢出）都不在前端做，一律回引擎。** 理由是反目标 A3：一旦前端能改版式，编排决策就分裂成两份，两边算出的版面永远对不上。

这条线的副产品：编辑后的图纸**永远是"引擎版面的一个变体"**，不是"另一个引擎的产物"。

### D16 字体：不做 webfont，靠系统字体

`loop/text_style.py:19` 的 `FONT_NAME = "微软雅黑"`。**微软雅黑是专有字体（微软 / 方正），不能打包成 webfont 发给浏览器。** 但这不构成阻塞：

- **D10 之后，浏览器不需要折行** —— 行是 Python 用 msyh 度量算好写进契约的，浏览器只是把给定的行画出来。所以字体差异**不会**导致断行不同。
- Windows 浏览器本来就能命中本机安装的微软雅黑（`font-family: "Microsoft YaHei", ...`）；macOS / Linux 会降级到系统无衬线字体，行不变，只是字宽略有出入。
- 因此 v1：`font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans SC", sans-serif`，**不打包字体**。
- 影响：V2 的像素对拍会因字体而异 —— 所以 V2 的阈值必须按**结构重合度**定，或者只在有 msyh 的机器上跑（见 §7）。

> 若将来要让"别人打开也一模一样"，再考虑打包一个开源中文字体（思源黑体 / Noto Sans SC，子集化后几百 KB）。**这是可逆的，v1 不做。**

---

## 5. 契约规格（v1）

### 5.1 两个层级

```
PageLayoutDoc                    ← 整版（pagelayout.json）
├── 画布 + theme + rows + cards + blocks + images
└── cards[].spec : PageSpec      ← 单卡（pagespec.json），内嵌，含 elements[]
```

### 5.2 整版层（`PageLayoutSpec`，`loop/layout.py:401-423`）

```jsonc
{
  "version": "1.0",              // v1 新增，可选；老样本没有
  "theme": { /* palette.summary() */ },   // v1 新增
  "width_in": 10.0, "height_in": 15.0,
  "margin_in": 0.4, "gutter_in": 0.3,
  "column_count": 1, "column_gutter_in": 0.2,
  "rows":   [ { "kind", "y_in", "h_in", "items", "cards", "blocks" } ],
  "cards":  [ { "name", "kind", "x_in", "y_in", "w_in", "h_in",
                "row", "column_span", "spec": { /* PageSpec */ } } ],
  "blocks": [ { "name", "style", "align", "text",
                "x_in", "y_in", "w_in", "h_in", "row", "column_span",
                "columns", "column_gutter_in",
                "lines": [...], "line_groups": [[...]] } ],
  "images": [ { "name", "path", "style", "align",
                "x_in", "y_in", "w_in", "h_in", "row", "column_span",
                "asset_id", "tag", "semantic",
                "rect": [dx, dy, w, h] } ]
}
```

`rect` 是盒内真实绘制矩形（永不变形、居中留白），渲染时用它，不要拉伸外盒。

### 5.3 单卡层（`PageSpec`，`loop/models.py:45-62`）

```jsonc
{
  "width_in": 10.0, "height_in": 6.0,
  "chart_key": "heat_ratio_top5",
  "chart_title": "取暖电器细分品类成交额环比增速TOP5",
  "scale": { "v_max": 11.0, "h_in": 3.0, "unit": "倍(超)",
             "factor": 0.2727..., "domain": [0.0, 11.0] },
  "elements": [ /* ElementSpec[] */ ],
  "semantic_tags": [...], "constraints": [...], "layout": {...},
  "content_bbox": [x, y, w, h],   // 数据图形原来占的那块
  "frame_bbox":   [x, y, w, h],   // 包框之后的框
  "chart": { "kind": "thermometer",          // v1 新增（语义层，可空）
             "series": [ {"label": "...", "value": 0.0} ],
             "encoding": {"x": "label", "y": "value"} }
}
```

`content_bbox` / `frame_bbox` 的用意（`loop/models.py:57-62`）：包框之后 `width_in`/`height_in` 指的是**框**，内容原来占的那块记在 `content_bbox`。两个都留着，渲染器才能决定按框缩放还是按内容缩放。

### 5.4 元素层（`ElementSpec`，`loop/models.py:21-42`）

```jsonc
{
  "id": "liquid_1", "type": "rect", "role": "liquid",
  "x_in": 0.89, "y_in": 2.3195, "w_in": 0.1, "h_in": 1.2455,
  "fill": "F1F1F1", "text": null,
  "binding": { "label": "...", "value": 0.0 },
  "geometry_expr": "h_in = scale.factor * binding.value; ...",  // 审计留痕，不解析
  "geometry": { /* 复合图元的求解结果 / align / lines */ },
  "image_path": null,
  "lines": ["折好的第一行", "折好的第二行"],   // v1 新增，见 D10
  "font_pt": 8.0                              // v1 新增，见 D10
}
```

**坐标相对卡片左上角**（约束 C2）。

### 5.5 图元词汇表（v1 硬契约，7 + 1 个）

| `type` | 出现过的 `role` | 画法 | `geometry` 关键字段 |
|---|---|---|---|
| `rect` | `frame` / `title_band` / `track` / `liquid` | `<rect>` | `border`（边框色） |
| `ellipse` | `bulb` | `<ellipse>` | — |
| `arc` | `sector` | `<path>` 弧 | `start_angle` / `end_angle` + 整圆包围盒 |
| `text` | `title` / `scale_note` / `label` / `value` / `legend` / `center` | `<text>`，按 `lines` 逐行 | `align` |
| `ticks` | `ticks` | 循环画 N 根短线 | `count`/`len`/`thick`/`pad_top`/`pad_bottom` |
| `outline` | `outline` | 温度计外轮廓路径 | `cx`/`cy`/`R`/`cap_r`/`cap_top`/`tube_bottom`/`neck_h` |
| `image` | 插图 | `<image>` | —（用 `image_path`） |
| `chart` | *(v1 新增)* | 出口自定 | `{kind, series, encoding}` |

`ticks` 和 `outline` 是**复合图元**：一个元素要画多个 SVG 节点。展开口径**不是** `geometry_expr`（那是审计留痕，见 §1.3 的更正），而是**复刻 `loop/thermo_shape.py` 的两个纯函数**：

- `tick_rects(el)`（`loop/thermo_shape.py:17`）
- `outline_polyline(el)`（`loop/thermo_shape.py:48`）

它们的输入只有元素自己的 `x_in` / `y_in` / `w_in` / `h_in` 加 `geometry` 里的参数 —— 所以 JS 侧照抄即可，**不需要表达式求值器**。

### 5.6 v1 新增字段（全部可空，放末尾，向后兼容）

| 位置 | 字段 | 含义 |
|---|---|---|
| `PageLayoutSpec` | `version: str \| None` | 契约版本，新样本 `"1.0"`；老样本没有这个键（D9/D12） |
| `PageLayoutSpec` | `theme: dict \| None` | 主题 = `loop/palette.py:283 summary()` 的原样产物（D11） |
| `PageSpec` | `chart: dict \| None` | 语义层：`{kind, series, encoding}`（D3） |
| `ElementSpec` | `lines: list \| None` | 卡片内文本的折行结果（D10） |
| `ElementSpec` | `font_pt: float \| None` | 该文本元素的实际字号（D10） |
| `ElementSpec` | `editable: bool \| None` | 缺省按 `type` 推（`ticks`/`outline` 缺省不可单独选中，随宿主） |

### 5.7 schema 校验

`spec.schema.json` 用 JSON Schema draft 2020-12。两边都校验：

- Python 侧：`tests/` 加测试，用 `tests/fixtures/contract/` 里的夹具（D12）。
- JS 侧：库启动时校验，失败给出**元素级**错误（哪张卡、哪个元素、哪个字段），不是一句"格式错误"。

---

## 6. JS 库的结构

```
frontend/
  package.json
  README.md                    已有三条铁律，要保留并补 JS 侧的落地说明
  src/
    index.js                   公开 API
    theme.js                   读契约里的 theme，唯一允许出现色值/字号的读取层
    units.js                   inch ↔ px，scale
    doc.js                     图纸读取 / 归一化 / 版本检查 / schema 校验
    shapes/
      ticks.js                 ← 照抄 loop/thermo_shape.py::tick_rects
      outline.js               ← 照抄 loop/thermo_shape.py::outline_polyline
    render/
      stage.js                 画布 + 行 + 卡片容器（嵌套 <g transform>）
      primitives.js            rect / ellipse / arc / text / ticks / outline / image
      chart.js                 type:"chart" 分发（v1 报未实现或退化为占位）
      echarts.js               （v2）ECharts 适配器
    edit/
      select.js                命中测试 / 选中 / 多选
      drag.js                  拖动 + 吸附
      text.js                  就地改字（打 stale）
      inspector.js             属性面板
      history.js               撤销 / 重做
    io/
      toSpec.js                编辑结果 → 新图纸 JSON
      export.js                SVG / PNG 导出
    styles.css
  demo/                        一页 demo + 样本 pagelayout.json
  test/
```

公开 API（草案）：

```js
import { mountPage } from '@stecven/news-dataviz';

const page = mountPage('#stage', spec, {
  scale: 96,                                  // px per inch
  editable: true,
  assets: '/assets',                          // image_path 的 URL 前缀
  relayout: async (text, style) => lines,     // 可选，见 D6
});

page.on('change', (nextSpec) => { /* 回写图纸 */ });
page.exportSVG();
```

---

## 7. 验收与对拍

对拍资产**已经存在**，不用新造：

- `out/demo/auto_layout/`：`pagelayout.json` + `preview.png` + `page.pptx` + `flow.json` + `_cards/`
- `out/demo/end_to_end/{thermometer,semicircle,fallback,fallback_h3,h4,h6}/`：单卡 `pagespec.json` + `preview.png` + `selection.json`
- `out/demo/auto_layout/_plain/`：纯文本页

| # | 检查 | 通过标准 |
|---|---|---|
| V1 | 结构对拍 | JS 读同一份 `pagelayout.json`，输出的 SVG 元素数 + 每个元素的 bbox（换算回 inch）与图纸逐个比对，容差 `1e-6` |
| V2 | 像素对拍 | JS 渲染光栅化 → 与 `preview.png` 比对。字体必然有差异（D16），所以按**结构重合度**定阈值、不按逐像素；或者只在装了微软雅黑的机器上跑。阈值留给 builder |
| V3 | 编辑闭环 | 拖动 / 改字 → 导出新图纸 → 重新 mount → 位置一致（纯 JS 侧，不需要 Python） |
| V4 | Python 回归 | `pytest tests/` 676 条全绿；新增字段不破坏老 `pagespec.json` 的 `from_dict` |
| V5 | schema 校验 | **P1 之后新生成的**样本严格过 `spec.schema.json`；历史 11 份只要求"能读 + 给警告"（实测全部没有 `version`，6 份连 `images` 键都没有）。夹具在 `tests/fixtures/contract/`，`out/` 不入库。**不接 CI**（`.github/` 没有 workflow） |
| V6 | 主题单一来源 | `tests/` 扫 `frontend/src/`，除 `theme.js` 外禁止出现十六进制色值与写死的字号（D11） |

---

## 8. 留给 builder 的决定

这些是"换个 builder 也能自己定、不影响造出什么东西"的小决策，标记为**我的倾向**，builder 可以推翻：

- **构建工具**：Vite（因为需要一个 demo 页做 V2 对拍）。
- **打包产物**：只出 ESM。现代浏览器直接用，不欠 UMD 的债。
- **是否上 TypeScript**：倾向**先不上**，图纸侧靠 JSON Schema + 运行时校验拿类型安全（和仓库其他部分的门槛一致）。可逆。
- **命中测试**：优先用 SVG 自己的 hit-testing（`elementFromPoint` / 事件冒泡），不到万不得已不算 bbox。
- **撤销粒度**：按"一次用户操作 = 一步"，拖动过程中的中间态不记录。
- **像素对拍阈值**：先按 V1 结构对拍卡死，V2 只做"人眼看不出结构错位"的粗阈值。
- **`ticks` / `outline` 的 JS 实现**：直接照抄 `loop/thermo_shape.py`，两边加一条对拍测试（同一元素 → 同样的点集），不做数学抽象。

---

## 9. 分期

| 期 | 内容 | 依赖 |
|---|---|---|
| **P1** | 契约冻结：`spec.schema.json` + `version` + `theme` + 卡片 `lines`/`font_pt` + `loop/contract.py` 读回入口 + 夹具 + V4/V5/V6 | 无 |
| **P2** | 只读渲染：7 个原语 + `ticks`/`outline` 照抄 + 整版骨架 + `demo/` 页 + V1/V2 | P1 |
| **P3** | 编辑（D15 边界内）：选中 / 拖动 / 改字 / 属性面板 / 撤销 + 导出回图纸 + V3 | P2 |
| **P4** | CLI + MCP server 外壳 | P2（P3 不是必须） |
| **P5** | 素材导出脚本 `scripts/export_web_assets.py` + 插图渲染（D13） | P2，可与 P3 并行 |
| **P6** | *(v2)* `type:"chart"` + ECharts 适配器 + 扩图型 | P3 |
| **P7** | *(v2)* draw.io 出口 | P3 |

P1 → P2 → P3 是主干。P4 / P5 可以和 P3 并行。

---

## 10. 用户已拍板的边界（2026-11-12）

三个原本开着的问题，用户已经选定，写死在下面：

1. **编辑边界 = 不触发重排为止**（对应 D15）。能移动、改字、改样式、改数据、换插图；**增删元素、改栏数、换整版版式一律回引擎**。前端不复制 `compose.py` 的编排规则。
2. **v1 不做回流**。出口到"网页上画出来、改完能导出图纸 JSON"为止。D14 的读回入口照建（成本低、契约本来就该双向），但**不接**"编辑后 → 引擎重排 → 新 PPTX"这条路。
3. **v1 不补插图素材**。先把渲染与编辑这条链跑通；素材库的问题（现在是 1 张整版大图 + 7 个淡化图标，没有语义标注的插图集）留到 v2。对拍样本本来就有插图槽位，不阻塞。

---

## 11. 明确不动的东西（边界澄清）

写下来是为了让 builder 知道边界：

- `ingest/` 爬虫、`scripts/fetch_assets.py`、`scripts/seed_chart_data.py`
- `db/assets.db` 的表结构
- `loop/` 里任何**求解 / 选型 / 排版规则**：`solve.py`、`selector.py`、`scaffold.py`、`layout.py` 的编排算法、`compose.py` 的编排规则 —— v1 只**读**它们的输出，不改它们算什么
- `tests/` 里现有 676 条断言
- PPTX 出口（继续存在，继续能用）

**边界澄清（builder check 提出来后补的）**：D10 / D11 / D14 确实要动 `loop/`，但它们**不是"改规则"，是"把已经算出来的东西写进产物、并把产物读回来"**：

- D10 把 `preview.py::_draw_text` 里已经在用的折行逻辑前移到规格生成阶段 —— 规则没变，只是结果多写了一份。
- D11 调用现成的 `palette.summary()` —— 没有任何新规则。
- D14 新增 `loop/contract.py` 只做读写 + 校验。

这三件事都不得改变任何一张已存在样本的几何数字（V1/V4 会守住）。

---

## 12. builder check 回执

一轮独立复核（fresh subagent，读了 `loop/` 源码与 11 份真实样本）的结论已并入本文。它改掉的三处：

1. **§1.3 原来写"每个元素都带 `geometry_expr`"，是错的。** 实测 54 个卡片元素里 33 个为 `null`；非空的那 21 条**不可执行**（含 `{i-1}` 下标、引用 JSON 里不存在的 `x_track`/`w_track`/`H_track`/`bulb_y`）。`loop/models.py:33` 的原文写明它是「E.1 ④ **审计留痕**」。复合图元的真实口径是 `loop/thermo_shape.py` 的 `tick_rects` / `outline_polyline`。已改 §1.3 与 §5.5。
2. **§5.5 原来写"照着公式展开"，字面照做会卡死**（表达式没法执行、参数不存在）。已改成"复刻两个纯函数"。
3. **§7 原来要求"所有历史样本通过 schema"，现在就是全红** —— 11 份里没有一份有 `version`。已改成 D12 的宽松读 / 严格写。

以及它复核通过、不必再问的部分：7 种图元 × 14 个 `(type, role)` 组合与文档一致；所有卡片 `spec.width_in/height_in` 与卡片框完全相等、无负坐标/溢出（C2 成立）；`_render_order`（先非文本后文本）与 §5.5 的绘制顺序假设一致；`loop/preview.py` 对 `arc` 的整圆包围盒画法有明确口径注释，可自行决定。
