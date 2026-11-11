# SDD ledger — plan: docs/superpowers/specs/2026-11-07-charticulator-landing-design.md (implementation)

## Identity
- User m01073: implement that spec following D.2 order. Three hard requirements:
  ① only thermometer + semicircle (other 4 chart types NOT implemented);
  ② split D.2 steps 1→6, each step writes tests first then implementation, never all tests at once;
  ③ E.3 four assertions + three failure paths (n=20 raises SolveError, Σv=0 raises, no-solution writes no file) must land as unittest, all green.
  Constraints: no new dependencies, DO NOT change loop/render.py, DO NOT touch db.
- No .git repository (confirmed in earlier rounds) → no commit steps, no task-start/task-done scripts (they need git). Manual ledger + todos only.

## Rulings
- Ruling: D.2 table has exactly 5 numbered steps; user says "1→6". Interpret as 6 increments by splitting D.2 step 3 (solve) into 3a preprocessing constants and 3b linear solve/geometry, and splitting 3b across thermometer (inc 4) and semicircle (inc 5). — why: preserves D.2 order and honors "每步先写测试" without inventing a nonexistent step 6. — cost if wrong: user meant a different 6-way split; the sequence still covers every D.2 step.
- Ruling: C.2 lists semicircle constraints C1,C2,C3,C5,C7,C8, but E.3 #3 (user-mandated unittest) requires semicircle to reuse thermometer's C1/C4/C5 primitives. Include C4/C5 in the semicircle template (used for legend/center-text layout) so E.3 #3 holds. — why: E.3 is explicitly named by the user as a required assertion. — cost if wrong: semicircle constraint set is a superset of C.2's literal list.
- Ruling: label width = 1.0 in (was 1.6 in the write-hardcoded spec) so C1 bounds hold with d=2.125 at m=0.5, W=10. Old x_track=0.8+i*1.8, new solved x_track=0.5+i*2.125; no existing test asserts absolute x/y. — why: with w_label=1.6 and d=2.125 the centered labels would overflow x<0 and x>W, violating C1. — cost if wrong: label boxes narrower than the original rendering (text may wrap earlier).
- Ruling: H_track preprocessing = min(params.H_track, H − top_reserve − (bulb_d/2 + gap_label + h_label + gap_value + h_value)) with y_track = top_reserve + margin. With defaults TOP_RESERVE=1.65 (m+h_title+g_title+h_note+g_note), BELOW_STACK=1.35 (bulb_d/2+g_label+h_label+g_value+h_value+bottom_margin) → H=6.0 gives 3.0 (keeps 31 legacy tests), H=4.0 gives 1.0 (E.3 #1 fit). min/max is computed as a constant in preprocessing, never inside the constraint matrix (C7 hard rule). — cost if wrong: H>6 caps track at 3.0 leaving extra vertical whitespace.
- Ruling: geometry_expr is an audit record of the declarative expression; the solver interprets the template's constraint rows, not the string. A dedicated test asserts solved values satisfy the declared liquid expression `h_in = scale.factor * binding.value`. — cost if wrong: expressions and rows could drift; the test catches the key one.

## Pre-flight
- Baseline `python -m unittest discover -s tests -t . -v` → Ran 31 tests in 1.012s OK.
- Python: bundled 3.12.14 + python-pptx 1.0.2 + Pillow 12.3.0; run with `$env:PYTHONIOENCODING='utf-8'; $env:PYTHONPATH='.'`.
- Sandbox: directories made by tempfile.mkdtemp() are unwritable; tests use tests/scratch.py mkdtemp (os.makedirs + uuid). Directories pre-existing or made by os.makedirs() are writable.
- DB SHA-256 constant BBB8B2DFFBE772B03B9F33749B8AD583BA64269F7A55F26D5EF5E666FE2990B0 unchanged; load_points() stays read-only.

## Increments
- Incr 1 (D.2-1): models optional fields + backward compat; load_points unchanged. — complete (RED 7 errors → GREEN 7 ok; full suite 38 tests OK / PYTHON_EXIT=0). Files: loop/models.py (Scale.factor/domain, ElementSpec.geometry_expr/geometry, PageSpec.constraints/layout with defaults), tests/test_step1_models.py (7 tests incr old pagespec.json backward compat).
- Incr 2 (D.2-2): TemplateSpec registry, 2 coordinate-free templates, 4 placeholders. — complete (RED 13 ImportError → GREEN 13 ok; full suite 51 tests OK). Files: loop/templates.py (TemplateSpec dataclass w/ 5 sections, TEMPLATES registry 2 implemented + 4 placeholders raising NotImplementedError, export_template/export_template_file), tests/test_step2_templates.py (13 tests). All marks x/y/w/h are "@param" string refs; no absolute coord literals; C9 excluded; semicircle declares C1/C4/C5 reuse.
- Incr 3 (D.2-3a): preprocess constants + SolveError (n=20 C1+C6, Σv=0). — complete (RED ModuleNotFoundError → first GREEN attempt exposed 4 KeyError('w_track') + 1 float 2.9999999999999996!=3.0; fixed with template-neutral param defaults + C6/H_track gated to thermometer + assertAlmostEqual; GREEN 22 ok; full suite 73 tests OK / PYTHON_EXIT=0). Files: loop/solve.py (SolveError with .conflicts, preprocess() returning W/H/m/n/v_max/sum_v/d/R/H_track/factor/arc_total/p), loop/templates.py (top_reserve 1.2→1.65), tests/test_step3_preprocess.py (22 tests). Failure paths 1 (n=20/n=19 → C1+C6) and 2 (Σv=0 / Σv<0 / nan → C2) now unittest-covered.
- Incr 4 (D.2-3b thermometer): Gaussian solve_linear + solved geometry + build_pagespec retrofit + read_shapes coordinates. — complete (RED ImportError: cannot import name 'solve_linear' → GREEN 23 ok; full suite 96 tests OK / PYTHON_EXIT=0). Files: loop/solve.py rewritten (solve_linear Gauss-Jordan w/ partial pivot + singular/rectangular→SolveError, _resolve/_make_element, build_skeleton coordinate-free x/y/w/h=0, _solve_thermometer C1-C6 with n×n linear system for C6, _SOLVERS dispatch, solve()), loop/scaffold.py build_pagespec() retrofit (new kwargs width_in/height_in/template_name/param_overrides; delegates to build_skeleton+solve), loop/verify.py read_shapes() +left/top/width int keys. E.3 #1 (H=6→4, n=20 C1+C6, PPTX 27 shapes in 10×4) and E.3 #3 thermometer half now unittest-covered. Hand-derived constants: d=2.125, x_track=[0.5,2.625,4.75,6.875,9.0], y_title=0.5/y_note=1.15/y_track=1.65/y_bulb=4.30/y_label=5.10/y_value=5.45.
- Incr 5 (D.2-3b semicircle): semicircle solve + render_arc adapter + E.3 #2/#3/#4. — complete (RED 22 errors + 1 failure `SolveError: no solver registered for template semicircle` → GREEN 24 ok; full suite 120 tests OK / PYTHON_EXIT=0). Files: loop/solve.py (+_GLOBAL_ROLES={title,scale_note,center} so center is one global mark, build_skeleton semicircle scale_note + center_text live-normalized by center_slice_id, _solve_semicircle C1/C2/C3/C4/C5/C7/C8, _SOLVERS dispatch), loop/templates.py (+gap_center/gap_legend params), loop/render_arc.py NEW (render_pptx_arc: PIE AUTO_SHAPE w/ start/end angle in adjustments, needs_arc_renderer), loop/verify.py read_shapes +auto_shape_type/adjustments, loop/preview.py arc→pieslice, loop/build_loop.py render_from_spec dispatch + --template CLI. Probe scripts/_probe_arc.py confirmed PIE adjustments=[start,end] degrees, readback 5-decimal precision (tests allow delta=1e-3); render.py UNCHANGED. Ruling: legend stack lower bound uses bottom_margin (0.25) not m (0.5), because C7's R=(H−2m)/2 makes pie bottom = H−m and legend sits at different x. Hand-derived: Σv=22, factor=180/22, bounds 180/261.81818/286.36363/310.90909/335.45454/360, center 45.5%/32.3%/20.0%, R 2.5→1.5 on H=6→4.
- Incr 6 (D.2-4/5): atomic write + failure path 3 + read-back validation + final suite. — complete (RED `ImportError: cannot import name 'write_pagespec_atomic'` → GREEN 11 ok; full suite 131 tests OK / EXIT=0). Files: `loop/build_loop.py` +`write_pagespec_atomic(path,doc)`(先写 `.tmp` 再 `os.replace`；序列化失败清 `.tmp` 且不破坏已有文件)、`build_loop(...,param_overrides=None)` 先 solve 再原子写、读回后 `validate_spec` 再渲染；`loop/solve.py` +`validate_spec(spec)`(C1 越界 + DATA/C2 `h_in=scale.factor*binding.value` 一致性；幂等不改坐标；半圆扇角走 geometry 不误判)。`tests/test_step6_atomic_and_readback.py` 11 测试含失败路径3「无解不落盘且不覆盖已有 pagespec」。修掉测试自身 `open(p,'rb').read()` 的 ResourceWarning（`_read_bytes` helper）。

## 目视复核发现并修复的缺陷（z-order，Incr 5 之后）
- `out/semi_check/preview.png` 经 vision_describe 发现半圆中心 `45.5%` 与量程说明被扇区 PIE 楔形（bbox 覆盖 250..750×50..350）盖住；像素探针 `centernote_band_dark=0`、`center_band_dark=0`。根因：`build_skeleton` 先出全局 text 再出逐点 sector，两个渲染器按规格顺序绘制 → 后画的色块盖字。
- TDD 补 `tests/test_step5_solve_semicircle.py::TestSemicircleTextOnTop` 4 测试（RED 2 failures + 1 error `ImportError: _render_order` → GREEN 4 ok）。修复：`loop/preview.py` +`_render_order(spec)`(shapes+texts，文字后置)、`loop/render_arc.py` 循环改 `for el in _render_order(spec)`；**规格 / 求解器 / loop/render.py 均不动**。
- 像素复核 dark 0→535(量程) / 0→65(中心)；vision_describe 确认量程说明与 `45.5%` 清晰、无遮挡。

## 测试-产物耦合修正
- `tests/test_step1_models.py::test_old_pagespec_json_still_loads_with_defaults` 原本读 `out/loop1/pagespec.json` 断言无 `constraints`；该文件被后续步骤重生成成新格式后断言失败（135 tests 中唯一失败）。改为把旧格式钉成模块内固定样本 `_OLD_FORMAT_DOC`，不再依赖会被覆盖的产物文件。

## 最终验证
- `Ran 135 tests OK` / `TEST_EXIT=0`；`DB_SHA=BBB8B2DFFBE772B03B9F33749B8AD583BA64269F7A55F26D5EF5E666FE2990B0`(未变)；`loop/render.py` 内容核对为原始 60 行渲染器、无 arc 逻辑、未改；CLI `--out out/loop1` 与 `--template semicircle` 各 exit 0 产出 3 文件；`scripts/_probe*` 残留 0、`out/semi_*` 已清。
- E.3 四条断言与三条失败路径 census 全部有 unittest：#1(H=4/n=20：test_step4 `test_height_4_*`×3 + `test_n20_raises_solveerror_on_build_pagespec`) / #2(override 12.0：test_e2e `test_vmax_11_to_14...` + test_step5 `test_override_1_12_recomputes_factor_and_all_angles`) / #3(模板无坐标字面量 + 同模板 constraints 相同 x_in 不同：test_step2 + test_step4/5) / #4(中心实时归一不写死 80%：test_step5 `TestE3Assertion4Center` 4 条)；n=20(test_step3/4/5) / Σv=0(test_step3/5) / 无解不落盘(test_step6)。
- `out/scratch/probeB-332875b7-9vfsc85i/` 空目录为首个探针遗留、沙箱 ACL 拒删（按 diagnose-windows-sandbox-acl 不修权限，无害）。

## 审查修复轮（FRESH REVIEW: Needs fixes → 已修，160 tests 全绿）
- 审查者 `c5faa74d-d633-47ed-9ad2-4527d961ac36` 结论 Needs fixes：无 Critical，三条 Important。我用独立只读探针 `scripts/_verify_review.py` 逐条复核，均属实（不做事先认同）。
- **Important 1（声明式约束惰性）**：原 solve() 仅按 `template.name` 分派硬编码 handler，`validate_spec` 只查 `"scale.factor"` 子串。修复取审查者建议的「至少」路线：① `loop/solve.py` 新增 `_check_constraint_declarations(spec, template)`，`solve()` 与 `validate_spec()` 都先校验声明集完整（删行 / 未知 id 均抛 SolveError）→ 改声明**真的**改变行为；② `validate_spec()` 重写为逐行分派 `_CONSTRAINT_CHECKERS`（C1/DATA/C3/C4/C5/C6/C7/C8），从已求解几何**重新推导**每条声明约束（含半圆 Σθ 闭合、C6 d 等距、C7 R、C5 居中、C4 竖直相邻）；③ `geometry_expr` 也承重（扇区必须含 `theta_i`、中心必须含 `sum(v)`、液柱必须含 `scale.factor`）；④ checker 抛 `KeyError/TypeError/ValueError` 包装成 `SolveError(...,[id])`，缺字段不漏原始异常。**未**把几何改成完全由约束行驱动（那是一次大重写，超出本子集；台账此前 "solver interprets the template's constraint rows" 的措辞已由上述 ①②③ 变为**可验证为真**）。
- **Important 2（半圆读回校验漏 DATA 链接）**：原门控 `"scale.factor" in e.geometry_expr` 对半圆 sector 恒假。修复：`_chk_DATA` 新增半圆分支，重算 θ_i==factor×v_i、Σv、中心 `percent/sum_v/v_center/text` 全等于实时归一值。探针复核：篡改 `sector_1.geometry["theta"]=999` 现被拒（conflicts DATA,C2）。
- **Important 3（布局 override 与竖直堆叠脱节 → 伪 C1）**：原 `preprocess` 用存储字面量 `top_reserve` 算 `H_track`，`_solve_thermometer` 用另一套分量和算 `y_track`。修复：`top_reserve` 改由 `m+h_title+gap_title+h_note+gap_note` 派生、写回 `p["top_reserve"]`，两阶段与 `_solve_semicircle` 共用；显式覆盖 `top_reserve` 直接拒绝（提示改分量，conflicts C4）。探针复核：`gap_title=0.3` → H_track=2.85/y_track=1.8；`gap_title=0.6` → 2.55/2.1 均无伪 C1。
- **Minor 一并修**：① 半圆单负值 `[10,3,-1,3,3]` 原产 θ=-10（非法 PIE），现 `SolveError(...,["C2"])`；② 半圆 `Scale` 语义错乱（h_in=0.0、domain=[0,11]）改为 `h_in=arc_total(180)`、`unit="deg"`、`domain=[0,180]`，注释说明 factor 单位 deg/value 与温度计 in/value 的区别；③ 半圆 `not_applicable_when` 点明「>5 换图 / fallback_used 属 GoalExplorer 职责，本子集未实现、仅声明不强制」；④ 两条 change-detector 测试加手算/结构字面量锚点（`liquid.h_in==3v/11`、constraints id 集合）。
- **半圆标题压扇区（本轮目视新发现，同类缺陷）**：`_solve_semicircle` 原 `y_pie=m`、C7 `R=min((W−2m)/2,(H−2m)/2)` 未预留 `top_reserve`。修复：`R=min((W−2m)/2,(H−top_reserve−bottom_margin)/2)`、`y_pie=top_reserve`、`cy=top_reserve+R`；`top_reserve`/`bottom_margin` 写入 `layout` 供 `_chk_C7` 独立复算；设计文档 C7 行同步更新。H=6 时 R 2.5→2.05（10×4 时 1.5→1.05），中心盒 y 2.6→3.3。目视复核：标题 / 量程说明不再被扇区覆盖。
- 新增 `tests/test_step7_review_fixes.py` 26 测试（5 组），RED 首跑 `FAILED (failures=33, errors=1)` → GREEN。
- **自查又发现并修掉一个自指漏洞**：`_chk_C6` 原用 `_by_id(spec,"title").x_in` 当 margin、`_chk_C4` 半圆分支只比相邻间距——整体平移整份规格时 title 跟着动、图例同距，二者都会静默通过（探针实测「thermo whole shift +0.2 → ACCEPTED」）。修复：`_chk_C6` 的 margin 改取 `ctx["m"]`（= `layout.margin`）；`_chk_C4` 半圆分支锚定 `legend_1.y_in == layout.top_reserve`。复核：「thermo whole shift +0.2 → REJECTED [C6]」「semi whole shift down +0.2 → REJECTED [C4]」，并加 `test_whole_spec_shifted_right_is_rejected_not_self_referential`。
- 说明：对 track/bulb/label/value 剥掉 `geometry`/`binding` 仍 ACCEPTED 属**正确**行为——这些图元本就不承载数据链接（只有 liquid / 半圆 sector / center 有）。
- **最终验证：`Ran 175 tests OK` / EXIT=0**（多次复跑一致）；`DB_SHA` 仍 `BBB8B2DF...990B0`；`loop/render.py` 零 arc/PIE 命中、未改；无新依赖。产物重生成 exit 0：`out/loop1`(29204/11461/22850)、`out/semicircle`(29062/9018/26989)、`out/loop1_override`(29205/11461/22874)。

## 复审第二轮（FOCUSED RE-REVIEW: Needs fixes → 已修，175 tests 全绿）
- 审查者 `ababc2da-4025-42cb-a408-6f5f228b18c2` 判定：claim 1 FIXED、2 **PARTIAL**、3 FIXED、4 FIXED、5 求解正确但读回无防线、6/7 PASS；另报 7 条 Important + 7 条 Minor。我逐条用探针复现，全部属实。
- 新建 `tests/test_step8_readback_hardening.py`（14 测试，5 组：TestC6SpacingFormula / TestArcTotalClosure / TestLegendPitchAndTopReserve / TestMalformedSpecs / TestElementCountIntegrity），RED `FAILED (failures=8, errors=3)` → GREEN。
- `loop/solve.py` 加固：
  - **I1** `_chk_C6` 改为按声明重新推导 `d = max(gap_min, (W−2m−w_track)/(n−1))` 并逐根比对 `x_i == m + i·d`（原只查等距+首柱在 margin，挤到 pitch=0.01 会通过）。探针：pitch 0.01 → REJECTED [C6]；margin=0.6+整体平移 → REJECTED [C6]。
  - **I2** `_chk_C3` 半圆分支加 `Σθ == arc_total` 与 `scale.h_in == arc_total`（原 Σθ=90 通过）。探针：factor 减半 → REJECTED [C3]；h_in=999 → REJECTED [C3]。
  - **I3** `_chk_C4` 半圆分支把图例 y 绑定 `top0 + i*(h_legend+gap_legend)` 且校验 `h_in == h_legend`（原只查彼此间距相等）。evidence：pitch 0.15 → REJECTED [C4]。
  - **I4** `_chk_C4` 断言 `sector.y_in >= top_reserve`；`_chk_C7` 从 `m+h_title+gap_title+h_note+gap_note` **重新推导** top_reserve 并与 `layout.top_reserve` 比对（原自报自证）。探针：top_reserve=0.6 → REJECTED [C7]；sector y=0.5 → REJECTED [C4]。
  - **I5** `_check_constraint_declarations` 先验证每行是带 `"id"` 的 dict；`validate_spec` 先查 `spec.scale is None`。（原 `constraints=["C1"]` → 原始 AttributeError，`scale=None` → AttributeError。）
  - **I6** `SolveError.__init__` 把非 str 冲突 id 转 `repr()`，`__str__` 不再抛 TypeError。
  - **I7** 新增 `_check_element_integrity(spec, template)`：各 role 的 seq 后缀集合必须完全相同（原 `zip` 截断使删 `bulb_5`/`legend_5` 静默关闭检查）；并断言数据图元必须有 binding。
  - **M1** 在 `_chk_DATA` 注释里说明温度计 v≤0 钳 0 与半圆拒负值的**有意非对称**及理由。
  - **M3** `loop/templates.py` 修正声明漂移：C8 由 `alpha_0 = 0` 改为 `alpha_0 = 180 (半圆定义)` 并补 `sum(theta) = arc_total`；C7 声明改为含 `top_reserve`/`bottom_margin` 的真实公式。
- 修错一次：`_chk_C4`/`_chk_C6` 起初读 `ctx["params"]` 误传成模板参数 schema（值是 `{default,unit,desc}` dict）→ 21 errors `float() argument must be ... not 'dict'`；改为 `_defaults(template)` 叠加 `layout.param_overrides`。
- **最终验证：`Ran 175 tests OK` / EXIT=0**；`DB_SHA` 仍 `BBB8B2DF...990B0`；`loop/render.py` 零 arc/PIE 命中；无新依赖；三个产物目录均 exit 0。

## 报纸原版改版：0 点移到球泡顶点（用户 m02007，175 tests 全绿）
- 用户指令原文：「不需要考虑负数，然后做成这样的图，0点为圆最上方的顶点」，附《经济日报》原版区块③截图（细管 + 球泡 + 刻度 + 类别名在管上方 + 数值在球下方）。
- `loop/templates.py` `_THERMO_PARAMS` 改为报纸原版尺寸：`w_track 0.5→0.28`、`bulb_d 0.7→0.52`、`h_label 0.3→0.34`、`h_value 0.3→0.18`、`gap_label 0.1→0.03`、`gap_value 0.05→0.03`、`w_label 1.0→1.2`、`color_track 新增 "FFFFFF"`、`color_liquid` 改暖珊瑚 `"E8A08C"`、新增 `color_tick "C9C9C9"`。`H_track` 保持 3.0（k=3/11 不变）。
- 竖向模型重定义（`loop/solve.py`）：`below_stack = h_label+gap_label+bulb_d+gap_value+h_value+bottom_margin = 1.35`；`_solve_thermometer` 内 `y_label = y_note+h_note+gap_note`(1.65)、`0 点 y_bulb_top = y_label+h_label+gap_label+H_track`(5.02)、`y_track = y_bulb_top−H_track`(2.02)、`y_bulb = y_bulb_top`、`y_value = y_bulb_top+bulb_d+gap_value`(5.57)、液柱 `y = y_bulb_top − h`。
- `_chk_C4` 温度计分支改为报纸口径：`b.y_in == t.y_in+t.h_in`（球顶=0 点，原 `b.y_in+b.h_in/2 == bottom` 是旧中心对齐）、`la.y_in+la.h_in <= t.y_in`（标签在管上方）、`va.y_in >= b.y_in+b.h_in`（真值在球下）；错误串含 `(0 point)`。同时删掉文件里重复定义的旧 `_chk_C4`（654-681 行窄版，后者覆盖前者）。
- 水平 pitch 因细管由 `2.125 → 2.18`（W=12 时 3.125→3.18），6 行时 1.744。
- 测试同步（手算字面量）：`test_step3_preprocess` 的 d 2.18/1.744；`test_step4_solve_thermometer` 的 C6 序列 `[0.5,2.68,4.86,7.04,9.22]`、C4 竖向 `label 1.65/track 2.02/bulb 5.02/value 5.57`、液柱底 5.02、C5 偏移 `−0.12/−0.46`、H=4 pitch 2.18、W=12 的 3.18；`test_step7_review_fixes` 的 `gap_title=0.3 → track y 2.17`、`gap_title=0.6 → track y 2.47`；两条「整体平移必须被拒」的用例把位移由 0.2 改 0.02（0.2 会让 `label_5` 右缘 10.04 越界，先触发 C1 而非 C6，测不到要测的东西）。
- `tests/test_render.py::test_preview_png_is_nonblank` 的像素断言由「红像素」改「液柱色 E8A08C 附近像素 >1000」（原断言 `r>140 and g<110` 对暖珊瑚不适合，改色后 0 命中）。
- **验证：`Ran 175 tests OK`**；产物 `out/thermo_new`（loop1.pptx 29246 / pagespec.json 11621 / preview.png 22648）exit 0，`read_shapes` 回读 27 形状与 spec 一致；预览目视确认：类别名在管上方、液柱从球顶向上长、真值在球下。
- 文档同步：设计文档 C4 行改为报纸口径公式；E.3 #1 的 `d=2.125` 改 `2.18`；E.4 新增 **L4 管内刻度线未渲染**（刻度是非数据驱动装饰图元，需改 `render.py`，本子集明确不改）。

## 液柱改细杆（原版形态对齐，用户对比图反馈，201 tests 全绿）
- 触发：用户给出原版/复刻并排对比图（左：细杆液柱 + 胖球；右：满管宽液柱 + 小球）。像素实测原版第一支：管外轮廓 x 490..518（28px）、液柱 x 500..511（10-12px，约管宽 36%）、球泡最宽 109px（含外环）、刻度短线在液柱右侧。
- 改动（不动 bulb_d，避免连锁 5 个测试文件的竖向常量）：
  - loop/templates.py 新增参数 liquid_w = _p(0.10, "in", ...)；w_track 描述去掉「/ 液柱」。
  - _THERMO_MARKS 的 liquid 改为 ("@x_liquid","@y_liquid","@liquid_w","@h_liquid")，geometry_expr 增写 w_in = liquid_w; x_in = x_track + (w_track - liquid_w) / 2。
  - loop/solve.py preprocess() 加 p.setdefault("liquid_w", 0.0)；_solve_thermometer() 读 liquid_w，液柱改为 x + (w_track - liquid_w) / 2 与 w_in = liquid_w（高度与底边不变）。
  - _chk_C5 温度计分支 role 循环由 ("bulb","label","value") 扩为 ("liquid","bulb","label","value")：细杆必须居中，否则与右侧刻度错位。
- 测试：tests/test_step9_thermometer_skin.py 新增 TestLiquidRod（5 用例，RED 8 failures -> GREEN）：参数存在、mark 用 @liquid_w/@x_liquid、细杆居中（x = x_track + 0.09）、细杆在管内且高度仍 factor*v、偏心 0.02 被 C5 拒。
- 验证：Ran 201 tests in 2.489s OK / EXIT=0；产物 out/paper_c3/（preview.png 25894）与 out/skin1/ 均 exit 0；像素实测复刻液柱宽 9px、管宽约 28px，比值 0.32，与原版 0.36 同量级。
- 对比图 out/cmp_rod2.png（330x420，同像素尺度）。剩余可见差：原版球泡相对管身更胖（109/28 ~ 3.9 含外环），复刻 0.52/0.28 ~ 1.86；未改动，因 bulb_d 会抬高 below_stack 并在 H=6 时挤压 H_track，牵动全部 3.0/5.02 竖向锚点。
- 文档：设计文档 C.2 温度计行改「液柱细杆 rect」；C.5 行补 x_liq + liquid_w/2 = x_track + w_track/2。

## 半圆图补完 + 两类图形共用性验证（用户 m03184）

**范围**：只做扇区角度 / 中心数值 / Σθ=180° 闭合；图例、配色、标签避让（C9）不做。

### 生产代码改动
1. `loop/templates.py` `_SEMI_PARAMS` 新增 `max_slices = _p(5, "count", ...)`。
2. `loop/solve.py` `preprocess()` 新增容量哨兵：
   `if is_semicircle: max_slices = int(p["max_slices"]); if n > max_slices: raise SolveError(f"n={n} exceeds max_slices={max_slices}: ...", ["MAX_SLICES"])`
3. `loop/solve.py` 抽两个共用 helper（消除两个求解器间的复制粘贴）：
   - `_place_header(sk, pre) -> (y_title, y_note)`：标题 / 量程说明两条全局 mark 的回填（原温度计 8 行 + 半圆 8 行逐字相同）。
   - `_check_canvas_bounds(sk, W, H)`：C1 越界检查（原两个求解器各有一份 5 行循环，`out of canvas` 文案也各有一份）。
   两个求解器末尾改为 `_check_canvas_bounds(sk, W, H)`，`_solve_thermometer` 用 `by = {...}` 前置 + `_place_header`。

### 测试
- 新增 `tests/test_step10_semicircle_acceptance.py`（25 用例 / 8 个 TestCase）：四组数据 + 6 项 fallback + 共用性 + 读回。
- 改 `tests/test_step5_solve_semicircle.py::test_n20_legend_overflow_raises_solveerror_not_clipped`：加 `param_overrides={"max_slices": 20}`，让 20 项先过容量哨兵，继续测「图例堆叠溢出 → C1」这条原路径。

### 四组 + 6 项 关键数字（`out/demo/semicircle/summary.json`）
| 组 | 数据 | Σθ | θ_i | 中心 | θ/v 恒定 |
|---|---|---|---|---|---|
| g1_original | DB heat_age 0.08/0.32/0.32/0.17/0.11 | 180.0 | 14.4 / 57.6 / 57.6 / 30.6 / 19.8 | 8.0% | ✓ (180.0) |
| g2_equal | 5/5/5/5/5 | 180.0 | 36 × 5 | 20.0% | ✓ (7.2) |
| g3_peak | 100/1/1/1/1 | 180.00000000000003 | 173.076923 / 1.730769 ×4 | 96.2% | ✓ (1.730769) |
| g4_zero | 10/0/3/2/1 | 180.0 | 112.5 / 0.0 / 33.75 / 22.5 / 11.25 | 62.5% | ✓ (11.25，零项 N/A) |
| g5_six | 10/3/2/2/2/1 | — | 被拒 | — | conflicts=["MAX_SLICES"]，未落盘 |

- 零值扇区 `theta == 0.0` 且 `start == end`，后续边界不位移（180/292.5/292.5/326.25/348.75/360）。
- 极值组最小扇区 = `180×1/104 = 1.730769°`，`< 2°`，未被任何「最小可见角度」兜底抬高。
- g3 的 Σθ 浮点尾差 3e-14，`assertAlmostEqual(places=9)` 通过；未做任何四舍五入。

### 共用性怎么验证的
1. `loop.solve.solve()` 是唯一入口；测试用 spy 替换 `S.preprocess`，确认两种模板都经过它。
2. `_SEMI_CONSTRAINTS` / `_THERMO_CONSTRAINTS` 的 `C1` / `C3` / `DATA` 是**同一个 dict 对象**（`assertIs`）；`C5` kind+expr 相同，半圆只是加了 `reuse_from_thermometer` 标记。
3. `inspect.getsource` 断言两个求解器都调用 `_place_header(` 与 `_check_canvas_bounds(`，且求解器源码内不再出现 `"out of canvas"` 文案——该文案只存在于 `_check_canvas_bounds` 内（证明复制粘贴已收敛为一份）。
4. 两者产出同为 `PageSpec` / `Scale` / `ElementSpec`，无半圆专用规格类。

### 老产物
`out/loop1/pagespec.json`：可 `PageSpec.from_dict` 读回（27 元素）、可 `render_pptx` 渲染（27 形状）。但**不通过** `validate_spec`——它是 12:09 的「球心对齐管底」旧 C4 口径产物，被当前 C4（球顶=0 点）以 `bulb_1 top != track_1 bottom (0 point)` 拒绝。已按此口径写测试，并记入设计文档 E.4 **L6**（历史产物不保证通过最新校验，不改校验器迁就老数据）。

### 验证
- `python -m unittest discover -s tests -q` → **Ran 226 tests OK / EXIT=0**。
- `db/assets.db` SHA-256 仍 `BBB8B2DFFBE772B03B9F33749B8AD583BA64269F7A55F26D5EF5E666FE2990B0`。
- `loop/render.py` 60 行未改，仍无 arc/PIE/ticks/outline 分支。
- 产物：`out/demo/semicircle/g1_original|g2_equal|g3_peak|g4_zero/`（pagespec.json + preview.png）、`g5_six_fallback/fallback.txt`、`summary.json`。

## 选型器第一版（用户 m03467，257 tests 全绿）

范围：只做 {温度计, 半圆图} 二选一；规则写死、不接 LLM、不碰素材库、不做整版、不改图形实现。

两处规则冲突已向用户提问并按裁定实现（方案 1）：
- 冲突 1「全相等 + 占比 + n≤5」：把「全相等」提为高于「占比」的否决条件，规则 2 增「非全相等」前提。
- 冲突 2「含零值 + 占比」：拆成 5a（全相等一律温度计，不论语义）/ 5b（含零值不改变语义选型结果，仅 rationale 点名零值退化扇区）。

新增文件：
- `loop/selector.py`（160 行）：`SEMANTIC_SHARE/COMPARE/OTHER`、`SelectorError`、`_semicircle_max_slices()`（从 `templates.get_template("semicircle").params` 读，缺失即抛，绝不默认 5）、`features_from_points(points, semantic)`、`select(features) -> {selected_template, rationale, rejected}`。不 import 渲染/求解模块、不写盘、不修改入参。
- `tests/test_step11_selector.py`（278 行 / 31 用例 / 10 TestCase）。

规则优先级（实现顺序，与文件 docstring 一致）：5a 全相等 → 4 含负值 → 1 n>max_slices → 2 占比 → 3 比较 → 6 其余无适用。

验证：`Ran 31 tests OK`；全量 `Ran 257 tests OK / EXIT=0`；`loop/render.py` 60 行未改；`loop/solve.py` 不含 "selector" 引用（未改）；`db/assets.db` SHA-256 仍 `BBB8B2DFFBE772B03B9F33749B8AD583BA64269F7A55F26D5EF5E666FE2990B0`；`out/loop1`、`out/paper_c3`、`out/skin1` 产物 mtime 未变。

## 选型器接入流水线（用户 m03536，281 tests 全绿）

范围：只做「接得上」——选型 → build_pagespec → 渲染。不改 selector / solve / render / db / schema，不调 LLM。

新增：
- `loop/pipeline.py`：`run_selected(chart_key=... | values=..., semantic=..., chart_title=..., out_root=..., group_name=...)`，返回 `{status, selected_template, rationale, rejected, semantic, out_dir, selection, pagespec, preview, pptx, message}`。内部 `features_from_points` → `selector.select` → `build_pagespec` → `write_pagespec_atomic` → `PageSpec.from_dict` + `validate_spec` → `render_from_spec`。`selected_template is None` 时短路返回 `status="no_applicable"`，不落 pagespec、不出图。
- `loop/pipeline.py::INTERFACE_MAP`：4 行接口对照表（代码即表，测试逐行校验）。
- `tests/test_step12_pipeline.py`：24 用例 / 7 TestCase。

三件事实测结果：
- `heat_ratio_top5`（语义=比较大小）→ thermometer，37 元素，`out/demo/pipeline/heat_ratio_top5/`（pagespec.json 19384 / preview.png 24255 / loop1.pptx 30952 / selection.json）。
- `heat_age`（语义=占比构成，5 项）→ semicircle，13 元素，Σθ=180.0，`out/demo/pipeline/heat_age/`（pagespec.json 8915 / preview.png 26923 / loop1.pptx 29045 / selection.json）。
- `[10,3,2,2,2,1]` 占比 6 项 → `status=no_applicable`、`selected_template=None`、目录内只有 selection.json（无 pagespec/preview/pptx），message 含 `fallback_used` 与 `6`。

接口对照表（selector 输出 → build_pagespec 输入）：
| selector 字段 | 状态 | 落到哪 |
| selected_template | 直接可用 | `build_pagespec(template_name=...)`，字符串即 get_template 注册表键，无别名映射 |
| selected_template(None) | 需转换 | 流水线内 None 守卫短路；若直接传 None 会回落 GOAL_STUB.chart_type=thermometer = 静默兜底 |
| rationale | 缺失 | build_pagespec 无此入参、PageSpec 无此字段 → 旁挂 selection.json |
| rejected | 缺失 | PageSpec 无承载字段 → 旁挂 selection.json |

验证：`Ran 281 tests OK / EXIT=0`；`loop/render.py` 60 行、零 pipeline/selector 命中；`loop/solve.py` 零 selector/pipeline 引用；`loop/selector.py` 零 pipeline 引用（未改）；DB SHA-256 仍 `BBB8B2DFFBE772B03B9F33749B8AD583BA64269F7A55F26D5EF5E666FE2990B0`。

## 第五层 S1/S2：素材库语义层建表 + 词表（用户 m03673）

- 新增 `loop/asset_schema.py`：DDL 片段（三张新表 + assets 9 列 + 两个视图 + 一个触发器 + 两个索引）、52 条词表种子、9 条校验 SQL、`audit()`。
- 新增 `scripts/migrate_db.py`：幂等迁移（PRAGMA 判列 / sqlite_master 判对象 / 词表 diff），单事务 + 迁移后自检，失败整体回滚。`--dry-run` / `--audit`。
- 新增 `scripts/asset_coverage.py`：G4 覆盖率体检（只读）。
- 新增 `tests/test_step13_asset_schema.py`：52 用例（结构 / 词表 / P1 / 约束 / 缓存一致性 / 幂等 / 真库 / 覆盖率）。
- P1 用**视图**而非 CHECK：CHECK 不能跨表；触发器 `trg_page_image_no_chart_semantic` 只禁 chart_semantic 这一类，主题标签允许存在但不进 `v_search_assets`。
- 真库迁移：`db/assets.db.bak-preS1` 备份 → SHA `BBB8B2DF…990B0` → `B0FC78BD…C339E`；二次执行「无变更」且 SHA 不变；`test_models.py` 常量已同步。
- 9 项体检全 0 行；`asset_tags` 仍为空（本轮不打标）。
- G4 结论：已登记 3/6、含未登记文件 4/6。占比构成＝缺登记/缺标签（percent、people）；全相等、无适用＝真缺专门素材（等号类 / 占位图）。
- 设计文档补 §9。全量 333 tests OK / EXIT=0。

## 第五层 S5：fallback 占位图（2026-11-09，348 tests 全绿）

目标：选型器返回 `no_applicable` 时，版面上有中性占位图可查，而不是留白或崩溃。

### 先解决的冲突
S1/S2 的 `v_searchable_assets` 刻意排除 `status='placeholder'`（占位图不该进正常检索），
所以占位图走 `v_asset_search` **永远查不到**；而本轮闸口要求「用 `fallback_placeholder`
能命中」。两条检索目标互斥 → 用户裁定：**新开 `v_fallback_assets` 视图**，不放宽
`v_searchable_assets`（放宽等于让灰色方块污染「比较大小」的配图结果）。同时裁定
占位图**不挂 chart_semantic**，只打 `usage=fallback_placeholder`。

### 产物
| 文件 | 说明 |
|---|---|
| `assets/placeholders/placeholder_todo.png` | 虚线方框 + 三点，400×400 RGBA 中性灰 |
| `assets/placeholders/placeholder_chart.png` | 坐标轴 + 三根柱 |
| `scripts/make_placeholder.py` | PIL 绘制 + 登记，支持 `--dry-run`，幂等且自愈 local_path |
| `loop/asset_lookup.py` | `find_fallback_assets` / `find_assets_by_semantic` / `resolve_local_path`（只读） |
| `tests/test_step14_placeholder.py` | 15 用例 / 4 TestCase |

为什么放 `assets/placeholders/` 而不是 `assets/icons/`：`asset_coverage.py` 扫
`assets/icons/` 统计图标覆盖率，混进去会把「未登记图标」从 4 个变成 6 个，污染 G4 口径。

### 登记
id 23 / 24，`kind='placeholder'`、`status='placeholder'`、`style_token='flat'`、
`palette='neutral_grey'`、400×400、`alpha=1.0`、`license='self-drawn (PIL)'`；
`asset_tags` 各 1 条 `fallback_placeholder / usage / weight 1.0 / source manual`。

### 视图
`DDL_VIEW_FALLBACK`（`loop/asset_schema.py`）：从 `assets` 出发 JOIN `asset_tags` +
`tag_vocabulary`，`WHERE s.status='placeholder' AND t.tag='fallback_placeholder'
AND v.deprecated=0`，列含 `status`。迁移脚本的对象清单已登记该视图。

### 修的两个坑
1. `CREATE VIEW IF NOT EXISTS` **不会更新已存在视图的定义** —— 改了 DDL 却静默不生效。
   迁移脚本新增 `_view_matches(con, name, ddl)`（归一化 SQL 比对）+ `recreate_view`
   （先 `DROP VIEW IF EXISTS` 再建）。否则 v_fallback_assets 一直是旧定义（缺 status 列）。
2. `tests/test_step13_asset_schema.py` 两条 S1/S2 断言与新数据冲突：
   `test_real_db_still_has_eight_assets` 写死总数 8 → 改成 `WHERE kind <> 'placeholder'` 仍 8；
   `test_real_db_has_no_bulk_tagging_yet` 写死 asset_tags 0 行 → 改成
   `WHERE tag <> 'fallback_placeholder'` 仍 0。这样断言表达的是**意图**（原始素材没丢、
   没批量打标）而不是一个会随每次加素材失效的魔法数字。

### 验收
- 图片 2 张存在可读、RGBA 400×400、中性灰（三通道最大差 ≤ 40）
- `v_fallback_assets` 返回 2 行（id 23/24，`kind='placeholder'`、`status='placeholder'`）
- `v_asset_search` 里 `kind='placeholder'` 命中 **0** 行（P1 对 placeholder 生效）
- 「比较大小」检索结果里无占位图
- 端到端：`run_selected(values=[10,3,2,2,2,1], semantic='占比构成')` → `status='no_applicable'`
  / `selected_template=None` / `preview=None`，兜底查询命中 2 行且文件都在
- 幂等：`make_placeholder.py` 二次执行「新增 assets 0 行 / asset_tags 0 行」；
  `migrate_db.py` 二次执行「无变更」；DB SHA 连续两次相同
- `Ran 348 tests OK`；`migrate_db.py --audit` 9 项全 0 行
- `loop/selector.py` / `solve.py` / `render.py` / `pipeline.py` / `models.py` 零改动（`grep placeholder` 命中 0）

### DB SHA
`B0FC78BD…C339E` → `44A6C024EADB9F9DD0C687710CA08AE472BA1ADCB1C184F9823F4950A902EA56`，
`tests/test_models.py` 常量已同步。

### 未做（不在本轮）
批量打标（S4）、登记 4 个未登记图标基名（S3）、把占位图真正画进版面（需扩 PageSpec
或新增图元类型）、`chart_semantic → 主题` 的桥（S6）。

## 第五层 S3：补登记 4 个未登记图标基名（2026-11-09，370 tests 全绿）

范围：只把 `assets/icons/` 下已有文件、`assets` 表里没有的 4 个基名登记进表。不打标。

### 扫描
`assets/icons/` 共 19 个文件 / 11 个基名。已登记 7 个（只登了 `_soft` 变体，id 16–22）。
未登记 4 个：**droplet / people / percent / pin**（各只有 `x.png`，无 `_soft`；400×400
RGBA，alpha 峰值 255 = 原图）。

### 产物
| 文件 | 说明 |
|---|---|
| `scripts/register_icons.py` | 扫描 + 登记 + 空列回填，`--dry-run` / `--list`，幂等 |
| `tests/test_step15_register_icons.py` | 22 用例 / 7 TestCase |
| `scripts/asset_coverage.py` | 「已登记」口径修正（见下） |

### 登记结果
id 25 `local:droplet` / 26 `local:people` / 27 `local:percent` / 28 `local:pin`，
全部 `kind='icon'`、`status='待登记'`、`style_token='flat'`、`palette=NULL`、
`license=NULL`、400×400、`alpha=1.0`、`local_path='assets/icons/<base>.png'`。

`palette` 填 NULL 的理由（用户裁定）：现有 7 个 icon 全 NULL，词表没有色板维度；
S5 占位图的 `neutral_grey` 是专为占位图定义的，不能推广。

### 幂等（三层）
1. `url` 已存在 → 跳过整行，非空字段不覆盖；
2. 行存在但字段空 → 只补空列（`_fill_blanks`）；
3. 文件在磁盘、库里没有 → 插入。

实测：第一次 `新增 4 / 跳过 0`；第二次 `新增 0 / 跳过 4`。
`register_icons.py` + `make_placeholder.py` + `migrate_db.py` 连跑两遍，DB SHA 前后一致。

### 覆盖率口径修正
`asset_coverage.py` 的「已登记」原来只统计**文件名以 `_soft` 结尾**的图标，
S3 补登记的 4 个基名没有 `_soft`，登记了也不算 → 覆盖率数字不动。
**口径比事实窄，把已登记的报成未登记。**
用户裁定改为「`assets` 表 `kind='icon'` 的基名集合」（归并 `_soft`/`_flat`）。
键名同步：`registered_soft_icons`→`registered_icons`、`covered_soft`→`covered_registered`、
`missing_with_soft`→`missing_with_registered`。

S3 后：已登记 11 基名 = 磁盘 11 基名（未登记 0），覆盖率 **3/6 → 4/6**
（「占比构成」由 people + percent 补上），仍缺 **全相等** / **无适用**。

### 修的两条旧断言
`tests/test_step13_asset_schema.py`：
- `test_real_db_still_has_the_original_eight_assets` 之前用 `kind <> 'placeholder'` 计数，
  S3 加 4 个 icon 后变 12 ≠ 8 → 改为**直接钉 8 个 id（15–22）**，素材增减都不影响。
- 覆盖率三条断言从 `registered_soft_icons`/`covered_soft`/`missing_with_soft`
  改用新键与 11 / 4 的新值。
`tests/test_models.py`：DB SHA 常量再换。

### 验收
- 4 个基名各 1 行、无重复 url；能按 `kind='icon'` 从 `v_searchable_assets` 查到（11 行全 icon）
- `v_asset_search` 里 `placeholder` / `page_image` 命中均 0
- `asset_tags` 全表仍只有 2 条 `fallback_placeholder`
- `Ran 370 tests OK`；`loop/selector.py` / `solve.py` / `render.py` / `pipeline.py` / `models.py` sha256 与 S5 时相同

### DB SHA
`44A6C024…EA56` → `79E7F1A6FB3A9B095E95B0D10890DC386A260DE13FE46CC03DF23BE451217F41`

### 未做
批量打标（S4）、给 4 个新图标补 `_soft` 变体、`style_token` 细分、
占位图接线（S5 遗留）、`chart_semantic → 主题` 的桥（S6）。

## 第五层 S4：11 个 icon 批量打 asset_tags（用户 m04071，394 tests 全绿）

### 范围
- 只打 id 16–22（7 个 `_soft`）+ 25–28（S3 新登记），共 11 个 icon
- 不打 page_image（id 15，P1）、不动占位图（23/24）、不生成素材、不改表结构
- 不改 `selector.py` / `solve.py` / `render.py` / `pipeline.py` / `models.py`
- 不发明词表外的标签

### 产物
- 新增 `scripts/tag_assets.py`：`TAG_PLAN` 写死 11 个 id 的标签计划（85 条）；
  `EXPECTED_IDS` / `EXPECTED_URLS` 启动时核 id↔url，不符就 `SystemExit`；
  `verify_targets()` / `missing_vocabulary()` / `tag_type_drift()` 三道预检；
  `tag_assets(db_path, dry_run)` 幂等写入 + `_refresh_cache()` 回填缓存列；
  `report()` 只读打印；CLI `--dry-run` / `--report`
- 新增 `tests/test_step16_tag_assets.py`（24 用例 / 7 TestCase）
- 改 `loop/asset_lookup.py::find_assets_by_semantic`：SELECT 增加 `weight`，
  `ORDER BY weight DESC, asset_id`（否则权重写了没人读）

### 打标结果（85 条 / 11 个 icon）
| id | 文件 | 条数 | chart_semantic |
|---|---|---|---|
| 16 | leaf_soft | 6 | — |
| 17 | radiator_soft | 9 | 比较大小 1.0 |
| 18 | sock_soft | 9 | — |
| 19 | cup_soft | 6 | — |
| 20 | thermometer_soft | 11 | 比较大小 0.6、含负值 1.0 |
| 21 | snowflake_soft | 9 | 其他 1.0 |
| 22 | flame_soft | 9 | 比较大小 1.0、其他 1.0 |
| 25 | droplet | 6 | 其他 1.0 |
| 26 | people | 7 | 占比构成 1.0、比较大小 1.0 |
| 27 | percent | 6 | 占比构成 1.0 |
| 28 | pin | 7 | 其他 1.0 |

### 用户裁定的三个歧义
- cup_soft → 「热水」（不是「饮水」：图上冒热气，与取暖主题更贴）
- flame_soft → 「火焰 + 热量」（不打「加热」：那是动作，图标不表达动作）
- 打标后 `assets.status`：待登记 → 已标注

### 「比较大小」为什么 radiator 优先
温度计本身就是原版区块③的**图表本体**，拿它当配图会和图表撞车。
所以 radiator 权重 1.0（首选）、thermometer 权重 0.6（次选）。
权重只影响检索排序，不参与选型决策。

### 三个踩坑
1. `asset_tags.created_at` NOT NULL 且无默认值 → 显式 `datetime.now().isoformat(timespec="seconds")`
2. `asset_tags.source` CHECK 只允许 `manual`/`model`/`crawl` → 批次号不能塞进 source，复用 `manual`
3. 缓存列必须回填，且 `json.dumps` 要用 `separators=(",", ":")` 才与 sqlite
   `json_group_array` 输出字面一致（默认带空格 → `cache_semantic_mismatch` 永不平）

### 检索验证
- 比较大小 4 命中：radiator(1.0) → flame(1.0) → people(1.0) → **thermometer(0.6)**
- 占比构成 2 命中：people(1.0) → percent(1.0)
- 含负值 1 命中：thermometer(1.0)
- 其他 4 命中：snowflake / flame / droplet / pin
- **全相等 0 命中、无适用 0 命中**（见下）
- `v_asset_search` 里 placeholder / page_image 命中均 0；`v_searchable_assets` 仍 11 行全 icon

### 两档如实未解决
- **全相等缺素材**：库里没有能表达「一样大 / 持平」的图标，11 个全是具体物件。
  需要等号类或「持平」类对比符号，本轮不造。
- **无适用占位图查得到但画不出来**：占位图走 `v_fallback_assets`（按 design 不污染正常
  检索，所以按 `chart_semantic='无适用'` 查是 0 命中）；且 `solve.py` / `render.py`
  不认识 `placeholder` 图元，只认 `rect/ellipse/text/arc/ticks/outline`。
  接线要扩 PageSpec 图元类型或加素材贴图渲染层，超出本轮范围。

### 改掉的旧断言（4 条）
- `tests/test_models.py` DB SHA → `45E875A2AFF56ADF6BEFCA1BD97C6B2E30D3DF793F8D5397B612C90B8ABE3195`
- `tests/test_step13_asset_schema.py::test_real_db_has_no_bulk_tagging_yet` →
  `test_real_db_bulk_tagging_only_touches_retrievable_icons`（按 kind 判，不按条数）
- `tests/test_step15_register_icons.py::test_new_rows_use_the_same_conventions_as_existing_icons`
  status 断言放宽为 `in ("待登记","已标注")`
- `tests/test_step15_register_icons.py::test_new_icons_carry_no_tags` →
  `test_new_icons_got_tagged_by_s4`（S4 之后应有标签）
- `tests/test_step15_register_icons.py::test_asset_tags_still_only_has_the_two_placeholders`
  改为只核 id 23/24 那两条仍在

### 验收
- `Ran 394 tests OK`（S3 时 370）
- `migrate_db.py --audit` 9 项全 0 行
- 幂等：`tag_assets.py` + `migrate_db.py` 连跑两遍 SHA 恒为 `45e875a2…3195`
- 既有模块 sha 与 S3 相同：selector `9e7de324728c` / solve `d06ed0efd0f5` /
  render `07bfd7c60f37` / pipeline `2c796685f6a1` / models `6a3536c39a75`

## 第五层接线：图片图元（用户 m04220，412 tests 全绿）

目标：让 PageSpec 能承载图片图元、`render.py` 能把它画进去、`no_applicable` 分支产出可见的占位图。

### 改动（4 个文件，全部点名范围内）

- `loop/models.py`：`ElementSpec` 末尾加 `image_path: str | None = None`（不复用 `binding`，缺省 None → 老 JSON 兼容）。
- `loop/render.py`：`_add_shape()` 加 `image` 分支（`add_picture`，按 `x/y/w/h`）；新增 `_ROOT` + `resolve_image_path()`（相对项目根 → 绝对路径）；缺路径抛 `ValueError`、文件不存在抛 `FileNotFoundError`；填充段加 `el.type != "image"` 守卫。
- `loop/preview.py`：同源 `image` 分支（`Image.open` → resize → `paste` RGBA），路径解析复用 `render.resolve_image_path` —— 否则 PNG 与 PPTX 会对不上。
- `loop/pipeline.py`：常量 `PLACEHOLDER_W_IN/PLACEHOLDER_H_IN = 2.2`、`PLACEHOLDER_TOP_IN = 3.0`；`_placeholder_element()`、`_build_fallback_spec()`；`run_selected` 的 `template_name is None` 分支从「只写 message 返回」改成「查 `v_fallback_assets` → 造 spec → 落盘 → 渲染」。

### 两个刻意不做

1. `_build_fallback_spec` 不写 `constraints`，该分支**不走 `validate_spec`**：占位图无模板，强行走要给 `solve.py` 加豁免分支 = 改求解逻辑，超范围。
2. `status` 仍 `no_applicable`、`selected_template` 仍 `None`：画占位图 ≠ 选型成功。

### 新增测试

`tests/test_step17_image_element.py`（18 用例 / 6 TestCase）：TestModel（JSON 往返、默认 None、老 JSON 可读、不与 binding 混用）、TestRender（PICTURE、name 回读、EMU 尺寸、与 rect/text 共存）、TestMissingFile（FileNotFoundError 带 id+路径、缺字段 ValueError）、TestPipelineFallback（出 pagespec/pptx/preview、只含 1 个 image、可回读 `placeholder_1`、selection.json 仍在、确定性选图）、TestNoRegression（温度计/半圆无 image、正常分支无 image、老 `out/loop1/pagespec.json` 仍渲染 27 形状）、TestEndToEnd（预览占位图盒非白 > 1000 像素）。

### 踩坑

- **`preview.py` 原来根本没有 `image` 分支**：`render.py` 加完分支后 17/18 绿，最后一条端到端断言 `grey=0` 失败——原因是 `preview.py` 的 `else` 兜底把 image 当 rect 画成了一个白框。补上同源分支后 `grey=20` 仍不够，才发现**真正的坑是测试口径**：占位图是线条图（虚线框+三个点），非白像素只占盒面积约 7%，全局 `stride=7` 采样只命中 20 个。改成「只在占位图盒内全扫描、判据用非白」→ 3338/48400。
- **`message` 双重前缀**：`rationale` 本身已以「无适用图形：」开头，我在 message 里又加了一遍 → `无适用图形：无适用图形：…`。去掉外层前缀。

### 改掉的两条旧断言（行为变更所致，不是放宽）

- `tests/test_step12_pipeline.py::test_nothing_was_rendered` → `test_no_applicable_draws_a_placeholder_not_a_default_chart`：不再断言「什么都没画」，改为断言「画出的是 image 且 `layout.kind == fallback_placeholder`、`layout.template is None`」。**反证断言 `test_does_not_fall_back_to_a_default_chart` 原样保留**——不能静默选默认图形这条没变。
- `tests/test_step14_placeholder.py`：`assertIsNone(res["preview"])` → 断言 preview 存在且 `placeholder` 以 `.png` 结尾。

### 验证

- `Ran 412 tests in 5.787s OK`（394 → 412，新增 18）。
- 端到端：`run_selected(values=[10,3,2,2,2,1], semantic='占比构成')` → `status=no_applicable`；`out/demo/fallback_wire/six/` 里 `pagespec.json 746 B` / `preview.png 6760 B` / `loop1.pptx 35727 B` / `selection.json`；`read_shapes` → `{'placeholder_1': PICTURE(13)}`；元素 `('placeholder_1','image','assets/placeholders/placeholder_todo.png',3.9,3.0,2.2,2.2)`；`layout={'template': None, 'kind': 'fallback_placeholder'}`、`constraints=[]`。
- 老产物回归：`out/loop1/pagespec.json` → 27 元素、27 形状、png 22837 B。
- 未动：`db/assets.db` SHA `45e875a2…3195`；`selector.py 9e7de324728c`、`solve.py d06ed0efd0f5` 与上一轮完全一致。
- 改动的四个文件新 sha：`models.py 9231f7b9ea8`、`render.py 4ac0188291e`、`preview.py d50df49826`、`pipeline.py 06444553009`。

## 第五层补漏：占位图边界兜底（用户 m04449，429 tests 全绿）

### 背景

端到端演示（m04383）暴露：占位图分支是全流水线**唯一**一条既不走约束求解、也不走 `validate_spec` 的路径。`PLACEHOLDER_TOP_IN = 3.0` 是绝对常量，画布 6→4 in 时底部 5.20 溢出 1.20 in，而 `status` 仍是 `no_applicable`、不报错——静默产出错误画面。

### 改动（只碰 `loop/pipeline.py`）

- 新增 `FIT_MARGIN_IN = 0.5`、`_EPS = 1e-9`。
- `_is_inside(el, width_in, height_in)`：四边 + 容差判界，与 C1 同口径。
- `_fit_placeholder(el, width_in, height_in, margin_in=0.5) -> dict`：在界内**原样不动**（`adjusted=False`，before==after）；越界则等比缩放至可用区并居中，返回 `{"adjusted","before","after"}`；画布小于 2×margin 抛 `ValueError`。
- `_build_fallback_spec()` 调 `_fit_placeholder`，把记录写进 `layout["placeholder_fit"]`。
- `run_selected()` 新增 `width_in=10.0, height_in=6.0` 关键字参数（此前根本没有画布参数，这是 H=4 无法复现的根因之一），并在 fallback 分支把它传给 `_build_fallback_spec`、把 `placeholder_fit` 放进返回值、`message` 追加调整说明。顺带把正常分支的 `build_pagespec(...)` 也传上 `width_in/height_in`（此前写死默认值）。

### 为什么选「自适应 a」而不是「报错 b」

1. 这条分支存在的意义就是「无适用时也要有可见产物」，报错等于撤销 m04220。
2. 缩放占位图不造成数值失真——它没有 binding、没有约束；温度计/半圆禁止缩放是因为尺寸编码数值。
3. 调整留痕（`placeholder_fit` + message），不是静默缩放。

### 新增测试

`tests/test_step18_placeholder_bounds.py`（17 用例 / 4 TestCase）：
- `TestGeometryHelpers`（6）：`_is_inside` 四边各一、贴边算内、界内不动、短画布缩放居中、margin 生效、画布过小抛错。
- `TestThreeCanvases`（5）：H=6 逐字回归（盒 3.9/3.0/2.2/2.2、adjusted=False）、H=4 元素与 PPTX 产物都在界、H=3 同、三档都留痕（before/after + message 含「越界」与「缩进」）、三档 status 仍 `no_applicable`。
- `TestNoSilentOverflow`（4）：反证未 fit 的盒在 H=4 确实溢出 1.20；`_build_fallback_spec` 确实调了 fit；画布高度 sweep 9 档（6/5/4.5/4/3.5/3/2.5/2/1.5）无一「status 成功但盒越界」；过小画布抛 `ValueError`。
- `TestOtherBranchesUntouched`（2）：温度计/半圆分支的返回值与 `layout` 里都**没有** `placeholder_fit`，且无 image 元素。

### 变异测试（证明闸口有效）

| 变异 | 结果 |
|---|---|
| `_fit_placeholder(el, width_in, 100.0)`（假装画布够大） | `FAILED (failures=14)` |
| 整行替换成「跳过 fit，直接返回 adjusted=False 的记录」 | `FAILED (failures=17)`，含 `test_fit_is_actually_called_by_build_fallback_spec`、`test_no_canvas_size_…` 全 9 档、`test_too_small_canvas_raises_instead_of_pretending` |

两次变异都已还原，`grep MUTANT` 零残留，`loop/pipeline.py` sha 恢复为 `7380d9b1c424`。

### 验证

- `Ran 429 tests in 6.794s OK`（412 → 429，新增 17）。
- H=6 逐字节回归：`fallback/preview.png` 与 `fallback_h6/preview.png` sha256 均 `f7b3545e…c45c`（补丁前那张相同）。
- 三档产物：H=6 盒 (3.9,3.0,2.2,2.2) adjusted=False；H=4 盒 (3.9,0.9,2.2,2.2) adjusted=True 底 3.10；H=3 盒 (4.0,0.5,2.0,2.0) adjusted=True 底 2.50。PPTX 回读底 3.100 ≤ 4.0。
- 未动模块 sha：`selector.py 9e7de324728c`、`solve.py d06ed0efd0f5`、`render.py 4ac01882919e`、`preview.py d50df4982669`、`models.py 9231f7b9ea8a`、`db/assets.db 45e875a2aff5`。

## 第 19 步：统一色板 + 文本角色字号表（用户 m04549）

**问题来源**：m04383 端到端复盘的三条症状——配色零交集、字号全部 `Pt(10)`、
无图框概念。本轮只做前两条（图框不在范围内）。

**范围**：只改渲染层颜色与字号来源；不改几何、不改
`solve/selector/models/pipeline` 逻辑、不新增图元类型、不动 db 与占位图文件。

### 做了什么

1. 新增 `loop/palette.py`（单一来源）：
   - 5 个彩色角色 `primary E8A08C` / `secondary C2512F` / `accent_1 E8B85C` /
     `accent_2 7A9E7E` / `accent_3 6C7A89`，`SECTOR_ROLES` 固定顺序；
   - 5 个中性角色 `neutral_dark 222222`（文本）/ `neutral_strong 7A8088` /
     `neutral_mid A8AEB6` / `neutral_light D6DADF` / `neutral_hairline C9C9C9`
     （刻度线、外圈发丝线）+ `surface FFFFFF`；
   - `ROLE_ALIASES` 把元素 role 映射到色板角色（`liquid→primary`、`track→surface`、
     `outline/ticks→neutral_hairline`、`placeholder_stroke→neutral_strong` …）；
   - 字号表 `FONT_SIZES = {title:20, subtitle:14, body:11, label:9, note:8}`，
     `ROLE_TO_FONT` 把流水线 role 映射进去（`center→subtitle`、`value→body`、
     `label/legend→label`、`scale_note→note`）；
   - 自检 API：`delta_e`（CIE76）、`contrast_ratio`（WCAG）、`check_separation()`。
2. 新增 `loop/text_style.py`：`apply_text_style(shp, el)` / `apply_fill(shp, el)`，
   三个平级适配器共用，避免互相 import。
3. 三个 PPTX 适配器 + 预览层全部改为查表，删掉所有硬编码色值与 `Pt(10)`。
4. 模板默认色与 `text_size` 改为引用色板；`solve.py` 仅扇区兜底色一处。
5. `scripts/make_placeholder.py` 的三档灰改为从色板派生（派生后 png 字节不变）。

### 两个用户裁定的歧义（m04607）

- 半圆要 5 色而用户只给了 4 个彩色角色 → **补 `accent_3`**（石板灰，沿用原版报纸）。
- `subtitle`/`body` 在现有图形里没有直接使用点，而 `center`/`legend`/`value`
  不在用户的 5 角色表里 → **表里定全 5 个设计角色，现有 role 逐个映射进去**。

### 两个实现期发现的坑

1. **预览层 pt/px 单位混用**：字号表是 pt，预览画布 100 px/in。直接当像素用，
   8 pt 注释被画成 8 px（字形不到 6 px 高），`test_scale_note_is_visible_in_preview`
   红（深色像素 0 > 50）。加 `_PX_PER_PT = PX_PER_IN / 72.0` 修好。
2. **`font_size()` 静默降级**：`ROLE_TO_FONT` 里没有 `subtitle`/`body` 键，
   只查映射会把 14 pt 副标题降级成 `note` 的 8 pt（缩水 43%）且不报错。
   改为「映射优先、命中字号表则直查」，补回归测试
   `test_design_role_names_resolve_to_their_own_size`。

### 新增测试 `tests/test_step19_palette.py`（24 用例 / 6 TestCase）

`TestPaletteDefinition`（角色齐全、色值合法 `^[0-9A-F]{6}$`、未知角色抛
`KeyError`、别名解析、sector 顺序固定）、`TestContrastGates`（相邻扇区 ΔE ≥ 20、
任意两扇区 > 10、文本对 `surface`/`neutral_light` ≥ 4.5、
`check_separation() == []`）、`TestFontScale`（5 角色齐、严格递减无并列、
流水线 6 个 role 都有映射、title 最大 note 最小、title > value×1.5、行高随字号
递增、**设计角色名直查字号表**）、`TestRenderersUseSingleSource`（4 个渲染文件
零十六进制字面量、无 `Pt(10)`、都接上单一来源、preview 无 `_font(14)`）、
`TestTemplatesDrawFromPalette`（温度计/半圆默认色 == 色板值、`text_size` 默认
== `FONT_SIZES["label"]`）、`TestPlaceholderDrawsFromPalette`（占位图三档灰
== 色板派生）。

### 验证

- `Ran 453 tests in 6.892s OK`（429 → 453）。
- 渲染层 grep：`"[0-9A-Fa-f]{6}"`、`Pt(10)`、`#888888`、`#222222`、`"white"` 全部 0 命中。
- 三组产出一致性（`out/demo/palette/{thermometer,semicircle,fallback}/`）：
  形状数 37 / 13 / 1 与改动前相同；三组共有色由 `['#FFFFFF']` 增至
  `['#FFFFFF','#A8AEB6']`；字号回读 20/11/9/8（温度计）、20/14/9/8（半圆）。
- 占位图逐字节回归：`placeholder_todo.png` `8a3ad481…2be57`、
  `placeholder_chart.png` `de7403e4…11d7` 与改动前相同。
- 未动模块 sha：`selector.py 9e7de324728c`、`models.py 9231f7b9ea8a`、
  `pipeline.py 7380d9b1c424`、`db/assets.db 45e875a2aff5`。
- 改动后 sha：`palette.py f9fcbd5115cf`、`text_style.py 85ab4b02d940`、
  `render.py 0378049f2fbe`、`render_arc.py bb5e2d942888`、
  `render_thermo.py 8bdd7700675e`、`preview.py 64c371368a4e`、
  `templates.py a57d7d3de533`、`solve.py 720900b10d78`。

### 未做

图框、版面格子、字号自适应版面宽度、插图位、`scale_note` 的读者语言改写。

---

## 第 20 步：图框 + 标题带 + 读者文案（用户 m04818，453 tests 全绿）

### 背景

端到端复盘（`docs/superpowers/specs/2026-11-09-end-to-end-review.md` §1.3 / §1.4）
指出三张图不像同一份报纸：没有图框、没有标题带、`scale_note` 写给开发者看。
用户 m04818 要求本轮只做**单张图表的卡片化**，不做整版排版 / 多图组合 / 版面格子。

### 拍板的设计（用户 m04888）

用户原话要点：「选 A：框 = 内容 bbox + 0.3，画布随框长大，图形一像素不动……
PageSpec 里同时记录 content_bbox 和 frame_bbox 两个字段，width_in/height_in
取 frame_bbox。content_bbox 留给未来整版排版的缩放/适配层用——版式引擎拿到
两个尺寸，才能决定按框缩放还是按内容缩放。」

为什么必须是 A：温度计 5 个类别标签把内容撑到 x 0.040..9.960（9.92 in），
原画布 10 in，任何 ≥0.05 in 内边距都会顶出框；收窄标签会动几何并打破
`x_label = x_track − 0.46` 一组手算断言。

### 实现

- 新增 `loop/frame.py`：`PAD_IN=0.3` / `BAND_H_IN=0.5` / `BAND_GAP_IN=0.15` /
  `NOTE_H_IN=0.3` / `NOTE_GAP_IN=0.2` / `TEXT_INSET_IN=0.15`；
  `content_bbox()` / `wrap()` / `unwrap()` / `validate_frame()`。
  `wrap` 只平移不改几何，写 `layout["frame"] = {origin, canvas, pad_in, band_h_in}`
  与 `PageSpec.content_bbox` / `frame_bbox`。
- `loop/models.py`：`PageSpec` 加 `content_bbox` / `frame_bbox`（缺省 None）。
- `loop/text_style.py`：`BORDER_PT = 1.0`；按 `geometry["align"]` 左右对齐、
  按 `geometry["border"]` 描边。
- `loop/preview.py`：左对齐文本 + `frame` / `title_band` 绘制分支。
- `loop/solve.py`：`scale_note` 改读者语言 + `_reader_unit()`；
  `validate_spec` 开头认领「先 `validate_frame`、再 `unwrap` 还原求解坐标」。
- `loop/scaffold.py`：`build_pagespec(..., frame=False, subtitle_text=None)`；
  **默认 False**（求解层单测关心纯坐标），交付路径显式 True。
- `loop/build_loop.py` / `loop/pipeline.py`：交付路径 `frame=True`；
  占位图分支 `wrap_frame(spec, note_text=PLACEHOLDER_NOTE)`。

### 两个坑

1. **`validate_spec` 坐标系**：包框后 `x_in` 是卡片坐标，篡改 `track_1.x_in=20`
   会先撞 `validate_frame` 的 content_bbox 一致性检查（报的不是 C1）。
   → `validate_spec` 自己拆框；测试篡改前先 `unwrap`。
2. **`build_pagespec` 默认值**：一开始默认 `frame=True`，40+ 条求解层单测全红
   （它们断言求解坐标与 27/37 元素）。→ 改默认 False、交付路径显式开框。

### 验证

- `Ran 453 tests in 7.986s OK`。
- 三组（`out/demo/frame/`，总览 `_sheet_all.png`）：
  | 组 | 状态 | 画布 | content_bbox | 元素/形状 |
  |---|---|---|---|---|
  | thermometer | rendered | 10.52 × 5.85 | `[0.3,1.45,9.92,4.1]` | 39 / 39 |
  | semicircle | rendered | 7.15 × 5.85 | `[0.3,1.45,6.55,4.1]` | 15 / 15 |
  | fallback | no_applicable | 2.80 × 3.95 | `[0.3,1.45,2.2,2.2]` | 5 / 5 |
- 三组 `title.x_in=0.45`、`title.y_in=0.30`、`title.h_in=0.50` 完全一致；
  `frame` / `title_band` 均能 `read_shapes()` 回读（AUTO_SHAPE）。
- 三组 PPTX 文本里 `V_max` / `液柱高度 =` / `Σθ=` / `arc_total` / `× 数值 /` 命中 0。
- 老产物 `out/loop1/pagespec.json`：27 元素可读、可渲染 27 形状
  （pptx 29239 / png 27268）；`validate_spec` 仍按 E.4-L6 拒（旧 C4 口径，预期）。
- 未动：`selector.py 9e7de324728c`、`db/assets.db 45e875a2aff5`、
  `placeholder_todo.png 8a3ad481e3e5`、`placeholder_chart.png de7403e4a326`。
- 改动后 sha：`frame.py dc74913b84f8`、`models.py 2f68365a05d4`、
  `solve.py 036ea01427c2`、`pipeline.py b3a1624dff2e`、`preview.py 60b4a4ff324e`、
  `text_style.py b2af6aa03ca9`、`scaffold.py b49328fc27d5`、
  `build_loop.py 9f8a4db98154`。

### 已知仍缺

半圆第 1 扇区（`primary` 暖珊瑚）在浅色背景上对比弱；无插图位、无版面格子、
无字号随画布自适应。

---

## 第 21 步：修复温度计外圈与管身错位（用户 m05104，461 tests 全绿）

### 现象

用户肉眼验收 preview 时看到「液柱贴着管身左侧」。实测**液柱与球泡都是居中的**
（track / liquid / bulb 中心都是 0.9000），偏的是包住整支温度计的外圈轮廓
`outline`：`geometry.cx=0.6400`，折线跨度 0.3350..0.9450，中心 0.6400，
左偏 0.26 in——正好等于图框平移量 dx。轮廓右壁压在液柱上、左壁离管身很远，
观感就成了「液柱偏左」。

### 根因

1. `outline.geometry` 存的是**求解坐标系下的绝对坐标**（cx / cy / cap_top / tube_bottom）；
2. 第 20 步的 `loop/frame.py::wrap` 只平移 `x_in/y_in`，没动 geometry；
3. `loop/thermo_shape.py::outline_polyline` 直接拿 `geometry.cx` 当页面坐标画。

它还是「自洽地错」：`unwrap()` 把 `x_in` 平移回去后，`_chk_skin` 用
`t.x_in + w_track/2` 重算出的 cx 恰好等于那份没被平移的 geometry.cx，校验器放行
——所以逃过了 453 条测试。

### 修法（两条都做，不是二选一）

- `loop/thermo_shape.py::outline_polyline`：改为以**外接盒**为锚点，
  `ox = el.x_in - (g["cx"] - R)`、`oy = el.y_in - g["cap_top"]`，再
  `cx = g["cx"] + ox`。geometry 从此只提供相对尺寸（R / cap_r / neck_h），
  位置一律由 bbox 决定。
- `loop/frame.py`：新增 `ABS_X_KEYS=("cx",)` / `ABS_Y_KEYS=("cy","cap_top","tube_bottom")`
  与 `_shift_geometry()`；`wrap` / `unwrap` 平移 `x_in/y_in` 时把 geometry 里的
  绝对坐标一起平移（半圆扇区的 cx/cy 也在同一套键里）。

### 新增测试 `tests/test_step20_alignment.py`（8 用例 / 3 TestCase）

- `TestThermometerCentrelines`：5 根管的 liquid / bulb 中心 == track 中心（0.001 in）；
  outline 折线跨度中点 == track 中心；折线不越出自己声明的 bbox。
- `TestAlignmentSurvivesFraming`：包框后三中心仍重合；wrap 逐键平移 geometry 绝对
  坐标；相邻管中心距不受包框影响；unwrap 逐键还原。
- `TestSkinStaysAligned`：包框后刻度右端仍严格贴管身右缘。

### 验证

- `Ran 461 tests in 6.747s OK`（453 → 461）。
- 三组重出 `out/demo/frame/`（总览 `_sheet_all.png`）：thermometer 10.52×5.85 / 39、
  semicircle 7.15×5.85 / 15、fallback 2.80×3.95 / 5。
- 温度计 5 根管：track / liquid / bulb / outline.geometry.cx / outline bbox 中心
  全部相等 —— 0.90 / 3.08 / 5.26 / 7.44 / 9.62。
- 像素复核第 1 支管：y=330..470 外圈 72..108（中心 90）、液柱 86..94（中心 90）；
  y=500 球泡外圈 59..121（中心 90）、珊瑚 66..115（中心 90.5）。

### 未受影响

半圆扇区只从 geometry 取角度、盒子来自 bbox；`preview.py` / `render_arc.py` 的 arc
分支都不读 cx/cy 定位。故无需改动，`_chk_C8` 与 `_chk_skin` 仍通过。

---

## 第 22 步：半圆扇区描边 + 字号随画布缩放（用户 m05688，476 tests 全绿）

### 一、半圆扇区描边

- 常量进色板：`SECTOR_STROKE_ROLE = "neutral_mid"`（A8AEB6）、
  `SECTOR_STROKE_PT = 0.5`。
- `loop/render_arc.py`：`apply_fill` 之后给 `el.type == "arc"` 的元素补
  `shp.line.color.rgb = neutral_mid`、`shp.line.width = Pt(0.5)`。
- `loop/preview.py`：`pieslice` 描边色改用 `_SECTOR_EDGE`；0.5 pt 在 100 px/in
  下约 0.69 px，Pillow 只支持整数线宽，取整 1 px。
- 数值验证：圆心 px (480,350)、R=205；沿 180° 与 194.4° 两条边界射线各采到
  170 个描边像素；扇区内部为 primary E8A08C 与 secondary C2512F。

### 二、字号随画布缩放

- `palette.canvas_scale(w, h) = min(w/10, h/6)`（基准 `BASE_CANVAS_W_IN=10`,
  `BASE_CANVAS_H_IN=6`）。
- `palette.spec_scale(spec)`：优先 `frame_bbox`，无框时退回 `width_in/height_in`。
- `palette.scaled_font_size(role, scale)`：`round(base*scale, 2)` 后截断到
  `[MIN_FONT_PT=6, MAX_FONT_PT=24]`；两位小数是为了避开 `Pt()` 按百分之一磅
  截断把 16.0 落成 15.99。
- `text_style.apply_text_style(shp, el, scale=1.0)`；
  `preview._draw_text(..., scale=...)` 与 `palette.line_height_px(role, scale=)`。
- 三个 PPTX 适配器各自在 `render_*` 开头算一次 `scale = palette.spec_scale(spec)`。

### 三、三组实测（out/demo/scale/）

| 组 | 画布 | scale | 标题 | 说明 | 中心 | 标签 | 真值 | 重叠 |
|---|---|---|---|---|---|---|---|---|
| thermometer | 10.52×5.85 | 0.975 | 19.50 | 7.80 | 13.65 | 8.78 | 10.72 | 无 |
| semicircle | 7.15×5.85 | 0.715 | 14.30 | 6.00* | 10.01 | 6.44 | 7.87 | 无 |
| fallback | 2.80×3.95 | 0.280 | 6.00* | 6.00* | — | — | — | 无 |

* 命中 6 pt 下限。pt/框宽 比例：基准 2.00、thermometer 1.85、semicircle 2.00、
fallback 2.14，三张并排协调。文本两两求交全部为空，且都在 frame_bbox 内。

### 四、形状数与未动模块

- 半圆 15 / 温度计 39（元素数与形状数都未变；描边是属性、缩放只是数值）。
- 未动 sha：`loop/selector.py 9e7de324728c`、`loop/solve.py 036ea01427c2`、
  `loop/models.py 2f68365a05d4`、`loop/pipeline.py b3a1624dff2e`、
  `db/assets.db 45e875a2aff5`。

### 五、新增测试 tests/test_step21_font_scale.py（15 用例 / 5 TestCase）

TestSectorStroke / TestCanvasScaleFormula / TestRenderersApplyTheScale /
TestSemicircleAndThermometerShapesUnchanged / 小卡片元素不过框。

### 六、未做

未改任何布局（文本盒坐标未动）；小卡片文字被 6 pt 下限兜住后仍只占标题带
一小条，属「不重排版面」的代价；未做多图混排与版面格子。


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


### 第 24 步：自由布局 0.1（流式排版，用户 m05945）

* 新增 `loop/layout.py`：`LayoutSpec` / `CardSpec` / `PlacedCard` /
  `PageLayoutSpec` / `LayoutOverflowError` / `build_card` / `flow_layout` /
  `flatten`（元素平移 + id 加 `c{i}_` 前缀 + `geometry._scale`）。
* 新增 `loop/render_page.py`：`render_pptx_page`（`_add_basic` + `_add_skin`
  + image 分支，字号按元素自带 `_scale`）、`compose_preview`（逐卡片渲染再贴
  回画布）、`render_layout`、`needs_page_renderer`。
* 新增 `scripts/build_page_demo.py` 与 `tests/test_step23_flow_layout.py`
  （18 用例 / 5 TestCase）。
* 演示 `out/demo/page/`：10×15 画布，margin 0.4，gutter 0.3；
  thermo (0.40,0.40,9.2×4.6) / semi (0.40,5.30,4.45×4.6) /
  placeholder (5.15,5.30,4.45×4.6)；水平与垂直邻距实测都严格等于 0.30。
* 溢出门槛：自然尺寸下温度计卡片 10.52 in > 可用 9.20 in →
  `LayoutOverflowError`（不截断、不静默）；高度不够同样报错并给 `needed_h`。
* 验证：`Ran 504 tests OK`（486 → 504）；未改任何单卡渲染逻辑
  （`loop/solve.py` / `loop/scaffold.py` / `loop/pipeline.py` / `loop/frame.py`
  本轮零改动）。


### 第 25 步：排版引擎 0.2（同行等高拉伸 + 溢出保底，用户 m05995）

* `loop/layout.py`（本轮**唯一**改动的生产文件）：新增 `LayoutFitError`；
  `LayoutSpec` 新增 `equal_height=True`、`fit_oversized` 默认 True；
  `build_card(..., stretch_to_in=None)`；`flow_layout` 改成两趟
  （先按宽度分行，再按行高拉高较矮卡片）；`_readable()` 做 6pt 保底检查；
  `fit.BoundaryError` 在排版层换成 `LayoutFitError`。
* 新增 `tests/test_step24_equal_height.py`（15 用例 / 3 TestCase）。
* 演示 `out/demo/page/`：第二行 semi 4.45×5.2 与 placeholder 4.45×3.6
  → 排版后两张都是 4.45×5.2、y 都是 5.30，图框下边线都在 y=1049。
* 保底报错 `out/demo/page/_fit_error.txt`：整版宽 4.0 in 时
  `LayoutFitError（最小可行尺寸 3.04×2.35 in）`。
* 验证：`Ran 519 tests OK`（504 → 519）。

## 第 26 步：图文混排 0.1（TextBlock + 文本流，用户 m06055）

* 新增 `loop/text_flow.py`：`wrap(text, style, width_in, scale)`（与预览同口径
  逐字折行，`\n` 是硬换行）、`line_height_in(style, scale)`、
  `block_height_in(...) = 行数 × 行高 + 2 × BLOCK_PAD_IN(0.05)`。
  **折行由排版层定、渲染器照抄**，否则排版高度与看到的行数是两套。
* `loop/layout.py`：新增 `TextBlock(text, style, align, width_in, name)`（样式名
  即色板字号表的设计角色，构造时校验）与 `PlacedBlock`（含折好的 `lines`）；
  `PageLayoutSpec` 增加 `blocks` / `items()` / `block(name)`；`flow_layout`
  重写为混合流：卡片按宽度塞进当前行、文本块先收行再独占整行，收行时沿用
  0.2 的等高拉伸；任一步越界抛 `LayoutOverflowError`；`flatten` 把文本块摊成
  `t{i}_` 前缀的 text 元素（`geometry = {block, lines, align, _scale}`）。
* `loop/render_page.py`：PPTX 端 `_add_text_block`（`word_wrap=False` + 按行换行 +
  `MSO_ANCHOR.TOP` + 字号 `scaled_font_size(style, _scale)`）；PNG 端
  `_draw_block` 逐行画，行高与排版层同一个函数；`_TEXT` 与单卡预览同源。
* 演示 `scripts/build_newspaper_demo.py` → `out/demo/paper/`：10 × 15 in，
  大标题 / 导语 / 温度计 / 正文 / 半圆+占位并排 / 尾段，共 7 项；
  五处相邻行带垂直间隔全部 0.30 in、并排两卡水平邻距 0.30 in（= gutter）；
  全部项在 `[0.4, 9.6] × [0.4, 14.6]` 内且两两不相交；`page.pptx` 63 形状 =
  39+15+5+4；溢出反例（10 × 6 in）→ `LayoutOverflowError`，记在
  `out/demo/paper/_overflow.txt`。
* 新增 `tests/test_step25_text_flow.py`（20 用例 / 5 TestCase：TextBlock 定义与
  高度公式 / 混合流落位与 gutter / 溢出 / flatten 与渲染 / 只放卡片仍向后兼容）。
* 验证：`Ran 539 tests OK`（519 → 539）。单卡模块 sha 全部与上一轮一致
  （solve `b62808464658`、scaffold `71077d79491a`、preview `61314e7ba1a6`、
  render `ce42c5ba5880`、fit `d36beb50b5d9`、pipeline `39cd4b790a98`、
  selector `9e7de324728c`、db `45e875a2aff5`）。
* 说明：0.1 采用「上下型排布」（文本独占整行），因此不存在「文本折行高度
  与卡片行对齐」的难题；两侧环绕是另一套算法，未做。


## 第 27 步：自动化编排 0.1（用户 m06157，566 tests 全绿）

新增 `loop/compose.py`（拆段 / 认标题导语 / 数据匹配 / 组流 / 整版输出）、
`scripts/build_auto_layout_demo.py`、`tests/test_step26_auto_compose.py`（27 用例）。

- 匹配规则：`chart_title` → `(地区, 品类, 维度, 指标)`；段落必须同时有品类 + 指标 +
  （维度或地区）；地区组必须见到地名；加权打分（地区 4 / 品类 3 / 维度 3 / 指标 2），
  平分时通用组优先、再按 key 排序。
- 卡片预设：`ratio = min(1, 可用宽/自然宽, 可用高 × MAX_CARD_HEIGHT_RATIO(0.35)/自然高)`。
- 演示 `out/demo/auto_layout/`：流 = 标题 → 导语 → 增速段 → 温度计卡(heat_ratio_top5)
  → 年龄段 → 半圆卡(heat_age)；六项不相交、间隔 0.3、底部 13.2338。
- 退化演示 `out/demo/auto_layout/_plain/`：无数据 → 纯文本页 + `no_data_matched` note。
- 不适用兜底由 `on_unapplicable`（`skip` 默认 / `placeholder`）控制，两条都有测试。
- 未动：`loop/layout.py 595bb174aca3`、`loop/render_page.py 254b2181cf1d`、
  `loop/scaffold.py 71077d79491a`、`loop/solve.py b62808464658`、`loop/fit.py d36beb50b5d9`、
  `db/assets.db 45e875a2aff5`。新增 `loop/compose.py 45c33e3e9521`。
- `Ran 566 tests OK`（539 → 566）。

## 第 28 步：多栏图文混排 0.1（用户 m06230）

- 目标：版面从「单栏一栏到底」升级为多栏；文本块可分栏、可跨栏，卡片可跨栏也可并排；
  同时把卡片高度上限从 `compose.py` 挪进 `LayoutSpec`。
- 新增/改动：
  - `loop/text_flow.py 44e6f66b395d`：`inner_column_width_in` / `balance_lines` /
    `wrap_columns` / `columns_height_in` —— 块内先按**栏宽**折行、再按行数均分到各栏
    （阅读顺序保持左栏接右栏，不丢字不重复）。
  - `loop/layout.py abb99f357a0d`：`LayoutSpec` 增 `column_count`(1..3) /
    `column_gutter_in`(0.2) / `max_card_height_ratio`(0.35)；`CardSpec` 增 `column_span`/`note`；
    `TextBlock` 增 `column_span`/`columns`；`card_box` 钉死跨栏宽度；`flow_layout` 改「按栏位
    塞行」并记录行类型（`text`/`cards`/`row`）；`_build_card_fitted` 在装不下时把高度顶到
    `max_card_height_in` 再试（修掉「宽而扁」格子误报装不下）。
  - `loop/render_page.py 05b93b1dec3e`：文本块按 `line_groups` **每栏各画一个 TextBox / 各画一组行**。
  - `loop/compose.py c404b0a58249`：`on_unapplicable` 默认改 `placeholder`；`_fallback_note` 把拒选
    理由翻成读者话；`_card_span` 决定卡片占几栏；删掉 `MAX_CARD_HEIGHT_RATIO`（政策进 LayoutSpec）。
  - `loop/pipeline.py c9e7739127f5`：`_build_fallback_spec(..., note=...)` 把理由透传给占位图。
  - 新增 `scripts/build_multicol_demo.py`（自动页 + 手工 `_spread` 页）、
    `tests/test_step27_multicol.py`（34 用例 / 8 TestCase）。
- 栏位算术（10 in / margin 0.4 / 2 栏 / 栏间距 0.2）：可用宽 9.20、栏宽 4.50、
  跨栏 9.20、`slot_x_in` 0.40 与 5.10。行内并排空隙 = 栏间距 0.2，行间 = gutter 0.3。
- 演示 `out/demo/multicol/_spread/`：标题(跨2栏) → 导语+结尾(各占一栏并排) → 温度计卡(跨2栏)
  → 两栏正文 → 半圆卡+占位卡(各占一栏并排)；底部 13.04/15，七项不相交。
  像素复核：栏间 0.2 in 深色像素 0；卡框竖边 40/489/510/959 px = 0.40/4.90/5.10/9.60 in。
- 向后兼容：`out/demo/page`、`out/demo/paper`、`out/demo/auto_layout` 三页坐标逐项与上一轮一致。
- 未动：`loop/solve.py b62808464658`、`loop/scaffold.py 71077d79491a`、`loop/fit.py d36beb50b5d9`、
  `loop/frame.py d6cb4c36b56d`、`loop/selector.py 9e7de324728c`、`loop/models.py 2f68365a05d4`、
  `db/assets.db 45e875a2aff5`。
- `Ran 600 tests OK`（566 → 600）。


## 第 29 步：图文并茂 1.0（用户 m06471）—— 素材库接进自动编排

- 生产改动四处：`loop/layout.py`（新增 `ImageBlock` / `PlacedImage` /
  `image_size_in` / `fit_rect_in` / `image_box`；`LayoutSpec.max_image_height_ratio`；
  `flow_layout` 的 `_box_of` 改返回四元组；`flatten` 摊出 `i{i}_` 前缀的 image 元素）、
  `loop/render_page.py`（`_add_image` 认 `geometry["image_rect"]`；新增
  `_paste_illustration`）、`loop/compose.py`（`_pick_illustration` / `_fallback_note` /
  `ILLUSTRATED_CARD_SHARE` / `Match.illustration`；`build_flow` 三种分支）。
- 新增 `scripts/build_illustrated_demo.py`（三页 + 总览图 + 插图放大带）、
  `tests/test_step29_illustration.py`（39 用例 / 6 TestCase）。
- 关键设计：宽高比读文件不猜；`v_asset_search` 的顺序就是配图优先级；
  单栏把一行切成「图表 66% + 插图 34%」，否则演示页直接溢出（16.77 > 15.00）。
- 演示 `out/demo/illustrated/`：`_spread`（半圆卡 + people 图标并排，y 都是 8.07）、
  `auto`（两处图文咬合）、`_no_asset`（无插图照排）。
- 像素指纹：people 区 `(96,120,190)`；radiator_soft 区 `(250,223,216)` = alpha 0.2 叠白底理论值。
- 改动后 sha：`loop/layout.py bbe90ebd8404`、`loop/render_page.py 0477793afa90`、
  `loop/compose.py 1867bb1a75e0`、`scripts/build_illustrated_demo.py 4d18dd18083c`。
  未动：`loop/solve.py b62808464658`、`loop/scaffold.py 71077d79491a`、
  `loop/fit.py d36beb50b5d9`、`loop/frame.py d6cb4c36b56d`、`loop/text_flow.py 44e6f66b395d`、
  `loop/selector.py 9e7de324728c`、`loop/models.py 2f68365a05d4`、
  `loop/pipeline.py c9e7739127f5`、`db/assets.db 45e875a2aff5`。
- `Ran 639 tests OK`（600 → 639）。

## 第 30 步：S6 桥接 0.1 —— 按文本主题配插图（用户 m06731，676 tests 全绿）

目标：插图从「按图表语义选」升级到「按文本主题选」，主题查不到再降级回图表语义。

### 做法

1. **词表反着建**（`loop/asset_lookup.py`）
   * `semantic_theme_terms()`：`tag_vocabulary` 里 `tag_type='semantic'`、
     `deprecated=0`、且 `EXISTS` 一条挂在 `v_searchable_assets` 上的 `asset_tags`
     —— 只收**有图可配**的主题。规范标签先登记，`aliases` 用 `setdefault` 补。
   * `resolve_theme_tag()`：词面 → 规范标签。`asset_tags.tag` 存的是规范标签，
     别名只活在 `aliases` 里，所以「年龄段」直接查会查空。**这是本轮修掉的坑。**
   * `find_assets_by_theme()`：解析别名后转调 `find_assets_by_semantic`（同视图同排序）。
2. **抽取**（`loop/compose.py`）
   * `load_theme_terms()`：`THEME_MIN_CHARS = 2` 过滤单字词面（冷/火/焰/％/袜/雪），
     61 个原始词面 → **55** 个可用。
   * `extract_theme(text, terms)`：取**命中最长的词面**，并列按词面字典序。
     「取暖电器」(4) 压过别名「年龄段」(3)。
3. **决策树**（用户 m06739 裁定，方案 1）
   * `_pick_illustration(theme, semantic, db_path, used) -> (block, basis)`：
     `theme` → `chart_semantic` → `None`，每档只取**没用过**的 `asset_id`。
     返回的 `basis` 记进 `Match.illustration_basis`，`flow_summary()` 里是 `matched_by`。
   * `Match.theme`、`ComposeResult.themes`（`{段落: 主题}`）一并落盘。

### 演示（`out/demo/theme_match/`）

主稿两段正文都写「取暖电器」：

| 段落 | 主题 | 图表 | 配图 | basis |
|---|---|---|---|---|
| 分品类看…环比增速 | 取暖电器 | thermometer | 17 `radiator_soft.png` | theme |
| 分年龄段看…占比 | 取暖电器 | semicircle | 26 `people.png` | chart_semantic（降级） |

反例 `_no_theme/`：稿子只提「加热电器」（非主题词）→ 主题全 `None` → 回落
`chart_semantic`。像素指纹：暖气片区 `(250,223,216)`、人形区 `(96,120,190)`。

### 验收

* 新增 `tests/test_step30_theme_match.py`（37 用例 / 5 TestCase）。
* `tests/test_step29_illustration.py` 跟随更新 4 处：`_pick_illustration` 多了
  `theme` 形参（2 处），「库查空 / 库抛异常」现在要同时打桩两条检索路径（2 处）。
* `Ran 676 tests in 164.6s OK`（639 → 676）。
* 未动：`loop/solve.py`、`loop/scaffold.py`、`loop/fit.py`、`loop/frame.py`、
  `loop/layout.py`、`loop/render_page.py`、`loop/selector.py`、`loop/models.py`、
  `db/assets.db`（SHA `45e875a2aff5`）。

### 未做

* 不做真正 NLP（不调 LLM、不引依赖）；不做词义消歧、拼音/近义改写。
* 主题只用于选插图，不参与「这段配哪组数据」的判定。
* 一段只配一个主题；命中多个时取最长的，不做多主题加权。
