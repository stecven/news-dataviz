"""D.2 steps 4/5 —— 原子写 pagespec.json + 无解不落盘 + 读回约束校验。

用户点名的失败路径 3：约束无解时 pagespec.json 不落盘（先解完再写）。
D.2 步骤 4：原子写；字段分工 constraints / geometry_expr / x_in.. 三者留痕。
D.2 步骤 5：from_dict → render_from_spec 前再跑一次约束校验（幂等、不改坐标）。

所有期望值都是手算 / 结构字面量，不调用被测代码推导。
"""
import json
import os
import unittest

from loop.build_loop import build_loop, write_pagespec_atomic
from loop.models import PageSpec
from loop.solve import SolveError, validate_spec

FRESH = lambda: __import__("tests.scratch", fromlist=["mkdtemp"]).mkdtemp(prefix="step6-")


def _tmp_files(d):
    return [f for f in os.listdir(d) if ".tmp" in f]


def _read_bytes(p):
    with open(p, "rb") as f:
        return f.read()


def _by_id(spec, eid):
    return next(e for e in spec.elements if e.id == eid)


# ---------------------------------------------------------------------------
# D.2 步骤 4：原子写 + 字段分工三者留痕
# ---------------------------------------------------------------------------
class TestAtomicWrite(unittest.TestCase):
    def test_build_loop_writes_valid_json_and_leaves_no_tmp_file(self):
        d = FRESH()
        r = build_loop(d)
        with open(r["pagespec"], encoding="utf-8") as f:
            doc = json.load(f)
        self.assertEqual(doc["scale"]["v_max"], 11.0)
        self.assertEqual(len(doc["elements"]), 39)   # 37 内容 + frame + title_band
        self.assertEqual(_tmp_files(d), [], "原子写后残留 .tmp 文件")

    def test_pagespec_json_records_all_three_field_layers(self):
        # constraints 存声明 / geometry_expr 存表达式 / x_in.. 存求解结果。
        d = FRESH()
        r = build_loop(d)
        with open(r["pagespec"], encoding="utf-8") as f:
            doc = json.load(f)
        self.assertTrue(doc["constraints"], "constraints 缺失")
        self.assertTrue(doc["layout"], "layout 缺失")
        liq = next(e for e in doc["elements"] if e["id"] == "liquid_1")
        self.assertIn("scale.factor", liq["geometry_expr"])
        self.assertIn("binding.value", liq["geometry_expr"])
        self.assertNotEqual(liq["x_in"], 0.0, "x_in 应是求解结果，不是骨架 0")
        self.assertGreater(liq["h_in"], 0.0, "h_in 应是求解结果")
        self.assertIn("满格约 11倍", doc["elements"][3]["text"])  # scale_note（读者文案）

    def test_write_pagespec_atomic_overwrites_cleanly(self):
        # 第二次原子写必须完整替换，不残留第一次的内容碎屑、不残留 .tmp。
        d = FRESH()
        p = os.path.join(d, "pagespec.json")
        write_pagespec_atomic(p, {"mark": "FIRST", "elements": [{"id": "a"}]})
        write_pagespec_atomic(p, {"mark": "SECOND", "elements": []})
        with open(p, encoding="utf-8") as f:
            doc = json.load(f)
        self.assertEqual(doc["mark"], "SECOND")
        self.assertEqual(doc["elements"], [])
        self.assertNotIn(b"FIRST", _read_bytes(p))
        self.assertEqual(_tmp_files(d), [])

    def test_write_pagespec_atomic_cleans_tmp_on_serialization_failure(self):
        # json.dump 失败时不得留下 .tmp，也不得破坏已有文件。
        d = FRESH()
        p = os.path.join(d, "pagespec.json")
        write_pagespec_atomic(p, {"ok": 1})
        before = _read_bytes(p)
        with self.assertRaises(TypeError):
            write_pagespec_atomic(p, {"bad": {1, 2, 3}})   # set 不可序列化
        self.assertEqual(_tmp_files(d), [], "失败后残留 .tmp")
        self.assertEqual(_read_bytes(p), before, "失败破坏了已有文件")


# ---------------------------------------------------------------------------
# 失败路径 3（用户点名）：无解不落盘
# ---------------------------------------------------------------------------
class TestFailurePath3NoSolutionWritesNoFile(unittest.TestCase):
    def test_no_solution_writes_no_pagespec_no_tmp_no_render(self):
        # gap_min=3.0 → d=3.0 → 总宽 4×3+0.5=12.5 > W−2m=9.0 → C1+C6 无解。
        d = FRESH()
        with self.assertRaises(SolveError) as ctx:
            build_loop(d, param_overrides={"gap_min": 3.0})
        self.assertIn("C1", ctx.exception.conflicts)
        self.assertIn("C6", ctx.exception.conflicts)
        self.assertFalse(os.path.exists(os.path.join(d, "pagespec.json")),
                         "无解却落盘了 pagespec.json")
        self.assertEqual(_tmp_files(d), [])
        self.assertFalse(os.path.exists(os.path.join(d, "loop1.pptx")))
        self.assertFalse(os.path.exists(os.path.join(d, "preview.png")))

    def test_no_solution_does_not_clobber_an_existing_pagespec(self):
        # 先成功写一次，再让同目录求解失败：原 pagespec.json 字节必须不变。
        d = FRESH()
        build_loop(d)
        p = os.path.join(d, "pagespec.json")
        before = _read_bytes(p)
        with self.assertRaises(SolveError):
            build_loop(d, param_overrides={"gap_min": 3.0})
        self.assertEqual(_read_bytes(p), before,
                         "失败时覆盖了上一次成功的规格")


# ---------------------------------------------------------------------------
# D.2 步骤 5：读回约束校验（幂等、不改坐标）
# ---------------------------------------------------------------------------
class TestReadbackValidation(unittest.TestCase):
    def test_validate_spec_is_idempotent_and_does_not_change_coordinates(self):
        r = build_loop(FRESH())
        spec = r["spec"]
        before = spec.to_dict()
        validate_spec(spec)            # 再跑一次约束校验
        self.assertEqual(spec.to_dict(), before, "校验改动了坐标 / 破坏了幂等")

    def test_validate_spec_accepts_both_templates(self):
        from loop.scaffold import build_pagespec
        _, pts = __import__("loop.data_source", fromlist=["load_points"]).load_points(
            __import__("loop.data_source", fromlist=["DB_PATH"]).DB_PATH)
        for name in ("thermometer", "semicircle"):
            with self.subTest(template=name):
                spec = build_pagespec(pts, "标题", template_name=name)
                validate_spec(spec)     # 不抛即通过

    def test_validate_spec_rejects_out_of_bounds_element(self):
        # 人工把某元素推到画布外 → C1 校验应拒绝。
        from loop.frame import unwrap
        r = build_loop(FRESH())
        # C1 的坐标系是**内容画布**：包框后的 x_in 是卡片坐标，得先拆框再篡改，
        # 否则会先撞上 chrome 的 content_bbox 一致性检查（那不是 C1 的职责）。
        spec = unwrap(r["spec"])
        _by_id(spec, "track_1").x_in = 20.0
        with self.assertRaises(SolveError) as ctx:
            validate_spec(spec)
        self.assertIn("C1", ctx.exception.conflicts)

    def test_validate_spec_rejects_liquid_height_drifted_from_expression(self):
        # 声明式链接 h_in = scale.factor × binding.value 不再成立 → 拒绝。
        # 取 1.0 仍满足 C1（不出界），故触发的必须是 DATA/C2 链接校验。
        r = build_loop(FRESH())
        spec = r["spec"]
        _by_id(spec, "liquid_1").h_in = 1.0
        with self.assertRaises(SolveError) as ctx:
            validate_spec(spec)
        self.assertTrue(ctx.exception.conflicts)
        self.assertTrue({"DATA", "C2"} & set(ctx.exception.conflicts))

    def test_build_loop_readback_validation_is_wired(self):
        # 由 build_loop 写出的 JSON 读回后能通过 validate_spec（磁盘规格是唯一渲染源）。
        r = build_loop(FRESH())
        with open(r["pagespec"], encoding="utf-8") as f:
            disk = PageSpec.from_dict(json.load(f))
        validate_spec(disk)            # 不抛


if __name__ == "__main__":
    unittest.main()
