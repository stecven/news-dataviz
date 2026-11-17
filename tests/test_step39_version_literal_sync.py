"""PR-C：契约版本号的**单一事实来源守卫**。

``CONTRACT_VERSION`` 在仓里有好几份副本，分散在两种语言、四个文件里：

======================  ==================================================
位置                     形态
======================  ==================================================
``loop/contract.py``     ``CONTRACT_VERSION = "1.1"``（Python 权威常量）
``frontend/src/version.js``  ``export const CONTRACT_VERSION = '1.1';``
``frontend/schema/pagelayout.schema.json``  ``properties.version.enum``
``tests/test_step37_contract_delivery.py``  ``EXPECTED_CONTRACT_VERSION``
``frontend/test/doc.test.mjs``  ``minimalValidDoc().version``
======================  ==================================================

它们**没有**生成器（P1 的取舍：不引入模板/生成步骤），所以只能靠一条守卫测试
把它们钉在一起。这里刻意用**正则从文件正文里抠字面量**、而不是 import 常量来比：
import 进来比是「自己等于自己」，改一处就跟着变，等于没守。

顺带钉住两条跨端口径：``frontend/src/version.js`` 的 ``CONTRACT_MAJOR`` 与
``SUPPORTED_VERSIONS`` 也要和 Python 侧一致，且 schema 的 enum 必须与
``SUPPORTED_VERSIONS`` 逐项相等（否则 Python 写得出、JS 认不得，或反过来）。
"""
import json
import os
import re
import unittest

from loop.contract import CONTRACT_MAJOR, CONTRACT_VERSION, SUPPORTED_VERSIONS
from tests import contract_fixtures as cf

FRONTEND = os.path.join(cf.REPO_ROOT, "frontend")
VERSION_JS = os.path.join(FRONTEND, "src", "version.js")
DOC_JS = os.path.join(FRONTEND, "src", "doc.js")
SCHEMA_JSON = os.path.join(FRONTEND, "schema", "pagelayout.schema.json")
CONTRACT_PY = os.path.join(cf.REPO_ROOT, "loop", "contract.py")
STEP37_PY = os.path.join(cf.REPO_ROOT, "tests", "test_step37_contract_delivery.py")
DOC_TEST_MJS = os.path.join(FRONTEND, "test", "doc.test.mjs")


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _extract(pattern: str, text: str, what: str) -> str:
    match = re.search(pattern, text, re.MULTILINE)
    if match is None:
        raise AssertionError(f"{what}: 抠不到版本字面量（正则 {pattern!r}）")
    return match.group(1)


class TestEveryCopyAgrees(unittest.TestCase):

    def test_python_constant_matches_this_test_module(self):
        # 独立字面量：``loop/contract.py`` 被改成别的值时这里必须红。
        self.assertEqual(
            _extract(r'^CONTRACT_VERSION = "([^"]+)"', _read(CONTRACT_PY),
                     "loop/contract.py"),
            CONTRACT_VERSION)

    def test_frontend_version_js_agrees(self):
        source = _read(VERSION_JS)
        self.assertEqual(
            _extract(r"export const CONTRACT_VERSION = '([^']+)';", source,
                     "frontend/src/version.js"),
            CONTRACT_VERSION)
        self.assertEqual(
            _extract(r"export const CONTRACT_MAJOR = ([^;]+);", source,
                     "frontend/src/version.js").strip(),
            # 源码里是拼出来的表达式，抠出来后按同样的算法在 Python 里算一遍。
            "CONTRACT_VERSION.split('.', 1)[0]")
        self.assertEqual(
            _extract(r"export const SUPPORTED_VERSIONS = \[([^\]]+)\];", source,
                     "frontend/src/version.js").strip(),
            ", ".join(f"'{v}'" for v in SUPPORTED_VERSIONS))

    def test_delivery_test_constant_agrees(self):
        self.assertEqual(
            _extract(r'^EXPECTED_CONTRACT_VERSION = "([^"]+)"', _read(STEP37_PY),
                     "tests/test_step37_contract_delivery.py"),
            CONTRACT_VERSION)

    def test_frontend_minimal_valid_doc_agrees(self):
        self.assertEqual(
            _extract(r"^\s*version: '([^']+)',", _read(DOC_TEST_MJS),
                     "frontend/test/doc.test.mjs"),
            CONTRACT_VERSION)

    def test_doc_js_has_no_version_literal_of_its_own(self):
        # doc.js 只能**引用** version.js；自己再赋值一次就又多出一份事实来源。
        # （注释里提到 `'1.0'` 无妨，所以这里查的是「赋值」而不是「出现过」。）
        source = _read(DOC_JS)
        self.assertIn("from './version.js'", source)
        self.assertNotRegex(source, r"CONTRACT_VERSION\s*=")
        self.assertNotRegex(source, r"CONTRACT_MAJOR\s*=")


class TestSchemaAndPythonAgree(unittest.TestCase):

    def setUp(self):
        with open(SCHEMA_JSON, encoding="utf-8") as fh:
            self.schema = json.load(fh)

    def test_enum_equals_the_supported_list(self):
        node = self.schema["properties"]["version"]
        self.assertEqual(node.get("enum"), list(SUPPORTED_VERSIONS))

    def test_title_carries_the_current_version(self):
        self.assertIn(f"v{CONTRACT_VERSION}", self.schema["title"])

    def test_version_is_the_declared_major(self):
        for version in self.schema["properties"]["version"]["enum"]:
            with self.subTest(version=version):
                self.assertEqual(version.split(".", 1)[0], CONTRACT_MAJOR)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
