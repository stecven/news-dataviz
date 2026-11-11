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
