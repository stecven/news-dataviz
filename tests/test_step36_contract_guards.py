"""P1 Task 6：V5 / V6 验收守卫。

对应验收：

* V5 前半（读得进来）：0.x 老样本 ``load_layout`` 不抛，缺键降级成 warning
                 → ``test_legacy_samples_read_loosely_with_warnings``
* V5 后半（写得出去）：任何读进来的文档 ``dump_layout`` 出来的**返回值**都过严格
                  schema、带 ``version == "1.0"``、``theme == palette.summary()``
                 → ``test_new_documents_pass_strict_schema``
* V6 Python 侧：``theme`` 不是从旧图纸抄来的，而是**当前** ``palette.py`` 的产物
                 → ``test_theme_comes_from_palette_not_from_disk``
* V6 守卫自检：扫描器对样本片段抓得住十六进制色值与写死字号（否则守卫是摆设）
                 → ``test_theme_token_scanner_catches_hex_and_font_size``
* V6 本体：``frontend/src/**/*.js`` 里除 ``theme.js`` 外不许出现色值/写死字号
                 → ``test_frontend_sources_have_no_hardcoded_theme_tokens``

两处**刻意**的写法，改之前先读 ``task-6-brief.md`` 的 T6-A / T6-B：

1. 「老样本宽松读」只认 ``tests/fixtures/contract/legacy/`` 两份冻结夹具，**不**
   对 ``demo_layout_paths()`` 断言 warning 条数 —— ``out/demo`` 会被 Task 7
   重新生成，重新生成后带上了 ``version`` / ``theme``，warning 会掉到 1—2 条。
2. 「新文档过严格 schema」断言的是 ``dump_layout`` 的**返回值**（写出侧的能力），
   不是盘上文件的字节 —— 盘上产物是否已重新生成由 Task 7 负责。
"""
import os
import unittest
from unittest import mock

from loop import palette
from loop.contract import dump_layout, load_layout
from loop.schema_check import validate_doc
from tests import contract_fixtures as cf

#: 两份入库夹具（``out/`` 不入库，它们才是长期可复现的「老格式」标本）。
LEGACY_FIXTURES = ("auto_layout.pagelayout.json", "_plain.pagelayout.json")

#: 前端读取层：它就是读 ``theme`` 的那一层，唯一允许出现色值字面量的文件。
THEME_SOURCE = "frontend/src/theme.js"


def _legacy_paths() -> list[str]:
    return [os.path.join(cf.LEGACY_DIR, name) for name in LEGACY_FIXTURES]


class TestLegacySamplesReadLoosely(unittest.TestCase):
    """V5 前半：0.x 老文档读得进来，缺什么降级成 warning，不抛。"""

    def test_legacy_samples_read_loosely_with_warnings(self):
        for path in _legacy_paths():
            with self.subTest(fixture=os.path.basename(path)):
                result = load_layout(path)  # 不抛
                self.assertGreaterEqual(
                    len(result.warnings), 1,
                    f"{path} 是 0.x 样本，应当至少有 1 条 warning")
                self.assertTrue(
                    any("version" in w for w in result.warnings),
                    f"{path} 的 warning 里应当有一条关于 version："
                    f"{result.warnings!r}")
                self.assertIsNone(result.version)

        # 现网演示稿：只要求「读得进来」。**不断言 warning 条数**（T6-A）：
        # 它们会被 Task 7 用严格写出重新生成，条数会变。
        for rel in cf.demo_layout_paths():
            with self.subTest(demo=rel):
                load_layout(os.path.join(cf.REPO_ROOT, rel))


class TestNewDocumentsWriteStrictly(unittest.TestCase):
    """V5 后半：写出侧的产物过严格 schema（断言返回值，不看盘上字节，T6-B）。"""

    def test_new_documents_pass_strict_schema(self):
        demo_paths = cf.demo_layout_paths()
        paths = _legacy_paths() + [os.path.join(cf.REPO_ROOT, rel)
                                  for rel in demo_paths]
        # fresh clone 上 ``out/`` 不存在 → demo 这一支自然为空，只剩两份夹具。
        # 这里**不** skipTest：夹具永远在，它就够证明写出侧的能力了。
        for path in paths:
            with self.subTest(path=path):
                doc = dump_layout(load_layout(path).layout)
                self.assertEqual(validate_doc(doc), [],
                                 f"{path} 写出后仍有 schema 违规")
                self.assertEqual(doc["version"], "1.0")
                self.assertEqual(doc["theme"], palette.summary())


class TestThemeSingleSource(unittest.TestCase):
    """V6：颜色与字号只有一个来源 —— ``loop/palette.py``。"""

    def test_theme_comes_from_palette_not_from_disk(self):
        path = _legacy_paths()[0]
        # 老夹具里根本没有 theme（0.x），dump 出来的 theme 只能是本地色板。
        doc = dump_layout(load_layout(path).layout)
        self.assertEqual(doc["theme"], palette.summary())

        # 改色板 → 写出的 theme 跟着变，证明它是**当前** palette 的产物。
        forged = dict(palette.summary())
        forged["palette"] = dict(forged["palette"], primary="123456")
        forged["font_sizes"] = dict(forged["font_sizes"], title=99)
        with mock.patch("loop.palette.summary", return_value=forged):
            patched = dump_layout(load_layout(path).layout)
        self.assertEqual(patched["theme"], forged)
        self.assertNotEqual(patched["theme"], palette.summary())

    def test_theme_token_scanner_catches_hex_and_font_size(self):
        snippet = "\n".join([
            'const box = { fill = "#C01F2A" };',      # 1 十六进制 6 位
            'const edge = { stroke = "#abc" };',       # 2 十六进制 3 位
            'ctx.font = "12px sans";',                 # 3 写死字号（引号在数字前）
            'style.fontSize = 14;',                    # 4 写死字号（fontSize 后跟数字）
            'const c = theme.palette.title;',          # 5 合法：从 theme 取
            'const ref = "url(#faded)";',              # 6 合法：SVG 片段引用，不是色值
            '// 走锚点 #section-anchor',                # 7 合法：不是色值
        ])
        hits = cf.find_hardcoded_theme_tokens(snippet)
        lines = [line for line, _text in hits]
        self.assertIn(1, lines)
        self.assertIn(2, lines)
        self.assertIn(3, lines)
        self.assertIn(4, lines)
        self.assertNotIn(5, lines)
        self.assertNotIn(6, lines)
        self.assertNotIn(7, lines)
        self.assertIn("#C01F2A", [text for _line, text in hits])
        self.assertIn("#abc", [text for _line, text in hits])

        # 干净片段必须是 0 命中，否则这条守卫只能靠白名单维持，很快形同虚设。
        self.assertEqual(
            cf.find_hardcoded_theme_tokens(
                'const c = theme.palette.title;\n'
                'const f = theme.font_sizes.title;\n'
                'el.style.color = c;\n'),
            [])

    def test_frontend_sources_have_no_hardcoded_theme_tokens(self):
        sources = cf.iter_js_sources()
        if not sources:
            self.skipTest("frontend/src 尚未创建（P2 才建）")

        offenders = []
        for rel in sources:
            if rel == THEME_SOURCE:  # 读取层，天然持有色值字面量
                continue
            with open(os.path.join(cf.REPO_ROOT, rel), encoding="utf-8") as fh:
                for line, text in cf.find_hardcoded_theme_tokens(fh.read()):
                    offenders.append(f"{rel}:{line}: {text}")
        if offenders:
            self.fail(
                "frontend/src 里出现了硬编码的色值/字号，请改成从 theme 取"
                f"（{len(offenders)} 处）：\n" + "\n".join(offenders))
