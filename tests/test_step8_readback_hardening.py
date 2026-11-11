"""复审第二轮（FOCUSED RE-REVIEW: Needs fixes）—— 更深一层的读回校验加固。

上一轮把「声明行驱动 / 半圆数据链接 / 布局 override」修好了，但复审发现
读回校验仍有多处「只查一部分」的漏洞：

  I1 C6 的 d 公式从未重新推导（只查等距 + 首柱在 margin）
  I2 Σθ = arc_total 从未断言（factor 减半 → Σθ=90 仍通过）
  I3 图例间距只查「彼此相等」，未绑定 h_legend+gap_legend
  I4 top_reserve 自报，未断言 == m+h_title+gap_title+h_note+gap_note，
     也未断言扇区 y_in >= top_reserve
  I5 非 dict 约束行 / scale=None 漏出原始 AttributeError
  I6 SolveError.__str__ 在冲突 id 为 None 时崩
  I7 删掉图元（zip 截断）会静默关闭检查

期望值全部手算字面量。
"""
import unittest

from loop.data_source import DB_PATH, load_points
from loop.scaffold import build_pagespec
from loop.solve import SolveError, validate_spec

PTS = load_points(DB_PATH)[1]


def _thermo(**kw):
    return build_pagespec(PTS, "温度计", **kw)


def _semi(**kw):
    return build_pagespec(PTS, "半圆", template_name="semicircle", **kw)


def _role(spec, role):
    return [e for e in spec.elements if e.role == role]


def _move_bank(spec, i, delta):
    """把第 i 支温度计的**整组**图元一起水平平移。

    皮肤图元（m02273）也是这一组的一部分：`ticks`/`outline` 的盒跟着动，
    `outline.geometry.cx` 也要一起动，否则 C4 的皮肤重推会先于 C6 触发。
    """
    for role in ("track", "liquid", "bulb", "label", "value", "ticks", "outline"):
        _role(spec, role)[i].x_in += delta
    o = _role(spec, "outline")[i]
    o.geometry = dict(o.geometry or {})
    o.geometry["cx"] = o.geometry["cx"] + delta


# ---------------------------------------------------------------------------
# I1：C6 的 d 必须由公式重新推导，而不只是「等距」+「首柱在 margin」
# ---------------------------------------------------------------------------
class TestC6SpacingFormula(unittest.TestCase):
    def test_crowded_tracks_reoderived_d_is_rejected(self):
        # 手算 d = (W−2m−w_track)/(n−1) = (10−1−0.28)/4 = 2.18（> gap_min 0.5）。
        # 把整组（管身 + 液柱 + 球泡 / 标签 / 真值 + 皮肤）一起按新 pitch=0.01 压缩，
        # 这样 C4/C5 仍然成立，唯一被违反的必须是 C6 的 d 公式。
        spec = _thermo()
        pitch = 0.01
        for i, t in enumerate(_role(spec, "track")):
            delta = (0.5 + i * pitch) - t.x_in
            _move_bank(spec, i, delta)
        with self.assertRaises(SolveError) as ctx:
            validate_spec(spec)
        self.assertIn("C6", ctx.exception.conflicts)

    def test_whole_spec_shift_is_rejected(self):
        # 平移 0.02 in：仍在画布内（label_5 右缘 9.96），确保拒绝理由来自 C6。
        spec = _thermo()
        for e in spec.elements:
            e.x_in += 0.02
        for o in _role(spec, "outline"):
            o.geometry = dict(o.geometry or {})
            o.geometry["cx"] = o.geometry["cx"] + 0.02
        with self.assertRaises(SolveError) as ctx:
            validate_spec(spec)
        self.assertIn("C6", ctx.exception.conflicts)


# ---------------------------------------------------------------------------
# I2：Σθ 必须等于 arc_total，且 factor == arc_total / Σv
# ---------------------------------------------------------------------------
class TestArcTotalClosure(unittest.TestCase):
    def test_halved_factor_with_recomputed_angles_is_rejected(self):
        spec = _semi()
        half = spec.scale.factor / 2.0
        spec.scale.factor = half
        a = 180.0
        for e in _role(spec, "sector"):
            th = half * e.binding["value"]
            e.geometry["start_angle"] = a
            e.geometry["theta"] = th
            e.geometry["end_angle"] = a + th
            a += th
        with self.assertRaises(SolveError):
            validate_spec(spec)

    def test_scale_h_in_must_equal_arc_total(self):
        spec = _semi()
        spec.scale.h_in = 999.0
        with self.assertRaises(SolveError):
            validate_spec(spec)


# ---------------------------------------------------------------------------
# I3 / I4：图例间距绑定参数；top_reserve 必须可复算且不压文字
# ---------------------------------------------------------------------------
class TestLegendPitchAndTopReserve(unittest.TestCase):
    def test_repitched_legends_are_rejected(self):
        # 合法 pitch = h_legend + gap_legend = 0.3 + 0.1 = 0.4。
        # 改成 0.15 会让框互相重叠，必须拒。
        spec = _semi()
        for i, e in enumerate(_role(spec, "legend")):
            e.y_in = 1.65 + i * 0.15
        with self.assertRaises(SolveError) as ctx:
            validate_spec(spec)
        self.assertIn("C4", ctx.exception.conflicts)

    def test_top_reserve_must_match_its_components(self):
        # 手算 top_reserve = 0.5+0.5+0.15+0.3+0.2 = 1.65；改成 0.6 也必须拒。
        spec = _semi()
        spec.layout["top_reserve"] = 0.6
        with self.assertRaises(SolveError):
            validate_spec(spec)

    def test_sector_must_not_overlap_title_band(self):
        # 扇区盒顶必须 >= top_reserve（否则压在标题/量程说明上）。
        spec = _semi()
        for s in _role(spec, "sector"):
            s.y_in = 0.5
        with self.assertRaises(SolveError):
            validate_spec(spec)


# ---------------------------------------------------------------------------
# I5 / I6：畸形规格必须抛 SolveError，不能漏原始异常 / 不能崩在 str()
# ---------------------------------------------------------------------------
class TestMalformedSpecs(unittest.TestCase):
    def test_non_dict_constraint_row_raises_solveerror(self):
        spec = _thermo()
        spec.constraints = ["C1"]
        with self.assertRaises(SolveError):
            validate_spec(spec)

    def test_scale_none_raises_solveerror(self):
        spec = _thermo()
        spec.scale = None
        with self.assertRaises(SolveError):
            validate_spec(spec)

    def test_empty_constraint_row_str_does_not_crash(self):
        spec = _thermo()
        spec.constraints = [{}]
        try:
            validate_spec(spec)
        except SolveError as ex:
            str(ex)          # 不得再抛 TypeError

    def test_duplicate_constraint_rows_are_rejected(self):
        spec = _thermo()
        spec.constraints = spec.constraints + [dict(spec.constraints[0])]
        with self.assertRaises(SolveError):
            validate_spec(spec)


# ---------------------------------------------------------------------------
# I7：删除图元不能让检查被 zip 截断静默关闭
# ---------------------------------------------------------------------------
class TestElementCountIntegrity(unittest.TestCase):
    def test_missing_bulb_is_rejected(self):
        spec = _thermo()
        spec.elements = [e for e in spec.elements if e.id != "bulb_5"]
        with self.assertRaises(SolveError):
            validate_spec(spec)

    def test_missing_legend_is_rejected(self):
        spec = _semi()
        spec.elements = [e for e in spec.elements if e.id != "legend_5"]
        with self.assertRaises(SolveError):
            validate_spec(spec)

    def test_missing_sector_is_rejected(self):
        spec = _semi()
        spec.elements = [e for e in spec.elements if e.id != "sector_5"]
        with self.assertRaises(SolveError):
            validate_spec(spec)


if __name__ == "__main__":
    unittest.main()
