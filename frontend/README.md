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

```js
import { mountPage } from './src/index.js';
const page = mountPage('#stage', doc, { scale: 50 });
page.on('warning', (msg) => console.warn(msg));  // 缺图、缺 spec 之类的降级
```

`opts` 里 `scale`（默认 96）**只管 `<svg>` 的展示尺寸**，不参与任何像素换算：
内部坐标永远是 `PX_PER_IN = 100` 的 1:1 口径，`viewBox` 写内部尺寸、`width` /
`height` 写展示尺寸。`assetsBase` 与 `resolveAsset` 管图片地址解析。

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

## 已知限制（别当成 bug 反复修）

- 半圆图分项 > 5 判「不适用」，走占位图兜底；「全相等」档缺专门素材。
- 图文混排只做上下型 + 栏内均分，没有两侧文字环绕；段落不回填上一行空栏。
- 球泡与管身的接合用折线近似，400% 放大可见轻微折角。
