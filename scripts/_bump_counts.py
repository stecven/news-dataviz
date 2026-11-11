"""一次性脚本：把温度计元素数断言从 27 改成 37（新增 ticks/outline 各 5 个）。"""
import pathlib

EDITS = {
    "tests/test_e2e.py": [
        ('len(d["elements"]), 27', 'len(d["elements"]), 37'),
        ('len(read_shapes(out2)), 27', 'len(read_shapes(out2)), 37'),
    ],
    "tests/test_render.py": [
        ('len(read_shapes(self.pptx)), 27', 'len(read_shapes(self.pptx)), 37'),
    ],
    "tests/test_scaffold.py": [
        ('all_27_elements', 'all_37_elements'),
        ('len(spec.elements), 27', 'len(spec.elements), 37'),
        ('test_27_elements_with_unique_ids', 'test_37_elements_with_unique_ids'),
        ('len(ids), 27', 'len(ids), 37'),
        ('len(set(ids)), 27', 'len(set(ids)), 37'),
    ],
    "tests/test_step4_solve_thermometer.py": [
        ('produces_27_elements', 'produces_37_elements'),
        ('len(spec.elements), 27', 'len(spec.elements), 37'),
        ('len(shapes), 27', 'len(shapes), 37'),
        ('仍返回 27 元素', '仍返回 37 元素'),
    ],
    "tests/test_step6_atomic_and_readback.py": [
        ('len(doc["elements"]), 27', 'len(doc["elements"]), 37'),
    ],
}

for name, subs in EDITS.items():
    path = pathlib.Path(name)
    text = path.read_text(encoding="utf-8")
    for old, new in subs:
        if old not in text:
            print("MISS", name, old)
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")
print("done")
