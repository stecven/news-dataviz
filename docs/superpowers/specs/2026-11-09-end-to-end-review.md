# 端到端演示复盘（用户 m04383）

**本轮只跑演示、出图、写分析，未改任何生产代码。** 三组数据分别命中三个分支，全部跑通。

## 0. 产出与元数据

| 组 | 数据来源 | 语义 | 选型 | 元素数 | 形状数 | 素材 | 预览 |
|---|---|---|---|---|---|---|---|
| thermometer | `heat_ratio_top5`（10/3/3/3/3，单位「倍(超)」） | 比较大小 | `thermometer` | 37（text 12 / rect 10 / outline 5 / ellipse 5 / ticks 5） | 37 | — | `out/demo/end_to_end/thermometer/preview.png` |
| semicircle | `heat_age`（0.08/0.32/0.32/0.17/0.11，Σ=1.0） | 占比构成 | `semicircle` | 13（text 8 / arc 5） | 13 | — | `out/demo/end_to_end/semicircle/preview.png` |
| fallback | 构造 10/3/2/2/2/1（6 项占比） | 占比构成 | `None`（`no_applicable`） | 1（image 1） | 1 | `assets/placeholders/placeholder_todo.png`（id 23） | `out/demo/end_to_end/fallback/preview.png` |

每组目录下均有 `pagespec.json` / `preview.png` / `loop1.pptx` / `selection.json`；汇总在 `out/demo/end_to_end/summary.json`，三张并排总览在 `out/demo/end_to_end/_sheet_all.png`。

三组的关键几何（画布统一 10×6 in）：

| 组 | 元素 bbox 覆盖宽度 | 覆盖高度 | 底部空白 | 墨迹占比（非白像素 / 画布） |
|---|---|---|---|---|
| thermometer | 99% | 87% | 0.25 in | 6.6% |
| semicircle | 90% | 88% | 0.25 in | 12.2% |
| fallback | 22% | 37% | 0.80 in | 0.5% |

---

## 1. 三种产出放在一起像不像同一份报纸里的东西？

**不像。** 三张图各自单独看都成立，并排放就散。具体差在四处，都是可验证的：

### 1.1 配色族完全不交叉

| 组 | 用到的颜色 |
|---|---|
| thermometer | `E8A08C`（暖珊瑚液柱）、`FFFFFF`（白管）、`C9C9C9`（灰刻度 / 外圈） |
| semicircle | `C01F2A`、`E07B39`、`F2C14E`、`7A9E7E`、`6C7A89`（五色撞色板） |
| fallback | 中性灰（`GREY_DARK/MID/LIGHT` 三阶） |

三组没有任何一个颜色是共用的。温度计走单色暖调，半圆走五色分类色板，占位图走中性灰——这是三套独立的配色语言。原版《经济日报》整版之所以像一份东西，靠的是贯穿全版的暖秋色（枫叶红橙）+ 米白底。**当前没有任何机制约束「同一版里不同图必须共享色板」**，模板各自带 `color_*` 参数（`_THERMO_PARAMS` 的 `color_liquid`、`_SEMI_PARAMS` 的 `color_sector_1..5`），彼此不知道对方存在。

### 1.2 字号全部一样大，标题不突出

三个渲染器的文字尺寸都是硬编码常量，跟元素角色无关：

- `loop/render.py:96` `run.font.size = Pt(10)`
- `loop/render_arc.py:73` `run.font.size = Pt(10)`
- `loop/render_thermo.py:117` `run.font.size = Pt(10)`
- `loop/preview.py:41` `font = _font(14)`（预览固定 14 px）

所以 `title`（`h_in=0.50`）和 `legend`（`h_in=0.30`）、`value`（`h_in=0.18`）用的是同一个字号。从预览能直接看到：「取暖电器细分品类成交额环比增速TOP5」与「10倍」视觉权重相同。这是**排版层缺失的最直接证据**——图形层已经知道谁是标题（role 分了类），渲染层却没把语义翻译成字号。

### 1.3 空白利用率差 24 倍，没有「图框」概念

墨迹占比 0.5%（占位图）到 12.2%（半圆），差 24 倍。温度计铺满 99% 宽度，半圆实际图形只占中部（扇区 x 2.95..7.05，左右各留 ~2.5 in，左侧塞图例、右侧纯空），占位图只占画布 22%×37%。

每张图都按「画布多大我就尽量撑多大」的规则自己决定占多少。拼版时必然出现一张挤满、一张空荡。**没有「每个图分配一个格子、图形在自己格子里居中」的概念**，只有「画布」没有「版面」。

### 1.4 占位图连标题都没有

`thermometer` / `semicircle` 的 PageSpec 里都有 `title` 与 `scale_note` 两个文本元素；`fallback` 分支的 PageSpec **一个文本元素都没有**，只有那个 image（`PLACEHOLDER_W_IN/H_IN=2.2`、`PLACEHOLDER_TOP_IN=3.0`）。

`_build_fallback_spec()` 把 `chart_title` 传进了 `PageSpec.chart_title` 字段，但没有生成 `title` 元素——所以数据里知道标题是什么，画面上什么都没有。这是 `no_applicable` 分支刻意简化（不写 constraints、不走 validate_spec）带来的副作用：它绕过了 `_place_header()` 这套共用 helper，也顺带绕过了标题。

---

## 2. 占位图位置（3.9, 3.0, 2.2, 2.2）合不合理？换画布会失效吗？

### 2.1 6 in 画布下：数值上不越界，语义上缺东西

- 占位图底 = 3.00 + 2.20 = **5.20 in**，画布 6.0 in → 底部留 0.80 in，**不越界**。
- 与另两组对比：温度计 / 半圆的元素最低底都是 5.75 in（底部空白 0.25 in）。占位图底部只到 5.20，比别人浅 0.55 in——位置算「中部偏下」，没有对齐其他图形的基线。
- 水平方向 `x=3.9`、`w=2.2` → 中心 5.0，正好画布中线，水平居中是成立的。
- 但它上方/下方都没有任何文字：没有标题、没有「此处缺一张图」的说明。真实版面里读者看到一块虚线框会不知道它是什么。位置本身不是问题，**缺的是与文本的关系**。

### 2.2 换画布 H=4.0：**曾溢出 1.20 in（静默失败），已在 m04449 修复**

```
[fallback H=4] elem y_in=3.00 h_in=2.20 bottom=5.20  canvas_h=4.0  ok=False
[fallback H=4] bottom margin = -1.20 in
```

具体表现两侧都坏：

| 后端 | 现象 |
|---|---|
| PNG 预览（`preview.py`） | 画布裁到 400 px 高，占位图盒 (390..610, 300..520) 只有上半截可见。占位图盒内非白像素从完整状态的 3338 降到 **1164**，约 65% 被裁掉。 |
| PPTX（`render.py`） | `read_shapes` 回读 `top=3.000 height=2.200 → bottom=5.200 in`，幻灯片只有 4 in 高。形状坐标原样写进 pptx，**越出幻灯片边界**（PowerPoint 打开会在画布外，导出 PDF 时被裁）。 |

根因有两条，都可定位到具体行：

1. `loop/pipeline.py` 的 `PLACEHOLDER_TOP_IN = 3.0` / `PLACEHOLDER_W_IN` / `PLACEHOLDER_H_IN` 是**绝对常量**，不随 `height_in` 变化——`_placeholder_element(asset, width_in)` 甚至只接收 `width_in` 一个参数，高度方向的常量完全没被使用。
2. `_build_fallback_spec()` **刻意不走 `validate_spec`**（因为它没有模板、没有 constraints）。所以连 C1 越界检查这一层都会被跳过——温度计/半圆在 H=4 时会自动重排（实测 `H_track` 3.0→1.0、`bulb y` 5.02→3.02、最低底 3.75，全在界内），占位图则完全没有这个能力，也**没有任何地方会发现它越界**。

换句话说：**占位图分支是全流水线唯一一条既不受约束求解、也不受边界校验保护的路径。** 这在 6×10 的写死画布下不出事，一旦换画布就是静默的错误产物（`status` 仍然是 `no_applicable`，调用方不会察觉）。

### 2.3 补丁：选择「自适应缩放」而非「直接报错」（用户 m04449）

| 项 | 内容 |
|---|---|
| 改动位置 | 只改 `loop/pipeline.py`（`_is_inside` / `_fit_placeholder` / `_build_fallback_spec` / `run_selected`），**未碰** selector / solve / render / preview / models |
| 策略 | **a) 自适应**：越界时等比缩放至含 `FIT_MARGIN_IN=0.5` in 边距的画布内并居中；不越界则**原样不动** |
| 留痕 | `layout["placeholder_fit"] = {"adjusted", "before", "after"}` 落进 pagespec.json，返回值同名字段，`message` 追加「已等比缩进并居中为 …」 |
| 画布过小 | `w < 2×0.5` 或 `h < 2×0.5` 时抛 `ValueError("canvas … cannot hold a placeholder …")`，不假装成功 |

**选 a 而不是 b 的理由（三条）**：

1. **这条分支存在的意义就是「无适用时也要有可见产物」**。选 b 会让 no_applicable 在短画布下退化成空手交出，等于撤销 m04220 的目的。
2. **缩放占位图不造成「数值失真」**。同一个项目里温度计/半圆禁止缩放，是因为它们的尺寸编码了数值（C1/C2/C3 约束）。占位图没有 binding、没有约束，缩放它不破坏任何数据语义——这条原则在两类图元上是相反的，不能一刀切。
3. **调整不是静默的**。`placeholder_fit.adjusted=True` + `before/after` + message 提示，调用方与人都能看到「这张图被改过」。若是无声缩放，那就和原来的静默溢出一样糟。

**为什么不修 `PLACEHOLDER_TOP_IN` 这个绝对常量本身**：那属于版面布局（把绝对坐标换成格子坐标），是下一层的事，本轮范围锁死明确排除。

### 2.4 三档实测（补丁后）

| 画布 | 元素盒 (x, y, w, h) | 底 | 是否在界内 | `adjusted` | preview 非白像素 |
|---|---|---|---|---|---|
| 10×6.0 | (3.9, 3.0, 2.2, 2.2) | 5.20 | ✅ | `False` | 3338（与补丁前 sha 完全一致） |
| 10×4.0 | (3.9, 0.9, 2.2, 2.2) | 3.10 | ✅ | `True`（只改 y） | **3338（不再被裁，补丁前 1164）** |
| 10×3.0 | (4.0, 0.5, 2.0, 2.0) | 2.50 | ✅ | `True`（等比缩到 2.0） | 2684 |

PPTX 侧同样核对过：H=4 时 `read_shapes` 回读 top=0.900 height=2.200 → bottom=3.100 in ≤ 4.0，形状不再跑到幻灯片外。

**H=6 的回归是逐字节的**：`out/demo/end_to_end/fallback/preview.png` 与 `fallback_h6/preview.png` 的 sha256 都是 `f7b3545e…c45c`，与补丁前那张完全相同。

---

## 3. 整版排版的核心问题：图形之间的组合排布，还是图形与文本/插图的混排？

**是后者——图形与文本、插图的混排。** 依据是「图形之间的组合与排布」这一层，本轮已经能看到它基本被求解器解决了；而文本/插图层几乎完全空白。

### 3.1 图形内部的组合排布：已基本解决

三组里凡是涉及「图形之间怎么排」的，都是求解器算出来的、且换画布能自适应：

| 约束 | 效果 | 证据 |
|---|---|---|
| C6 等距 | 5 支温度计水平等距 `d=2.18` | 预览里 5 支管口右缘对齐、间距一致 |
| C5 居中 | 液柱/球泡/标签/真值全部对齐管身中心 | 细杆液柱与管身同轴 |
| C4 竖直相邻 | 标签→管身→球泡→真值严格堆叠 | `track y=2.02`、`bulb y=5.02`、`value y=5.57` |
| C7 半径适配 | 半圆 R 随画布算 | H=4 时 R 2.05→1.05 |
| C8 扇角递推 | Σθ=180° 闭合 | 半圆 5 扇区端点 180→360 |

H=4 重排实测：`track_1 y=2.020 h=1.000`、`bulb y=3.020`、`value bottom=3.750`，全部在 4 in 内。**「图形自己该长什么样、内部谁挨着谁」这件事已经有确定答案了。**

### 3.2 文本/插图层：几乎为零

对照「像不像报纸」这一问，缺的完全是图外的东西：

1. **没有图框与标题带**。三组都没有副标题、没有来源行、没有单位说明带。`scale_note` 是本项目自造的调试性文字（「量程上限 V_max=11倍(超)｜液柱高度 = 3.0 × 数值 / V_max」），把实现细节写给读者看——原版报纸那里应该是一句人话（如「环比增速」）。
2. **没有字号层级**。见 §1.2，标题/图例/数值全 Pt(10)。
3. **没有图文关系**。占位图单独一块虚线，没有配文；半圆左侧图例带是 `w_legend = max(0.5, x_pie - m)` 算出来的剩余宽度，不是「图例应该排在哪」的设计决定。
4. **没有跨栏与插图穿插**。原版《经济日报》整版的辨识度来自那张贯穿三栏的枫叶 + 家电实物插画，三块图表是压在插画留白上的。本轮三张图都是「一张图占满一个画布」，插画与图表的位置关系根本没有被建模。
5. **没有统一色板与留白规则**。见 §1.1 / §1.3。

### 3.3 因此下一步该做什么

如果继续打磨单个图形（把球泡再放大、给半圆加标签避让 C9），边际收益很低——§3.1 那五条约束已经保证了图形本身不会丑。真正卡住「像不像报纸」的是：

- **版面格子（grid）**：把画布切成区域，每个图分配一个格子并在格内居中，而不是每个图都自己撑满画布；
- **文本角色与字号表**：`title` / `subtitle` / `legend` / `source` / `note` 各自的字号与行距，由渲染层从 role 读取，而不是硬编码 `Pt(10)`；
- **统一色板约束**：一版一个 palette，模板的 `color_*` 从 palette 派生而不是各自写死；
- **插图位**：插画与图表在同一版面上的位置关系（谁压谁、留白多少）；
- **占位图也要走版式**：`PLACEHOLDER_TOP_IN` 这种绝对常量必须变成「由格子算出来的位置」，否则换画布就溢出（§2.2 已经实证）。

---

## 4. 验收自查

| 闸口 | 结果 |
|---|---|
| 三组分支全部跑通，每组有 `pagespec.json` + `preview.png` | ✅ 三组齐全，均含 pptx 与 selection.json |
| 占位图 fallback 确实画出图，不是空白 | ✅ 预览里占位图盒内非白 3338/48400 像素，`read_shapes` 回读 `placeholder_1 = PICTURE` |
| 元素数符合预期 | ✅ 温度计 37、半圆 13、占位图 1 |
| 分析文档回答三组问题，有实际观察支撑 | ✅ 全部结论附实测数字与文件行号 |
| 全量测试仍全绿，未改既有代码 | ✅ 412 tests OK；改动仅新增本文档 |
| 发现的问题如实报出，未自行修复 | ✅ §2.2 占位图 H=4 溢出已由 m04449 修复（§2.3/§2.4）；§1.2 字号硬编码、§1.1 色板不统一仍未修 |

## 5. 统一色板 + 文本角色字号表（用户 m04549 落地记录）

§1.1 与 §1.2 的两条症状（配色零交集、字号全部一等大）本轮已修，改法是把
颜色与字号从「各渲染器各写一份」收成单一来源。

### 5.1 色板 `loop/palette.py`

| 角色 | 色值 | 用途 |
|---|---|---|
| `primary` | `E8A08C` | 暖珊瑚：温度计液柱/球泡、半圆第 1 扇区（**锚定报纸原版，不改**） |
| `secondary` | `C2512F` | 半圆第 2 扇区（原 `C01F2A`，压暗一档以进入同一暖色族） |
| `accent_1` | `E8B85C` | 半圆第 3 扇区 |
| `accent_2` | `7A9E7E` | 半圆第 4 扇区 |
| `accent_3` | `6C7A89` | 半圆第 5 扇区（用户 m04607 裁定补的第五色） |
| `neutral_dark` | `222222` | 所有正文文本 |
| `neutral_strong` | `7A8088` | 占位图主笔 |
| `neutral_mid` | `A8AEB6` | 占位图中间调、PNG 预览描边 |
| `neutral_light` | `D6DADF` | 占位图淡色/虚框 |
| `neutral_hairline` | `C9C9C9` | 温度计划度线与外圈发丝线 |
| `surface` | `FFFFFF` | 画布底、管身底 |

为什么比用户原定的 6 个角色多 5 个：文本深色、发丝线、占位图三档灰是**四种
不同用法**，压成同一个 `neutral_light` 会让刻度线和虚框一样淡、正文和标签一样
灰。`SECTOR_ROLES` 固定顺序 `primary → secondary → accent_1 → accent_2 → accent_3`，
不随机、不轮转，所以同一份数据两次出图配色必然相同。

### 5.2 字号表（单一来源，`loop/palette.py`）

| 设计角色 | pt | 流水线里的 role |
|---|---|---|
| `title` | 20 | `title` |
| `subtitle` | 14 | `center`（半圆中心占比） |
| `body` | 11 | `value`（温度计数值 118%/10倍） |
| `label` | 9 | `label`、`legend` |
| `note` | 8 | `scale_note`（量程说明） |

改前全流水线只有 `Pt(10)` 一个值（PPTX 端三处硬编码 + 预览端 `_font(14)`），
标题和「10倍」等权；现在 title:value = 20:11 ≈ 1.8 倍，title:note = 2.5 倍。

### 5.3 改了哪些文件

| 文件 | 改动 |
|---|---|
| `loop/palette.py` | **新增**。色板 + 字号表 + 别名 + `delta_e`/`contrast_ratio`/`check_separation` 自检 |
| `loop/text_style.py` | **新增**。`apply_text_style(shp, el)` / `apply_fill(shp, el)`，让三个平级适配器共用一套套样式代码，不互相 import |
| `loop/render.py` | 删 `_FONT_NAME`/`_TEXT_COLOR`/`Pt(10)`，改走 `apply_fill` + `apply_text_style` |
| `loop/render_arc.py` | 同上 |
| `loop/render_thermo.py` | 同上；皮肤兜底色 `el.fill or palette.color("ticks")` |
| `loop/preview.py` | 背景/描边/文本色全部取色板；`_draw_text` 改为按 `role` 取字号与行高，并做 **pt → px 换算**（`PX_PER_IN/72`） |
| `loop/templates.py` | 模板默认色改为引用色板常量；`text_size` 默认 = `FONT_SIZES["label"]` |
| `loop/solve.py` | 仅第 289 行扇区兜底色改为 `PALETTE["primary"]`，**求解逻辑零改动** |
| `scripts/make_placeholder.py` | 三档灰改为从色板派生（派生后图片字节逐位不变） |

未改：`loop/selector.py`、`loop/models.py`、`loop/pipeline.py`、`db/assets.db`
（sha 前后一致，见 §5.6）。

### 5.4 两个实现期发现的坑

1. **预览层 pt/px 单位混用**：字号表给的是 pt，预览画布按 100 px/in 出图。
   直接把 pt 当像素用，8 pt 的注释会被画成 8 像素（字形高度不到 6 像素），
   `test_scale_note_is_visible_in_preview` 立刻红（深色像素 0 > 50 失败）。
   加 `_PX_PER_PT = PX_PER_IN / 72.0` 后恢复。
2. **`font_size()` 静默降级**：设计角色名（`subtitle`/`body`）不在
   `ROLE_TO_FONT` 里，只查映射会一路降级到 `DEFAULT_FONT_ROLE = "note"`，
   14 pt 副标题被画成 8 pt（缩水 43%）且不报错。改为「映射优先、命中字号表
   则直查」。补了回归测试 `test_design_role_names_resolve_to_their_own_size`。

### 5.5 三组回归实测

| 组 | 元素/形状 | 主色（改前 → 改后） | 字号层级 |
|---|---|---|---|
| thermometer | 37 / 37 | `#E8A08C`+`#C9C9C9`+`#888888` → `#E8A08C`+`#C9C9C9`+`#A8AEB6`（描边统一到色板） | 20 / 11 / 9 / 8 |
| semicircle | 13 / 13 | `#E07B39 #F2C14E #7A9E7E #6C7A89 #C01F2A` → `#E8A08C #C2512F #E8B85C #7A9E7E #6C7A89`（第 1 扇区并入主色，其余进同一暖色族） | 20 / 14 / 9 / 8 |
| fallback | 1 / 1 | 三档灰本来就是色板值，逐字节不变 | 无文本 |

三组共有色从 `['#FFFFFF']` 变为 `['#FFFFFF', '#A8AEB6']`。

对比度自检（写在 `palette.check_separation()` 里，测试直接断言 `== []`）：
相邻扇区 ΔE 依次 36 / 47 / 50 / 31 / 46（阈值 20）；正文 `222222` 对
`surface` 15.91:1、对 `neutral_light` 11.33:1（阈值 4.5）。

### 5.6 验收

- `Ran 453 tests OK`（含新增 `tests/test_step19_palette.py` 24 用例）；
- 渲染层四个文件 grep 不到任何十六进制色值字面量、`Pt(10)`、`#888888`、`#222222`、`"white"`；
- `loop/selector.py` `9e7de324728c`、`loop/models.py` `9231f7b9ea8a`、
  `loop/pipeline.py` `7380d9b1c424`、`db/assets.db` `45e875a2aff5` 与改动前一致；
- 产物：`out/demo/palette/{thermometer,semicircle,fallback}/`，总览 `out/demo/palette/_sheet_all.png`。

### 5.7 本轮明确未做

图框、版面格子、字号派生自版面宽度的自动缩放、图标插图位、
`scale_note` 的文案改写（它现在还是「量程上限 V_max=11倍(超)｜液柱高度 = …」
这种实现细节，给人看应该改成「1 格 ≈ 1 倍」之类的读者语言）。

## 6. 图框 + 标题带 + 读者文案（用户 m04818 落地记录）

§1.3 与 §1.4 指出的问题（没有图框、没有标题带、`scale_note` 写给开发者看）在本轮
处理。范围按用户要求锁死在**单张图表的卡片化**：不做整版排版、不做多图组合、
不做版面格子。

### 6.1 规格（三组统一）

| 项 | 值 | 常量 |
|---|---|---|
| 内容到框线的内边距 | 0.30 in | `loop/frame.py::PAD_IN` |
| 标题带高度 | 0.50 in | `BAND_H_IN` |
| 标题带与说明的间距 | 0.15 in | `BAND_GAP_IN` |
| 说明行高 | 0.30 in | `NOTE_H_IN` |
| 说明与图形区的间距 | 0.20 in | `NOTE_GAP_IN` |
| 标题/说明相对带边的内缩 | 0.15 in | `TEXT_INSET_IN` |
| 框线颜色 | `neutral_mid` `A8AEB6`，1 pt | `BORDER_ROLE` + `text_style.BORDER_PT` |
| 标题带填充 | `neutral_light` `D6DADF` | `BAND_ROLE` |
| 标题字号 / 对齐 | 20 pt / 左对齐 | `palette.FONT_SIZES["title"]` |

三项用户点名的「三张图要一致」都落在这张表上：内边距、标题字号、标题位置
（`title.x_in = PAD_IN + TEXT_INSET_IN = 0.45`，`title.y_in = PAD_IN = 0.30`）。

### 6.2 为什么画布会变大（用户 m04888 的裁定 A）

温度计 5 个类别标签把内容撑到 x 0.040..9.960（宽 9.92 in），原画布只有 10 in。
任何 ≥0.05 in 的内边距都会把框顶出画布，而收窄标签会动图形几何、打破
`x_label = x_track − 0.46` 一组手算断言。用户裁定**框 = 内容 bbox + 0.3，
画布随框长大，图形一像素不动**，并要求 PageSpec 同时记录两个尺寸：

- `content_bbox`：[x, y, w, h]，内容外接盒（卡片坐标）；
- `frame_bbox`：[0, 0, W, H]，框的外接盒；
- `width_in / height_in` 取**框**尺寸，原来的画布尺寸记在
  `layout["frame"]["canvas"]`，内容原点偏移记在 `layout["frame"]["origin"]`。

这样版式引擎（未来整版）拿到两个尺寸，才能决定按框缩放还是按内容缩放。

### 6.3 三组实测（`out/demo/frame/`）

| 组 | 状态 | 画布 | content_bbox | 元素数 | 形状回读 |
|---|---|---|---|---|---|
| thermometer | rendered | 10.52 × 5.85 | `[0.3, 1.45, 9.92, 4.1]` | 39 | 39 |
| semicircle | rendered | 7.15 × 5.85 | `[0.3, 1.45, 6.55, 4.1]` | 15 | 15 |
| fallback | no_applicable | 2.80 × 3.95 | `[0.3, 1.45, 2.2, 2.2]` | 5 | 5 |

元素数变化 = 原内容 + `frame` + `title_band`（`title` / `scale_note` 是**替换**不是新增）：
37→39、13→15、1→5。`read_shapes()` 回读得到 `frame`（AUTO_SHAPE）、
`title_band`（AUTO_SHAPE）与原有全部图元，三组 `len(shapes) == len(elements)`。

### 6.4 说明文案改成读者语言

| 组 | 旧 | 新 |
|---|---|---|
| 温度计 | `量程上限 V_max=130%｜液柱高度 = ...` | `液柱越长，涨幅越高；满格约 11倍，球泡处为零点。` |
| 半圆 | `扇角总和 Σθ=180°｜θ_i = Σθ × 数值 / Σv ...` | `扇面越大，占比越高；圆心那个百分比，就是它所在扇区自己的占比。` |
| 占位图 | （原无说明） | `示意图：这里暂时缺一张图，数据补齐后会替换成对应图表。` |

回读三组 PPTX 文本，`V_max` / `液柱高度 =` / `Σθ=` / `arc_total` / `× 数值 /`
命中数均为 **0**。

### 6.5 改动文件

| 文件 | 改动 |
|---|---|
| `loop/frame.py` | **新增**。`content_bbox` / `wrap` / `unwrap` / `validate_frame` 与上述常量 |
| `loop/models.py` | `PageSpec` 末尾加 `content_bbox` / `frame_bbox`（缺省 None，老 JSON 仍可读） |
| `loop/text_style.py` | 加 `BORDER_PT`；按 `geometry["align"]` 左/居中；按 `geometry["border"]` 描边 |
| `loop/preview.py` | 支持左对齐、`frame` / `title_band` 两个绘制分支 |
| `loop/render.py` | 无需新增分支——`frame` 是普通 rect，走既有 `apply_fill` 即可描边 |
| `loop/solve.py` | `scale_note` 文案改读者语言 + `_reader_unit()`；`validate_spec` 认领「先校 chrome、再拆框」 |
| `loop/scaffold.py` | `build_pagespec(..., frame=False)`；交付路径显式传 True |
| `loop/build_loop.py` / `loop/pipeline.py` | 交付路径开框；占位图分支 `wrap_frame` + `PLACEHOLDER_NOTE` |

`selector.py` 与 `db/assets.db` 未动（sha `9e7de324728c` / `45e875a2aff5`）；
两张占位图 png 逐字节不变（`8a3ad481e3e5` / `de7403e4a326`）。

### 6.6 两个坑

1. **`validate_spec` 的坐标系陷阱**：包框后 `x_in` 是卡片坐标，直接把 `track_1.x_in`
   改成 20 会先撞上 `validate_frame` 的 `content_bbox` 一致性检查，报的不是 C1。
   因此 `validate_spec` 自己认领「先 `validate_frame`、再 `unwrap` 还原求解坐标」，
   调用方不用记得拆框；测试里篡改几何要先 `unwrap`。
2. **`build_pagespec` 的默认值**：一开始把 `frame` 默认设成 True，结果 40+ 条求解层
   单测（断言的是求解坐标与 27/37 元素）全红。改为默认 False、交付路径显式开框——
   求解与 chrome 两层各自可断言。

### 6.7 已知仍缺

- 半圆第 1 扇区是 `primary`（暖珊瑚），浅色扇形在浅色背景上对比弱（14.4° 那一条
  几乎与白底融在一起）。要改得动色板顺序或给扇区加描边，本轮范围不做。
- 还没有插图位、没有版面格子、没有字号随画布自适应。

## 7. 修复：温度计外圈与管身错位（用户 m05104 肉眼验收发现）

### 7.1 现象与真实原因

用户肉眼看到的是「液柱贴着管身左侧」。**但液柱本身是对的**——实测坐标：

| 元素 | 中心 x（in） |
|---|---|
| `track_1` | 0.9000 |
| `liquid_1` | 0.9000 |
| `bulb_1` | 0.9000 |
| `outline_1.geometry.cx` | **0.6400** |
| `outline_1` 折线实际跨度 | **0.3350 .. 0.9450，中心 0.6400** |

偏的是包住整支温度计的**外圈轮廓**（`outline`），左偏 `0.26 in`——正好等于图框
平移量 `dx`。于是轮廓右壁压在液柱上、左壁离管身很远，看起来就像液柱偏左。

根因链：

1. `outline.geometry` 里存的是**求解坐标系下的绝对坐标**（`cx` / `cy` /
   `cap_top` / `tube_bottom`）；
2. `loop/frame.py::wrap`（第 20 步）只平移了 `x_in` / `y_in`，**没动 geometry**；
3. `loop/thermo_shape.py::outline_polyline` 直接拿 `geometry.cx` 当页面坐标画。

而且它是「自洽地错」：`unwrap()` 把 `x_in` 平移回去之后，`_chk_skin` 用
`t.x_in + w_track/2` 重算出的 `cx` 恰好等于那份**没被平移**的 `geometry.cx`，
校验器于是放行。这就是它逃过 453 条测试的原因。

### 7.2 两处修法（不是二选一，两个都改）

1. **形状函数只信外接盒**（`loop/thermo_shape.py`）：`outline_polyline` 改为
   `ox = el.x_in - (g["cx"] - R)`、`oy = el.y_in - g["cap_top"]`，再用
   `cx = g["cx"] + ox` 这类偏移量推导。geometry 从此只提供**相对尺寸**
   （`R` / `cap_r` / `neck_h`），位置一律由 bbox 决定——无论包框、拆框、
   手工改 x_in，轮廓都跟着走。
2. **修正平移的根因**（`loop/frame.py`）：新增 `ABS_X_KEYS = ("cx",)`、
   `ABS_Y_KEYS = ("cy", "cap_top", "tube_bottom")` 与 `_shift_geometry()`，
   `wrap` / `unwrap` 在平移 `x_in/y_in` 的同时把 geometry 里的绝对坐标一起
   平移。半圆扇区的 `cx`/`cy` 也在同一套键里，一并受益。

只做第 1 条能修好眼前的图，但任何其他直接读 geometry 绝对坐标的消费者还会
再踩一次；只做第 2 条则依赖「谁都得记得平移 geometry」。两条一起做才既修现象
又断根。

### 7.3 回归测试 `tests/test_step20_alignment.py`（8 用例 / 3 TestCase）

| TestCase | 断言 |
|---|---|
| `TestThermometerCentrelines` | 5 根管的 `liquid` / `bulb` 中心 == `track` 中心（delta 0.001 in）；`outline` 折线跨度中点 == `track` 中心；折线不越出自己声明的 bbox |
| `TestAlignmentSurvivesFraming` | 包框后三个中心仍重合；`wrap` 把 geometry 的绝对坐标按 origin 平移（逐键校验）；包框后相邻管中心距与未包框一致；`unwrap` 逐键还原 |
| `TestSkinStaysAligned` | 包框后刻度右端仍严格贴管身右缘 |

### 7.4 验证

- `Ran 461 tests in 6.747s OK`（453 → 461）。
- 三组重出（`out/demo/frame/`，总览 `_sheet_all.png`）：thermometer 10.52×5.85 /
  39 元素，semicircle 7.15×5.85 / 15，fallback 2.80×3.95 / 5。
- 温度计 5 根管逐根实测，`track` / `liquid` / `bulb` / `outline.geometry.cx` /
  `outline` bbox 中心**全部相等**：0.90 / 3.08 / 5.26 / 7.44 / 9.62。
- 像素复核（`out/demo/frame/thermometer/preview.png`）第 1 支管：y=330..470 的
  外圈 72..108（中心 90）、液柱 86..94（中心 90）；球泡行 y=500 外圈 59..121
  （中心 90）、珊瑚 66..115（中心 90.5）。

### 7.5 顺手确认过的边界

- 半圆扇区也只从 geometry 取角度（`start_angle` / `end_angle`），盒子来自 bbox，
  不受本轮影响；`cx`/`cy` 平移后仍然通过 `_chk_C8`。
- `loop/preview.py` 与 `loop/render_arc.py` 的 arc 分支都不读 `cx`/`cy` 画位置，
  只读角度，因此无需改动。

## 8. 半圆扇区描边 + 字号随画布缩放（用户 m05688）

单张卡片收尾的最后两件事。范围仍锁在渲染层：不动求解逻辑、不动色板色值、
不动图框规格、不动 PageSpec 结构、不碰数据库与占位图文件。

### 8.1 半圆扇区描边

| 项 | 值 |
|---|---|
| 角色 | `palette.SECTOR_STROKE_ROLE = "neutral_mid"` → `A8AEB6` |
| 线宽 | `palette.SECTOR_STROKE_PT = 0.5` pt |
| PPTX | `loop/render_arc.py` 在 `apply_fill` 之后给 `arc` 元素补描边 |
| PNG | `loop/preview.py` 的 `pieslice` 描边色改用 `_SECTOR_EDGE` |

为什么必须加：`10/3/3/3/3` 的第 1 扇区只有 `14.4°`，两像素宽的一条楔形；
相邻扇区颜色 ΔE 虽够，但窄扇区没有描边时和背景、和邻扇区都会糊在一起。

0.5 pt 在 100 px/in 的预览上约 0.69 px，Pillow 的 `pieslice` 只支持整数线宽，
取整为 1 px——再细就画不出来。PPTX 侧仍是精确的 0.5 pt。

数值验证（`out/demo/scale/semicircle/preview.png`，圆心 px `(480, 350)`、
`R=205`）：沿 `180°` 与 `194.4°` 两条边界射线各采到 **170** 个
`(168,174,182)` 描边像素；扇区内部色分别是 `primary E8A08C` 与
`secondary C2512F`，两侧不靠颜色也分得开。

### 8.2 字号随画布缩放

```
font_scale  = min(frame_w / 10.0, frame_h / 6.0)      # palette.canvas_scale
font_pt     = clamp(base_pt * font_scale, 6.0, 24.0)  # palette.scaled_font_size
```

- 基准画布 `BASE_CANVAS_W_IN = 10.0` / `BASE_CANVAS_H_IN = 6.0`；
- 取**小的那一维**：只放大宽或只放大高时，字号不能跟着放大到溢出另一维；
- 上下限 `MIN_FONT_PT = 6.0`（可读下限）/ `MAX_FONT_PT = 24.0`（单卡显示上限）；
- 尺寸来源是 `frame_bbox`（`palette.spec_scale`）——第 20 步按用户 m04888 要求
  同时记录内容尺寸与图框尺寸，这里正好用上；没有图框时退回 `width_in/height_in`；
- 结果保留两位小数：`8/10` 与 `4.8/6` 有 1e-16 级尾差，不修掉的话 `Pt()` 按
  百分之一磅截断，16.0 会落成 15.99。

落地位置：`palette.scaled_font_size` 是唯一出处，三个 PPTX 适配器
（`render.py` / `render_arc.py` / `render_thermo.py`）与 `preview.py` 各自
算一次 `spec_scale(spec)` 再传下去；`text_style.apply_text_style(shp, el, scale)`。

### 8.3 三组实测（`out/demo/scale/`）

| 组 | 画布 (in) | font_scale | 标题 pt | 说明 pt | 中心 pt | 标签 pt | 真值 pt | 文本重叠 |
|---|---|---|---|---|---|---|---|---|
| thermometer | 10.52×5.85 | 0.975 | 19.50 | 7.80 | 13.65 | 8.78 | 10.72 | 无 |
| semicircle | 7.15×5.85 | 0.715 | 14.30 | 6.00\* | 10.01 | 6.44 | 7.87 | 无 |
| fallback | 2.80×3.95 | 0.280 | 6.00\* | 6.00\* | — | — | — | 无 |

* 命中 6 pt 下限：`8 × 0.715 = 5.72`、`20 × 0.28 = 5.6`，都被抬到 6 pt。

比例协调性看「pt / 图框宽」：基准是 `20/10 = 2.00`，实测 thermometer
`19.5/10.52 = 1.85`（被高度比 0.975 压住）、semicircle `14.3/7.15 = 2.00`、
fallback `6.0/2.8 = 2.14`。三张卡片并排时文字与框的比例基本一致。

重叠自检：三种卡片内所有文本元素两两求交，均为 `[]`；文本盒也都在
`frame_bbox` 内（`tests/test_step21_font_scale.py` 的
`test_placeholder_card_text_still_fits_its_frame` 覆盖）。

### 8.4 形状数不变（描边是属性、缩放只是数值）

| 组 | 元素数 | PPTX 形状数 |
|---|---|---|
| semicircle | 15 | 15 |
| thermometer | 39 | 39 |

### 8.5 新增测试 `tests/test_step21_font_scale.py`（15 用例 / 5 TestCase）

- `TestSectorStroke`：5 个扇区的线宽都等于 `Pt(0.5)`、颜色都等于
  `neutral_mid`；形状数 15；预览里描边色像素 > 500。
- `TestCanvasScaleFormula`：基准 1.0；只变宽仍 1.0；`20×12 → 2.0`；
  `5×3 → 0.5`；退化尺寸退回 1.0；`spec_scale` 优先 `frame_bbox`；
  `scaled_font_size` 截断到 6 / 24。
- `TestRenderersApplyTheScale`：未包框 `10×6` 标题仍 20 pt；`12×7.2` 时变大；
  `8×4.8` 时 16 pt；预览里大画布标题的暗像素多于小画布。
- `TestSemicircleAndThermometerShapesUnchanged`：半圆 15、温度计 39。
- `test_placeholder_card_text_still_fits_its_frame`：小卡片所有元素仍在框内。

### 8.6 未做

- 没有改任何布局（文本盒坐标一律没动）；小卡片文字被 6 pt 下限兜住后仍然
  只占标题带的一小条，这是「不重排版面」的代价，若要更好的观感需要在版式层
  重新分配标题带高度，不在本轮范围。
- 未做多图混排、版面格子、图文混排。

---

## 9. 单卡片适配外部边界（第 23 步，用户 m05768）

## 第 23 步：单卡片适配外部边界（用户 m05768）

「内容决定画布」逆转为「外部给边界、内部自适应」。本轮只做单卡片这一层地基。

### 做了什么

- 新增 `loop/fit.py`：`fit_to_target()` / `minimum_target()` / `BoundaryError`。
  缩放 25 个长度参数（`LENGTH_PARAMS`），字号走 m05688 的 `scaled_font_size`。
  标题与说明在卡片模式下由 chrome 提供，求解画布不再为它们留位
  （`CHROME_OWNED_PARAMS` 归零，省下 1.65 in）。
- `loop/frame.py::wrap(..., canvas_in=(w,h))`：框钉死在给定尺寸，内容居中。
- `loop/scaffold.py::build_pagespec(..., target_width_in=, target_height_in=)`。
  两者必须同给；不传时行为与之前逐位一致。
- `loop/pipeline.py::run_selected(..., target_width_in=, target_height_in=)`，
  占位图卡片同样按目标尺寸等比缩进并居中。
- `loop/templates.py` + `loop/solve.py`：半圆新增 `w_legend` 参数，C7 的半径
  先从画布里给图例留一列再取两轴较小者。**10×6 上仍是高度限制，R=2.05 不变。**

### 两个坑

1. **可行区间不是单侧区间**：s 太小标签装不下一行字（字号被 6 pt 兜住），
   s 太大相邻标签互相压。所以不能二分，只能粗扫 0.05 再向上细修 0.01。
2. **「因为字太大所以不量字」的死循环**：文字体检失败时也必须拿几何解去量
   「字到底需要多大」，否则行高/列宽下限永远抬不上去。改成双路搜索：
   一路要文字过关，一路只要几何过关，用后者的解抬下限。

### 实测（`out/demo/target/`，`summary.json` + `_sheet_all.png`）

| 卡片 | 目标 | 产出画布 | 元素 | scale | font_scale |
|---|---|---|---|---|---|
| thermo_5x4 | 5×4 | 5.0×4.0 | 39 | 0.72 | 0.50 |
| thermo_7x3 | 7×3 | 7.0×3.0 | 39 | 0.67 | 0.50 |
| semi_3x3 | 3×3 | 3.0×3.0 | 15 | 0.13 | 0.30 |
| semi_4x4 | 4×4 | 4.0×4.0 | 15 | 0.84 | 0.40 |
| semi_12x14 | 12×14 | 12.0×14.0 | 15 | 1.00 | 1.20 |
| placeholder_4x4 | 4×4 | 4.0×4.0 | 5 | — | — |

每张都过 `validate_frame` + `validate_spec`，元素全部在格内。

### 极小尺寸报错

2×2 装不下，抛 `BoundaryError` 并附每轴下限：

- 温度计：约 **3.04 × 2.35 in**（chrome 1.75 + 标签/真值行 + 管身至少一格）
- 半圆：约 **2.37 × 2.39 in**（chrome 1.75 + 图例列 + 半径）

### 测试

新增 `tests/test_step22_target_box.py`（10 用例）：五个极端尺寸落点、
占位图居中、字号夹在 6–24 pt、装不下必须报错、不传 target 时逐位不变、
半圆图例列在宽画布上不被挤没。全量 **486 tests OK**（476 → 486）。

未动：`loop/selector.py`、`loop/models.py`、`db/assets.db`。


## 10 自由布局 0.1：流式排版（用户 m05945）

### 10.1 输入结构

* `LayoutSpec(width_in, height_in, margin_in, gutter_in, fit_oversized=True)`
  —— 整版画布与间距。`usable_width_in = width - 2*margin`。
* `CardSpec(name, kind, chart_key=None, values=None, semantic, title,
  width_in=None, height_in=None)` —— 一张卡片：放什么由调用方给。
  尺寸两条来源：不给 `width_in/height_in` 就用「按内容长大」的自然尺寸；
  给了就当 target 传给 `build_pagespec`，由第 23 步的适配器缩进去。
* `PageLayoutSpec(width_in, height_in, margin_in, gutter_in, cards, rows)`
  —— 输出：每张卡片的最终 `x_in/y_in/w_in/h_in` + 内部子 `PageSpec`，
  `to_dict()` 可直接落 `pagelayout.json`。

### 10.2 分配算法（纯流式）

1. 游标 `(cursor_x, cursor_y)` 从 `(margin, margin)` 起，行带高 `row_h = 0`。
2. 取下一张卡片：若当前行非空且 `cursor_x + w > margin + usable_width`
   → 收行（`cursor_y += row_h + gutter`，`cursor_x = margin`，`row_h = 0`）。
3. `cursor_y + h > height - margin` → 抛 `LayoutOverflowError`
   （带 `placed` / `remaining` / `needed_h` / `page_h`，不静默越界）。
4. 放：记 `(x_in, y_in)`，`cursor_x += w + gutter`，`row_h = max(row_h, h)`。
5. 卡片宽 > `usable_width` → 抛 `LayoutOverflowError`
   （换行救不了：它已经在行首）。`fit_oversized=True` 时改走第 23 步的
   target 适配器按可用宽度等比缩一张，而不是截断。

行带高度取该行最高的卡片，行内顶端对齐 —— 这是流式排版的固有性质：
同一行里较矮的卡片下方会留白，**行与行之间的间距仍严格等于 gutter**。

### 10.3 渲染

`loop/render_page.py`（新增）写了一个「全集」适配器，因为整版是**混合卡片**
页面：温度计皮肤（ticks/outline）、半圆扇区（arc）、占位图（image）、每张卡片
自己的图框与标题带会同时出现在一份规格里，而现有三个适配器各只认一部分。

* `flatten(page)` 把整版摊平成**一份** `PageSpec`：元素 id 加 `c{i}_` 前缀、
  `x_in/y_in` 平移，`geometry` 里的绝对坐标（`cx`/`cy`/`cap_top`/`tube_bottom`）
  一起搬（第 21 步的教训：外圈折线直接拿 `geometry.cx` 当页面坐标），
  每张卡片的字号比例写在 `geometry["_scale"]`。
* PPTX：`render_thermo._add_basic` + `_add_skin` + 一个 image 分支；
  写字用元素自己的 `_scale`，不是整版比例。
* 预览：**逐卡片渲染再贴回画布**，保证整版预览与单卡预览逐像素一致
  （否则整版比例会把小卡片上的字放大/缩小）。

### 10.4 演示实测（`out/demo/page/`）

画布 10×15 in，margin 0.4，gutter 0.3 → 可用宽 9.2 in。

| 卡片 | 预设尺寸 | 位置 (x, y) | 尺寸 (w, h) | 行 | 元素 |
|---|---|---|---|---|---|
| thermo | 9.2×4.6 | (0.40, 0.40) | 9.2×4.6 | 0 | 39 |
| semi | 4.45×4.6 | (0.40, 5.30) | 4.45×4.6 | 1 | 15 |
| placeholder | 4.45×4.6 | (5.15, 5.30) | 4.45×4.6 | 1 | 5 |

* 水平邻距 `5.15 - (0.40+4.45) = 0.30` = gutter；行带垂直邻距
  `5.30 - (0.40+4.60) = 0.30` = gutter。
* 整版 `preview.png` 1000×1500；`page.pptx` 59 个形状 = 39+15+5，
  全部按 `c{i}_{原id}` 命名，含一个 PICTURE（占位图）。
* 像素复核：thermo 区非白 17368（含 `E8A08C` 2975）、semi 区 7956
  （含 `C2512F` 566 / `E8B85C` 539）、placeholder 区 6476
  （含 `7A8088` 87）；三区标题带都是 `D6DADF`。

### 10.5 自然尺寸的反例（验收闸口的溢出验证）

同一组卡片不给预设尺寸时，温度计卡片按内容长大到 **10.52 in**，比 9.2 in 的
可用宽度还宽 → `LayoutOverflowError: 卡片 thermo 宽 10.52 in > 可用宽度
9.20 in（整版 10 in 去掉两侧 0.4 in）`，`placed=[]`、`remaining=['thermo']`。
记录在 `out/demo/page/_natural_overflow.txt`。

高度溢出同样报错（`height_in` 不够时 `needed_h` / `page_h` 一并给出）。

### 10.6 本轮明确未做

多栏对齐、力导向、卡片与正文/大标题混排、版面网格、卡片跨行跨列、
自动决定「哪张卡片该多大」（本轮尺寸要么来自内容、要么来自调用方预设）。

### 10.7 已知限制

* **行内留白**：同一行里较矮的卡片下方留白，是流式排版的固有代价；
  要做「等高行」得让引擎反过来改卡片尺寸（属下一轮）。
* **自然尺寸普遍偏大**：三张卡片自然尺寸加起来需要约 16.3 in 高度，
  装不进 10×15 的一版 —— 所以本版演示用预设尺寸（任务允许的两条来源之一）。
  是否让引擎默认把大卡片缩到格子宽度，是需要产品决定的事（已向用户提问）。


## 11 排版引擎 0.2：同行等高拉伸 + 溢出保底（用户 m05995）

### 11.1 溢出策略（落实上一轮拍板）

* `LayoutSpec.fit_oversized` 默认 `True`：卡片自然尺寸超过可用宽度时按可用宽度
  等比缩一张，不截断。
* 新增保底防线 `LayoutFitError`（`loop/layout.py`）。两条触发路径：
  1. 为宽度缩完之后，说明文字（`note` 档）连 `palette.MIN_FONT_PT`（6pt）都不到
     → 「卡片 xxx 缩得太小，已无法阅读」；
  2. 目标格子低于单卡适配器算出的最小可行尺寸（`fit.BoundaryError`）
     → 换成排版层的 `LayoutFitError`，消息里带上最小可行尺寸。
* 实测：整版宽 4.0 in（可用 3.2 in）放自然尺寸的温度计卡片 →
  `LayoutFitError: 卡片 thermo 缩得太小，已无法阅读：3.20×1.78 in 的格子低于
  这张图的最小可行尺寸 3.04×2.35 in（chrome 就占满了格子）`，
  记在 `out/demo/page/_fit_error.txt`。
* `LayoutFitError` **不是** `LayoutOverflowError` 的子类：一个是「缩到看不清」，
  一个是「格子里放不下一行」，调用方要能分辨。

### 11.2 等高拉伸算法（两趟）

1. **分行**：先按各自尺寸造卡片（只用宽度）决定每行放哪几张。
2. **等高**：算该行最高卡片高度 `MaxH`；把行内**较矮**的卡片按
   `target_height_in = MaxH`（宽度保持自己的）重造一次；整行顶端对齐放下。

关键性质：
* 只对较矮的卡片生效 —— 行里最高的那张不会被压矮，所以拉伸**永远不会**
  让内容变小或让字缩水。
* 宽度保持不变：fit 引擎是**等比**缩放所有长度参数，拉高只会让内容整体
  放大到宽度允许的上限，不会把图形压扁（不变形）。
* 行带高度始终取该行最高卡片，决定下一行起点；`equal_height=False` 时
  卡片保留自己的高度，行内较矮的卡片下方就是留白（0.1 的行为，留作对照）。

### 11.3 演示实测（`out/demo/page/`）

画布 10×15 in，margin 0.4，gutter 0.3，可用宽 9.2 in。第二行刻意给两个
**不同高度**的预设（semi 5.2 / ph 3.6）：

| 卡片 | 预设尺寸 | 位置 (x, y) | 排版后 (w, h) | 行 |
|---|---|---|---|---|
| thermo | 9.2×4.6 | (0.40, 0.40) | 9.2×4.6 | 0 |
| semi | 4.45×5.2 | (0.40, 5.30) | 4.45×5.2 | 1 |
| placeholder | 4.45×3.6 | (5.15, 5.30) | **4.45×5.2**（被拉高） | 1 |

* 同行两卡 `y_in` 相同（5.30）、`h_in` 相同（5.20）→ 底部严格对齐。
* 像素复核：semi 与 placeholder 两张卡片的图框下边线都落在 y=1049
  （区域 530..1050），一像素不差；thermo 落在 y=498（区域 40..500）。
* 间距：水平邻距 `5.15-(0.40+4.45)=0.30`、行带垂直邻距
  `5.30-(0.40+4.60)=0.30`，都严格等于 gutter。
* 拉伸后的占位图卡片：自检通过（`validate_frame` OK、`text_problems` 为空、
  全部元素在卡片盒内）。
* 对照：`equal_height=False` 出图 `out/demo/page/_unequal/preview.png`，
  同款数据下行内出现留白。

### 11.4 本轮明确未做

不碰 `selector/solve/models/db`（sha 复核：`loop/solve.py b62808464658`、
`loop/scaffold.py 71077d79491a`、`loop/pipeline.py 39cd4b790a98`、
`loop/models.py 2f68365a05d4`、`loop/selector.py 9e7de324728c`、
`db/assets.db 45e875a2aff5` 全部与上一轮一致）。不做图文混排、多栏对齐、
力导向、跨行跨列。

### 11.5 已知限制

* 等高是「拉高较矮的卡」而不是「压矮较高的卡」，所以行带高度由行内最高
  卡片决定；极矮的整版仍可能因为一行放不下而溢出（报错，不静默）。
* 拉伸后内容只放大到宽度允许的上限，不会撑满整个拉高后的盒子 ——
  盒子留白在卡片内部（内容居中），这是刻意的：撑满就得非等比拉伸 = 变形。

## 12. 图文混排 0.1：TextBlock 与文本流（用户 m06055）

### 12.1 TextBlock 定义（`loop/layout.py`）

```python
TextBlock(text: str, style: str = "body", align: str = "left",
          width_in: float | None = None, name: str | None = None)
```

* `style` 直接借用色板字号表的**设计角色**：`title / subtitle / body /
  label / note` —— 标题、正文、说明的字号天然遵循既有规范（m04549），
  不另立一套；
* `align` 取 `left / center / right`；`width_in` 默认占满可用宽度；
* 构造时校验样式名、对齐名与非空文本，`name` 缺省取正文首行前 12 字。

### 12.2 折行与高度：为什么排版层自己折（`loop/text_flow.py`）

页面上文字与卡片共用一个纵向游标，**文字占多高**决定了后面所有元素的 y。
让 PowerPoint 自己折行，排版层就只能猜高度，猜错就是重叠或留白。所以：

* 排版层用与预览同一套字体度量（`fit._load_font`）折一次行，结果写进
  元素（`geometry["lines"]`）；
* PPTX 端 `word_wrap = False` + 按行插换行，PNG 端逐行画 —— 两个渲染器
  照抄同一份折行，**「排版占的高度」与「看到的行数」永远一致**；
* 高度公式：`行数 × 字号(pt) × 1.35 / 72 + 2 × 0.05 in`（上下各留一点呼吸位，
  它算进块高，所以块与块之间仍是严格 gutter）。

### 12.3 混合流的分配算法（`flow_layout`）

游标自上而下、自左而右：

1. 遇到 **CardSpec**：按宽度往当前行塞，放不下就**收行**（先做 0.2 的行内
   等高拉伸，再落坐标）；
2. 遇到 **TextBlock**：先把待排的卡片行收掉，然后按可用宽度折行、算出高度、
   **整块独占一行**放下；
3. 任一步越过下边距抛 `LayoutOverflowError`（含已放置项、剩余项、需要高度），
   绝不静默越界。

这就是用户建议的「上下型排布」。**它让「文本折行高度与卡片行对齐」这个
问题根本不存在** —— 文本与卡片不共享行，所以不需要停下来问；两侧环绕
（文字绕着卡片排）是另一套算法，本轮明确不做。

`flatten()` 把文本块也摊进整版 PageSpec（id 前缀 `t{i}_`，`geometry` 带
`{"block": True, "lines": [...], "align": ...}`），所以它们同样参与
`read_shapes` 回读与 PPTX 渲染。

### 12.4 演示实测（`out/demo/paper/`，10 × 15 in）

流：大标题 → 导语 → 温度计卡片 → 正文 → 半圆图与占位图并排 → 尾段正文。

| 项 | 类型 | x_in | y_in | w_in | h_in | 行数 |
|---|---|---|---|---|---|---|
| 取暖电器换季热销：五类小家电成交额环比增速榜 | 标题 | 0.40 | 0.4000 | 9.20 | 0.4750 | 1 |
| 入冬以来取暖电器…（导语） | 正文 | 0.40 | 1.1750 | 9.20 | 0.5125 | 2 |
| thermo | 卡片 | 0.40 | 1.9875 | 9.20 | 4.2000 | — |
| 从品类结构看… | 正文 | 0.40 | 6.4875 | 9.20 | 0.3063 | 1 |
| semi | 卡片 | 0.40 | 7.0938 | 4.45 | 4.6000 | — |
| ph | 卡片 | 5.15 | 7.0938 | 4.45 | 4.6000 | — |
| 分年龄看… | 正文 | 0.40 | 11.9938 | 9.20 | 0.3063 | 1 |

* 五处相邻行带垂直间隔**全部** 0.3 in（= gutter）；
* 并排两卡水平邻距 0.30 in（= gutter）；
* 全部项都在 `[0.4, 9.6] × [0.4, 14.6]` 内，任意两项外接盒不相交；
* `preview.png` 1000 × 1500；四个文本块区域的深色像素数 4749 / 3349 /
  2524 / 1954（字真的画出来了）；
* `page.pptx` 63 形状 = 39 + 15 + 5 + 4，每个元素都能 `read_shapes` 回读，
  标题文本在 PPTX 里可读。

溢出验证：同一股流塞进 10 × 6 in →
`LayoutOverflowError: 换行后高度也装不下：已用高度 6.59 in > 可用 6.00 in：
排不下：thermo`（记在 `out/demo/paper/_overflow.txt`）。

### 12.5 改动面与验收

改动仅三个文件：新增 `loop/text_flow.py`、`loop/layout.py`（新增 TextBlock /
PlacedBlock + 混合流）、`loop/render_page.py`（文本块渲染）。单卡模块零改动：
`loop/solve.py b62808464658`、`loop/scaffold.py 71077d79491a`、
`loop/preview.py 61314e7ba1a6`、`loop/render.py ce42c5ba5880`、
`loop/fit.py d36beb50b5d9`、`loop/pipeline.py 39cd4b790a98`、
`loop/selector.py 9e7de324728c`、`db/assets.db 45e875a2aff5` 全部与上一轮一致。

新增 `tests/test_step25_text_flow.py`（20 用例 / 5 TestCase）。`Ran 539 tests OK`
（519 → 539）。

### 12.6 本轮明确未做

两侧环绕（文字绕卡片）、分栏、图文混排的版面网格、跨行跨列卡片、多卡片
之间的对齐轴线。这些都留给后续版本。


## 13. 自动化编排 0.1（用户 m06157）

### 13.1 新增模块

| 文件 | 作用 |
|---|---|
| `loop/compose.py` | 拆段 / 认标题导语 / 数据匹配 / 组流 / 整版输出。唯一的编排入口。 |
| `scripts/build_auto_layout_demo.py` | 端到端演示 + 退化演示，产物 `out/demo/auto_layout/`。 |
| `tests/test_step26_auto_compose.py` | 27 用例 / 7 TestCase。 |

只调 `loop.layout`（流式排版）与 `loop.selector`（选型），不改单卡渲染与卡片内部约束。

### 13.2 三条规则

1. **拆段**：先按空行、再按换行切；整篇只有一段时按 `。！？` 断句。
2. **标题与导语**：第一段只有一句且 ≤ 34 字 → 整段当标题；有两句以上但首句
   ≤ 34 字 → 首句当标题、余下句子并回导语；首句也长就整段当标题，宁可不拆。
   标题之后 1 段并成导语，其余段落依次进正文。
3. **数据匹配**：把每个 `chart_title` 解析成 `(地区, 品类, 维度, 指标)` 四个
   侧面。段落必须同时提到**品类**、**指标**与（**维度**或**地区**）才算配上；
   带地区的数据组必须在段落里看到那个地名。候选多个时按侧面加权
   （地区 4 / 品类 3 / 维度 3 / 指标 2）取最高分，平分时通用组（无地区）优先，
   再按 chart_key 排序 —— 结果确定、可复现。
   `占比` → 「占比构成」，`环比增速` → 「比较大小」，交给选型器定图形。

这条「品类 + 指标 +（维度或地区）」合取规则是为了防一件事：光凭「取暖」两个字
就能同时勾上八组数据（取暖电器有 8 个 chart_key，其中 3 个还互为地区变体）。

### 13.3 演示实测（`out/demo/auto_layout/`）

输入只有一段 4 段的稿子 + 数据库，没有手写排版流。生成的流：

| # | 内容 | 结果 |
|---|---|---|
| 0 | 取暖电器换季热销：五类小家电增速领跑 | TextBlock(title) |
| 1 | 入冬以来取暖电器进入销售旺季… | TextBlock(body) 导语 |
| 2 | 从细分品类看，取暖电器的成交额环比增速… | TextBlock(body) |
| 3 | — | CardSpec(heat_ratio_top5 → thermometer) |
| 4 | 分年龄看，各年龄段消费者的取暖电器成交额占比… | TextBlock(body) |
| 5 | — | CardSpec(heat_age → semicircle) |

落位（10×15 / margin 0.4 / gutter 0.3）：标题 (0.40, 0.40, 9.20, 0.475)；
导语 (0.40, 1.175, 9.20, 0.3063)；增速段 (0.40, 1.7812, 9.20, 0.3063)；
温度计卡 (0.40, 2.3875, 8.9375, 4.97)；年龄段 (0.40, 7.6575, 9.20, 0.3063)；
半圆卡 (0.40, 8.2637, 6.0744, 4.97)。六项两两不相交、全在版内、
五处相邻行带垂直间隔都是 0.30 in，底部 13.2338 in。

卡片预设盒子由 `_preset()` 从内容自然尺寸等比推：`ratio = min(1, 可用宽/自然宽,
可用高 × 0.35 / 自然高)`。0.35 是排版政策 —— 一页要放两三张图再配文字，
让一张图吃掉整版高度后面就排不下了。

### 13.4 退化与不适用

* **匹配不到任何数据**（`out/demo/auto_layout/_plain/`）：流退化为 3 个纯文本块，
  `notes` 记一条 `no_data_matched`，照常出图，不崩。
* **选型器判「不适用」**：由 `on_unapplicable` 决定，`"skip"`（默认）只留文字并记
  `not_applicable` note，`"placeholder"` 配一张占位图。本轮演示数据不会触发
  （两组都是 5 项、无负值、非全相等），两条路径都有测试覆盖。

### 13.5 验收

| 闸口 | 结果 |
|---|---|
| 只传 text + db 出整版 PageLayoutSpec | ✅ `compose_page(COPY, out)` |
| 流顺序合理（标题在最前） | ✅ 断言 `flow[0].style == "title"` |
| 匹配失败退化为纯文本页不崩 | ✅ `TestDegradation`（2 用例） |
| 全量测试 539+ 全绿 | ✅ 566 tests OK |
| 排版引擎与单卡模块零改动 | ✅ `layout.py`/`render_page.py` 未动；`solve/scaffold/fit/selector/models/db` sha 与第 26 步一致 |

### 13.6 未做

不做两侧环绕（上下型排布）、不做多栏、不做 NLP/模型抽取、不做段落与卡片的
共行排版；段落与卡片永远上下相邻。卡片尺寸政策（0.35 上限）写死在 compose，
不是全局版面规则 —— 整版版面策略留待下一轮。

---

## 14. 多栏图文混排 0.1（用户 m06230）

单栏流式排版长文一栏到底，不像报纸。本轮把版面升级成**多栏**：文本块可以分栏、
可以跨栏，卡片可以跨栏，卡片之间还能量并排。同时把上一轮留在 `compose.py` 里的
「卡片高度上限 0.35」挪进 `LayoutSpec`（政策属于版面，不属于编排）。

### 14.1 三处改动

| 文件 | 改动 |
|---|---|
| `loop/text_flow.py` | 新增 `inner_column_width_in` / `balance_lines` / `wrap_columns` / `columns_height_in`：块内先按**栏宽**折行，再按行数均分到各栏（阅读顺序保持左栏接右栏） |
| `loop/layout.py` | `LayoutSpec` 增 `column_count`(1..3) / `column_gutter_in`(默认 0.2) / `max_card_height_ratio`(默认 0.35)；`CardSpec` 增 `column_span` / `note`；`TextBlock` 增 `column_span` / `columns`；`card_box` 钉死跨栏宽度；`flow_layout` 重写成「按栏位塞行」 |
| `loop/render_page.py` | `_add_text_block` / `_draw_block` 按 `line_groups` **每栏各画一个文本框**（PPTX 每栏一个 TextBox） |

栏位算术（10 in 宽、margin 0.4、2 栏、栏间距 0.2）：可用宽 9.20、栏宽 **4.50**、
`span_width_in(1)=4.50`、`span_width_in(2)=9.20`、`slot_x_in = 0.40 / 5.10`。
行内并排两项之间的空隙是**栏间距 0.2**，行与行之间仍是 **gutter 0.3**。

### 14.2 兜底政策：默认改配占位图

`build_flow(on_unapplicable=...)` 的默认值由 `"skip"` 改为 `"placeholder"`，并给
占位图写一句读者能懂的说明（`_fallback_note`）：

| 选型器理由里的关键字 | 写进占位图的说明 |
|---|---|
| `MAX_SLICES` / `max_slices` | 示意图：分项过多，建议看表格。 |
| `全相等` | 示意图：各项数值完全相同，看表格更清楚。 |
| `含负值` | 示意图：这组数据含负值，不适合这种画法。 |
| 其余 | 示意图：这组数据暂时没有合适的图形，先占个位。 |

`skip` 仍然可用（只留文字 + 一条 `not_applicable` note）。真实库里 12 组数据都是
5 项，只有「6 项占比」这类输入才会触发兜底，所以演示之外用选型器的**真实拒选文案**
做断言（`test_note_explains_the_reason`）。

### 14.3 高度政策进 LayoutSpec，顺手修掉「宽而扁」

`compose.MAX_CARD_HEIGHT_RATIO` 已删除，改为 `LayoutSpec.max_card_height_ratio`。

改这一条时暴露了一个 bug：多栏里**单栏卡片的宽度是被钉死的**（恰好一栏宽 4.5），
高度按自然比例换算。半圆图自然尺寸 7.15×5.85，缩到 4.5 只剩 3.68 高，内容盒
（4.5−0.6=3.9 宽、3.68−1.75=1.93 高）比它需要的最小内容高 2.39 还矮，于是抛
`LayoutFitError`。这不是物理极限 —— 是「宽度已定、高度白让给留白」。修法：
`_build_card_fitted` 在装不下时把高度**顶到 `max_card_height_in`** 再试一次（宽度
不变、内容居中），两次都装不下才抛错。于是「极小尺寸装不下」的报错语义没变，
而「宽而扁」的格子能用了。

### 14.4 演示实测

`out/demo/multicol/`（自动：只给稿子 + db，2 栏）与 `out/demo/multicol/_spread/`
（手工流：跨栏标题 + 块内两栏正文 + 两张单栏卡片并排）。

**手工页坐标**（10×15，2 栏）：

| 项 | span | x_in | y_in | w_in | h_in |
|---|---|---|---|---|---|
| 标题 | 2 | 0.4000 | 0.4000 | 9.2000 | 0.4750 |
| 左栏导语 | 1 | 0.4000 | 1.1750 | 4.5000 | 0.5125 |
| 右栏结尾 | 1 | 5.1000 | 1.1750 | 4.5000 | 0.3063 |
| 温度计卡 | 2 | 0.4000 | 1.9875 | 9.2000 | 4.9700 |
| 两栏正文 | 2 内 2 栏 | 0.4000 | 7.2575 | 9.2000 | 0.5125 |
| 半圆卡 | 1 | 0.4000 | 8.0700 | 4.5000 | 4.9700 |
| 占位卡 | 1 | 5.1000 | 8.0700 | 4.5000 | 4.9700 |

底部 13.04 in（画布 15），七项两两外接盒不相交。

**像素复核**（preview 100 px/in）：导语行左右栏深色像素 3176 / 1969（真的分了两栏），
两栏正文左右 4040 / 2619，**栏间 0.2 in 内深色像素 0**；卡片框竖边落在
x=40 / 489 / 510 / 959 px，即 0.40 / 4.90 / 5.10 / 9.60 in —— 左卡右缘与右卡左缘
正好夹出 0.2 in 的栏间距，右卡右缘正好压在右边距上。

**自动页**（`out/demo/multicol/`）：行序列 `text → row → cards → text → cards`，
标题跨 2 栏、导语与增速段各占一栏并排、两张卡片各占满整行。

### 14.5 验收

| 闸口 | 结果 |
|---|---|
| 2 栏下文本块宽高严格匹配、不溢出栏宽 | ✅ 宽度 = 栏宽 4.5 / 跨栏 9.2；高度 = 最长栏行数 × 行高 + 2×pad |
| 跨栏文本与卡片对齐左右边距 | ✅ `x=0.40`、`x+w=9.60` |
| 同行不交叠、总高超画布抛错 | ✅ 两两外接盒不相交；`LayoutOverflowError` / `LayoutFitError` 都有用例 |
| 兜底默认配图生效 | ✅ 默认 `placeholder`，note 写进卡片的说明位并渲染出来 |
| 全量 566+ 全绿、不破坏单栏 | ✅ **600 tests OK**；`out/demo/page`、`out/demo/paper`、`out/demo/auto_layout` 三页坐标逐项与上一轮完全一致 |

### 14.6 未做与已知限制

- 不做两侧环绕：卡片与文本块在垂直方向永不共享一行（用户明确要求）。
- 同一行里只做**顺序摆放**：一栏的段落与一张卡片不会并排（span=1 的卡片会和
  另一张 span=1 的卡片并排，段落之间也可以并排，但两者不混排）。
- 段落流不会「回填」上一行的空栏 —— 一行放不下就换下一行，宁可留白。
- 栏只能平均分，不做不等宽栏。


## 15. 图文并茂 1.0：素材库接进自动编排（用户 m06471）

多栏 0.1 之后，自动编排只会生成图表卡片 —— 版面是「四个矩形凑一页」。
本轮把素材库（`v_asset_search`）接进编排：匹配到数据时，除了配图表卡片，
再按这组数据的 `chart_semantic` 从库里挑**一张装饰插图**排进版面。

### 15.1 新增的流元素 `ImageBlock`

与 `TextBlock` / `CardSpec` **平级**，`flow_layout` 照常给它分配 `x/y/w/h`：

| 字段 | 含义 |
|---|---|
| `path` | 素材的 `local_path`（相对仓库根，正斜杠） |
| `style` | `icon` / `cover`（`IMAGE_STYLES`） |
| `align` | `left` / `center` / `right`（盒内水平定位） |
| `width_in` | 显式宽度；不给就按栏位算（1 栏 = 栏宽，跨栏 = 跨栏宽） |
| `column_span` | 占几栏（1..3） |
| `max_height_in` | 高度上限；不给就用 `LayoutSpec.max_image_height_in` |
| `asset_id` / `tag` / `semantic` | 只作溯源，渲染不用 |

**宽高比从文件本身读**（`image_size_in` → PIL `size/100`），不由调用方猜：
高度算错就是重叠或留白。`image_box()` 给盒子高度 `min(宽/纵横比, 上限)`，
`fit_rect_in()` 再按比例缩到盒内并居中 —— 只缩不放、**永不变形**。
`PlacedImage.rect` 记下盒内的绘制矩形（`dx, dy, dw, dh`），行内等高拉伸时
`dy` 再加上 `(行高 − 盒高)/2` 做垂直居中。

新增 `LayoutSpec.max_image_height_ratio = 0.2`（可用高度的两成），
防止一张方形图标把整行撑满。

### 15.2 compose 的选图逻辑

`_pick_illustration(semantic, db_path, used)`：

1. **顺序照用 `v_asset_search` 的排序**（weight 降序、同权按 id）—— 权重就是
   S4 表达「同一档里谁更适合当配图」的方式，调用方不再自己排一遍；
2. 跳过 `kind != "icon"`（整版图 `page_image` 不参与检索，P1）、跳过本页已用过
   的 `asset_id`（同一页不重复贴同一张图标）、跳过空路径；
3. **任何异常都返回 `None`** —— 少一张插图是遗憾，排不出整版是事故；
4. `template == "placeholder"` 时不配插图：占位图本身就是一张图。

插图与文本块的配合分两种情况：

* **多栏**：段落独占一整行（内部按栏折行），下一行留给「图表 1 栏 +
  插图 1 栏」并排 —— 报纸里图文咬合的样子；
* **单栏**：没有第二条栏位，若让插图独占整行，一张 2.84 in 的装饰图会白白
  吃掉一行（10×15 的演示页直接 `LayoutOverflowError`：已用高度 16.77 > 15.00）。
  改成**把这一行自己切成两段**：图表 66%（`ILLUSTRATED_CARD_SHARE`）、
  插图 34% 减 gutter，两者合计正好铺满可用宽度，行高取两者较大者 ——
  插图通常矮于图表，等于白搭不占额外高度。

### 15.3 演示实测（`out/demo/illustrated/`）

| 页 | 说明 | 结果 |
|---|---|---|
| `_spread/` | 手工流，严格照任务描述的结构 | 标题(跨2栏) → 导语 → 温度计卡(2栏) → 正文(2栏) → 半圆卡(1栏) + 插图(1栏) |
| `auto/` | 只给 text + db，全自动 2 栏 | 行序列 `text/text/text/row/text/row`，两处图文咬合 |
| `_no_asset/` | 把素材检索打桩成空结果 | 整页照排、无插图、不抛异常 |

手工页坐标（10×15 / margin 0.4 / gutter 0.3 / 2 栏 / 栏间距 0.2）：

```
text  标题              x=0.4000 y=0.4000 w=9.2000 h=0.4750
text  导语              x=0.4000 y=1.1750 w=4.5000 h=0.5125
card  heat_ratio_top    x=0.4000 y=1.9875 w=9.2000 h=4.9700
text  正文(内 2 栏)      x=0.4000 y=7.2575 w=9.2000 h=0.5125
card  heat_age          x=0.4000 y=8.0700 w=4.5000 h=4.9700
image illustration_26   x=5.1000 y=8.0700 w=4.5000 h=2.8400 rect=(0.83, 1.065, 2.84, 2.84)
```

半圆卡与插图同行（`y` 都是 8.07），左卡右缘 4.90 与右图左缘 5.10 正好夹出
0.2 in 栏间距；插图盒高 4.97 里 2.84 的图垂直居中（`dy = 1.065`）。

自动页挑到的两张图：`illustration_17` = `assets/icons/radiator_soft.png`
（比较大小档）、`illustration_26` = `assets/icons/people.png`（占比构成档）。

**像素复核**（本模型读不了图，改用配色指纹）：

* 手工页插图区 `(593,914)-(877,1198)` 出现 `(96,120,190)` —— 正是 `people.png`
  的签名色，说明人形图标真的画进了版面；
* 自动页 radiator 区主色 `(250,223,216)`，正是 `radiator_soft.png`（alpha 0.2）
  叠白底的理论值（`232×0.2+255×0.8=250.4`、`96×0.2+255×0.8=223.2`、
  `60×0.2+255×0.8=216`）—— alpha 合成正确，没把「柔化版」当实心图画。

### 15.4 验收

| 闸口 | 结果 |
|---|---|
| 自动编排生成的流含 `ImageBlock` | ✅ 标题 + 导语 + 2 段正文 + 2 卡 + 2 插图 = 8 项 |
| 按比例缩放不变形、不与文字/卡片重叠 | ✅ `dw/dh == 源图纵横比`；两两外接盒不相交（用例逐对判） |
| 仍合多栏规则（占 1 栏 = 栏宽） | ✅ `w == column_width_in == 4.5`；跨栏 = `usable_width_in` |
| 查不到素材不阻塞排版 | ✅ 空结果与「库抛异常」两条都用例验过，图表照排 |
| 全量测试全绿、不改单卡模块 | ✅ **639 tests OK**（600 → 639）；`solve`/`scaffold`/`fit`/`frame`/`selector`/`models` sha 全未变 |

### 15.5 未做

* 不做两侧环绕（沿用 0.1 的上下型：卡片与文本块垂直方向永不共享一行）。
* 插图只按 `chart_semantic` 选，不按文本主题选（桥接是 S6 的事）。
* 不做插图与图表的视觉配对（同一段既配图又配卡，但两者不是同一张「图说」）。
* `cover` 样式只声明未使用 —— 当前所有素材都是 `icon`。

## 16. S6 桥接 0.1：按文本主题配插图（用户 m06731）

### 16.1 主题词表反着建

没有另编一份主题词表，而是**从素材出发**：`semantic_theme_terms()` 取
`tag_vocabulary` 里 `tag_type='semantic'` 且**真挂在可检索素材上**的词，
再加上它们的 `aliases`。库里有素材的主题才进词表 —— 否则会抽出一个查不到图
的主题，白白走一遍降级路径。

| 项 | 值 |
|---|---|
| 原始词面 | 61（19 个规范标签 + 42 个别名） |
| 过滤后可用词面 | **55**（单字词面「冷」「火」「焰」「％」「袜」「雪」丢掉） |
| 最短词面 | `THEME_MIN_CHARS = 2` |
| 别名解析 | `find_assets_by_theme("年龄段")` → `resolve_theme_tag` → `人群` → people.png |

别名必须解析：`asset_tags.tag` 存的是**规范标签**，别名只活在
`tag_vocabulary.aliases` 里。拿「年龄段」直接 `WHERE tag = ?` 会查空 ——
这一层是检索层的责任，不该推给调用方（修 bug 时踩到的正是这条）。

### 16.2 主题抽取：最长词面优先

`extract_theme(text, terms)` 扫一遍词表，取**命中最长的词面**；长度并列按词面
字典序，保证同一段稿子永远抽出同一个主题。

「分年龄段看，各年龄段消费者对取暖电器的偏好不同」同时命中「取暖电器」（4 字）
与「年龄段」（3 字）→ 取「取暖电器」。这不是拍脑袋定优先级，是「哪个词更长，
这段就更具体地在说它」。

### 16.3 决策树：theme → chart_semantic → None

用户 m06739 裁定（方案 1）：

1. 有主题 → 按主题（`semantic` 标签）查，取该档里第一个**没用过**的素材；
2. 该档的图本页已用 → **不报错、不硬塞第二张**，降级到按 `chart_semantic` 查；
3. 两者都查不到或都被占用 → 返回 `None`，这一段不配图，排版照走。

`Match.theme` / `Match.illustration_basis` 把「抽到什么主题」「这张图是按什么
配的」写进结果，`flow_summary()` 里 image 项带 `matched_by`。

### 16.4 演示实测（`out/demo/theme_match/`）

主稿 4 段、2 栏；两段正文都写「取暖电器」：

| 段落 | 抽到主题 | 图表 | 配图 | 按什么配 |
|---|---|---|---|---|
| 分品类看…环比增速… | 取暖电器 | thermometer | `illustration_17` `radiator_soft.png` | **theme** |
| 分年龄段看…占比… | 取暖电器 | semicircle | `illustration_26` `people.png` | **chart_semantic**（降级） |

两张图 `asset_id` 不同（17 / 26），正是裁定里要求的那条用例。像素指纹复核：
暖气片区主色 `(250,223,216)` = `radiator_soft.png`（alpha 0.2）叠白底的理论值；
人形区主色 `(96,120,190)` = `people.png` 的签名色 —— 换了图，肉眼也看得出。

反例 `_no_theme/`：稿子只提「加热电器」（不在主题词表里）→ 每段 `theme` 都是
`None`，插图回落到 `chart_semantic`（比较大小 → 同样是暖气片），证明降级路径可用。

### 16.5 改动面与验收

| 文件 | 改动 |
|---|---|
| `loop/asset_lookup.py` | 新增 `find_assets_by_theme` / `resolve_theme_tag` / `semantic_theme_terms` |
| `loop/compose.py` | `THEME_MIN_CHARS` / `load_theme_terms` / `extract_theme` / `_pick_illustration` 决策树 / `Match.theme` / `Match.illustration_basis` / `ComposeResult.themes` |
| `tests/test_step30_theme_match.py` | 新增 37 用例 |
| `tests/test_step29_illustration.py` | 跟随签名与「两条检索路径」更新 4 处 |

| 闸口 | 结果 |
|---|---|
| 提「取暖电器」时配暖气片而非 people/percent | ✅ `asset_id=17`，`tag=取暖电器`，用例显式断言不是 26/27 |
| 不含主题词时降级正确 | ✅ `_no_theme/` 与测试都验了 |
| 同一页两段同主题，第二段降级且 asset_id 不同 | ✅ 用户 m06739 要求的用例 |
| 排版结构不变（分栏/跨栏/等高保持） | ✅ 标题仍跨整宽、正文仍分 2 栏、卡与图仍同行；两两不重叠、全在边距内 |
| 全量 639+ 全绿、不改单卡模块 | ✅ **676 tests OK**（639 → 676） |

### 16.6 未做

* 不做真正的 NLP（不调 LLM、不引依赖）：只做词面命中，不消歧、不做词性。
* 主题只用于**选插图**，不参与「这段配哪组数据」的判定（那是选型器的事）。
* 一段只配一个主题：命中多个词面时取最长的，不做多主题加权。
* 拼音/近义改写未覆盖（「暖气」在别名里，「暖器」不在）。
