"""审查修复轮（FRESH REVIEW REPORT: Needs fixes）。

三条 Important + 一条数据完整性 Minor，全部先写测试再改实现：

  1. 声明的 constraints / geometry_expr 惰性：solve() 按 template.name 分派
     硬编码函数，validate_spec 不读 spec.constraints。
     → 让 solve() 强制校验声明集完整；让 validate_spec **按 spec.constraints
       每一行分派校验器**重新推导几何；改声明行必须改变行为。
  2. 半圆读回校验跳过 DATA 链接：sector 的 theta/end_angle 被篡改仍 ACCEPTED。
     → 新增半圆分支：θ_i = scale.factor × v_i、Σθ 闭合、中心数值实时归一。
  3. gap_title / top_reserve 等布局 override 与求解器竖直堆叠脱节 → 伪 C1。
     → top_reserve 由竖直分量派生，preprocess 与 solve 消费同一派生值。
  4. 半圆单个负值产生负扇角（几何非法 PIE 楔形）→ 明确拒绝。

期望值全部手算 / 结构字面量，不调用被测代码推导。
"""
import unittest

from loop.data_source import DB_PATH, load_points
from loop.scaffold import build_pagespec
from loop.solve import SolveError, build_skeleton, solve, validate_spec
from loop.templates import get_template

PTS = load_points(DB_PATH)[1]


def _thermo(**kw):
    return build_pagespec(PTS, "温度计", **kw)


def _semi(**kw):
    return build_pagespec(PTS, "半圆", template_name="semicircle", **kw)


def _by(spec, eid):
    return next(e for e in spec.elements if e.id == eid)


def _declared_ids(spec):
    return [c["id"] for c in spec.constraints]


# ---------------------------------------------------------------------------
# Important 1：声明行必须真的参与求解与读回校验（不再只是元数据）
# ---------------------------------------------------------------------------
class TestDeclaredConstraintsAreLoadBearing(unittest.TestCase):
    def test_solve_refuses_skeleton_missing_a_required_constraint_row(self):
        # 从骨架的声明集删掉 C6 → solve() 必须拒绝，而不是照旧硬编码出坐标。
        sk = build_skeleton(get_template("thermometer"), PTS, "heat_ratio_top5", "T")
        self.assertIn("C6", _declared_ids(sk))
        sk.constraints = [c for c in sk.constraints if c["id"] != "C6"]
        with self.assertRaises(SolveError) as ctx:
            solve(sk, PTS)
        self.assertIn("C6", str(ctx.exception))

    def test_validate_spec_rejects_unknown_declared_constraint_id(self):
        # 把某行的 id 改成未登记的约束 → 读回校验必须拒绝，不能假装验过。
        spec = _thermo()
        spec.constraints[0]["id"] = "C_BOGUS"
        with self.assertRaises(SolveError):
            validate_spec(spec)

    def test_validate_spec_rejects_missing_required_constraint_row(self):
        spec = _thermo()
        spec.constraints = [c for c in spec.constraints if c["id"] != "DATA"]
        with self.assertRaises(SolveError) as ctx:
            validate_spec(spec)
        self.assertIn("DATA", str(ctx.exception))

    def test_every_declared_constraint_row_is_rederived_for_both_templates(self):
        # 逐行移除：每一行都必须让 validate_spec 抛错 → 没有一行是惰性的。
        for make in (_thermo, _semi):
            spec = make()
            for cid in _declared_ids(spec):
                with self.subTest(template=spec.layout["template"], removed=cid):
                    s = make()
                    s.constraints = [c for c in s.constraints if c["id"] != cid]
                    with self.assertRaises(SolveError) as ctx:
                        validate_spec(s)
                    self.assertIn(cid, str(ctx.exception))

    def test_valid_both_templates_still_pass_readback_validation(self):
        for spec in (_thermo(), _semi()):
            with self.subTest(template=spec.layout["template"]):
                validate_spec(spec)


# ---------------------------------------------------------------------------
# Important 2：半圆读回校验必须覆盖数据链接（θ / Σθ 闭合 / 中心数值）
# ---------------------------------------------------------------------------
class TestSemicircleReadbackDataLink(unittest.TestCase):
    def test_tampered_sector_theta_is_rejected(self):
        spec = _semi()
        _by(spec, "sector_1").geometry["theta"] = 999.0
        with self.assertRaises(SolveError):
            validate_spec(spec)

    def test_tampered_sector_end_angle_is_rejected(self):
        spec = _semi()
        _by(spec, "sector_1").geometry["end_angle"] = 999.0
        with self.assertRaises(SolveError):
            validate_spec(spec)

    def test_tampered_scale_factor_breaks_arc_sum_and_is_rejected(self):
        spec = _semi()
        spec.scale.factor = 1.0
        with self.assertRaises(SolveError):
            validate_spec(spec)

    def test_tampered_center_percent_is_rejected(self):
        # E.3 #4：中心数值必须是 v_center/Σv×100% 实时归一，不能写死 80%。
        spec = _semi()
        _by(spec, "center").geometry["percent"] = 80.0
        with self.assertRaises(SolveError):
            validate_spec(spec)

    def test_tampered_center_text_is_rejected(self):
        spec = _semi()
        _by(spec, "center").text = "80.0%"
        with self.assertRaises(SolveError):
            validate_spec(spec)

    def test_broken_arc_recurrence_is_rejected(self):
        spec = _semi()
        _by(spec, "sector_2").geometry["start_angle"] = 999.0
        with self.assertRaises(SolveError):
            validate_spec(spec)

    def test_stripped_sector_geometry_raises_solveerror_not_keyerror(self):
        spec = _semi()
        _by(spec, "sector_1").geometry = None
        with self.assertRaises(SolveError):
            validate_spec(spec)

    def test_stripped_center_binding_raises_solveerror_not_typeerror(self):
        spec = _semi()
        _by(spec, "center").binding = None
        with self.assertRaises(SolveError):
            validate_spec(spec)


# ---------------------------------------------------------------------------
# Important 1（续）：每条声明约束都从几何重新推导，破坏任一即被拒
# ---------------------------------------------------------------------------
class TestEachConstraintReDerived(unittest.TestCase):
    def test_broken_C3_vmax_is_rejected(self):
        spec = _thermo()
        spec.scale.v_max = 99.0
        with self.assertRaises(SolveError):
            validate_spec(spec)

    def test_broken_C3_semicircle_factor_is_rejected(self):
        spec = _semi()
        spec.scale.factor = 1.0
        with self.assertRaises(SolveError):
            validate_spec(spec)

    def test_broken_C4_liquid_bottom_is_rejected(self):
        spec = _thermo()
        _by(spec, "liquid_1").y_in += 0.2
        with self.assertRaises(SolveError):
            validate_spec(spec)

    def test_broken_C5_centering_is_rejected(self):
        spec = _thermo()
        _by(spec, "label_1").x_in += 0.3
        with self.assertRaises(SolveError):
            validate_spec(spec)

    def test_broken_C6_equal_spacing_is_rejected(self):
        spec = _thermo()
        _by(spec, "track_3").x_in += 0.1
        with self.assertRaises(SolveError):
            validate_spec(spec)

    def test_whole_spec_shifted_right_is_rejected_not_self_referential(self):
        # C6 的 margin 必须取自 layout，而不是 title.x_in（自指）：
        # 整体平移时 title 跟着动，自指检查会静默通过。
        # 平移量取 0.02：label_5 右缘 9.96 仍在画布内，C1 不会先于 C6 触发，
        # 从而保证这条测试验的确实是 C6 的重推而不是画布越界。
        # 皮肤图元的 outline.geometry.cx 也必须同步平移，否则 C4 的皮肤重推
        # 会先报错（那是另一条约束，不是本测试要验的）。
        spec = _thermo()
        for e in spec.elements:
            e.x_in += 0.02
        for o in [e for e in spec.elements if e.role == "outline"]:
            o.geometry = dict(o.geometry or {})
            o.geometry["cx"] = o.geometry["cx"] + 0.02
        with self.assertRaises(SolveError) as ctx:
            validate_spec(spec)
        self.assertIn("C6", ctx.exception.conflicts)

    def test_broken_C7_radius_is_rejected(self):
        spec = _semi()
        _by(spec, "sector_1").geometry["R"] = 4.0
        with self.assertRaises(SolveError):
            validate_spec(spec)

    def test_broken_C4_semicircle_legend_stack_is_rejected(self):
        spec = _semi()
        _by(spec, "legend_2").y_in += 0.2
        with self.assertRaises(SolveError):
            validate_spec(spec)

    def test_broken_C5_semicircle_center_box_is_rejected(self):
        spec = _semi()
        _by(spec, "center").x_in += 0.5
        with self.assertRaises(SolveError):
            validate_spec(spec)


# ---------------------------------------------------------------------------
# Important 3：布局 override 与竖直堆叠模型必须一致（不再伪 C1）
# ---------------------------------------------------------------------------
class TestLayoutOverrideConsistency(unittest.TestCase):
    def test_gap_title_0_3_shifts_stack_and_track_together(self):
        # 手算（0 点在球顶的竖向模型）：top_reserve = 0.5+0.5+0.3+0.3+0.2 = 1.8；
        # below_stack = h_label+gap_label+bulb_d+gap_value+h_value+bottom_margin
        #             = 0.34+0.03+0.52+0.03+0.18+0.25 = 1.35；
        # H_track = min(3.0, 6−1.8−1.35=2.85) = 2.85；
        # y_label=1.8, y_track = 1.8+0.34+0.03+2.85−2.85 = 2.17,
        # 0 点 y_bulb = 1.8+0.34+0.03+2.85 = 5.02 → y_value = 5.57。
        spec = _thermo(param_overrides={"gap_title": 0.3})
        self.assertAlmostEqual(_by(spec, "track_1").y_in, 2.17, places=9)
        self.assertAlmostEqual(_by(spec, "track_1").h_in, 2.85, places=9)
        self.assertAlmostEqual(_by(spec, "bulb_1").y_in, 5.02, places=9)
        self.assertAlmostEqual(_by(spec, "value_1").y_in + _by(spec, "value_1").h_in,
                               5.75, places=9)
        validate_spec(spec)     # 读回校验也必须接受这个合法规格

    def test_gap_title_0_6_no_longer_throws_spurious_C1(self):
        # top_reserve=2.1，H_track=min(3.0, 6−2.1−1.35)=2.55，
        # y_track = 2.1+0.37+2.55−2.55 = 2.47。
        spec = _thermo(param_overrides={"gap_title": 0.6})
        self.assertAlmostEqual(_by(spec, "track_1").y_in, 2.47, places=9)
        self.assertAlmostEqual(_by(spec, "track_1").h_in, 2.55, places=9)
        validate_spec(spec)

    def test_explicit_top_reserve_override_is_rejected_with_guidance(self):
        # top_reserve 是派生量，不能单独覆盖；提示改分量而不是静默错开。
        with self.assertRaises(SolveError) as ctx:
            _thermo(param_overrides={"top_reserve": 2.5})
        self.assertIn("C4", ctx.exception.conflicts)


# ---------------------------------------------------------------------------
# 数据完整性：半圆负扇角
# ---------------------------------------------------------------------------
class TestNegativeSemicircleValue(unittest.TestCase):
    def test_negative_individual_share_is_rejected(self):
        bad = [{"seq": i + 1, "label": f"x{i}", "value": float(v), "unit": "倍(超)"}
               for i, v in enumerate([10.0, 3.0, -1.0, 3.0, 3.0])]
        with self.assertRaises(SolveError) as ctx:
            build_pagespec(bad, "半圆", template_name="semicircle")
        self.assertIn("C2", ctx.exception.conflicts)


if __name__ == "__main__":
    unittest.main()
