"""PR-C：契约版本闸门（``1.1``）与 D9 主版本硬闸。

对应 P3 技术方案 v1.4-final 的 §11.1 与 §5 兼容矩阵。四条口径：

* 缺失 ``version``（0.x 老样本）    → 宽松读 + warning，``version=None``，**不抛**
* 主版本相同、版本号不同（``1.0``） → 宽松读 + warning；读得进来、预览得了，
  P3 编辑器不许在它上面编辑导出（那是前端 ``contractCapability()`` 的事）
* 主版本不同（``2.0`` / ``10.0``）  → ``UnsupportedContractVersion``，**明确报错**
* 写出侧                          → 缺 ``version`` 才填 ``CONTRACT_VERSION``；
  已经写死的版本号原样保留（``dump_layout`` 不改写已有值）

**为什么主版本要抛而次版本不用**：次版本变的是「同一套字段口径下多认了几个键」，
按老口径读不会读错；主版本变的是字段语义本身，猜着读出来的几何是错的。
"""
import json
import os
import unittest

from loop import contract
from loop.contract import (CONTRACT_MAJOR, CONTRACT_VERSION, SUPPORTED_VERSIONS,
                           ContractError, UnsupportedContractVersion, dump_layout,
                           load_layout, load_layout_json)
from loop.schema_check import validate_doc
from tests import contract_fixtures as cf

LEGACY_PLAIN = os.path.join(cf.LEGACY_DIR, "_plain.pagelayout.json")


def _raw_legacy() -> dict:
    """入库老夹具的原始字节（0.x：没有 version / theme / images）。"""
    with open(LEGACY_PLAIN, encoding="utf-8") as fh:
        return json.load(fh)


def _valid_doc() -> dict:
    """一份过严格 schema 的当前版本文档（写出侧补完 version / theme 之后的产物）。"""
    return dump_layout(load_layout(LEGACY_PLAIN).layout)


def _with_version(version) -> dict:
    doc = _raw_legacy()
    doc["version"] = version
    return doc


class TestVersionConstants(unittest.TestCase):
    """版本号是钉死的字面量：这里再独立写一遍，常量被误改时两边对不上就红。"""

    def test_current_version_is_1_1(self):
        self.assertEqual(CONTRACT_VERSION, "1.1")
        self.assertEqual(contract.CONTRACT_VERSION, "1.1")

    def test_major_is_derived_from_the_current_version(self):
        self.assertEqual(CONTRACT_MAJOR, "1")
        self.assertEqual(contract.CONTRACT_MAJOR, CONTRACT_VERSION.split(".", 1)[0])

    def test_supported_versions_listed(self):
        self.assertEqual(tuple(SUPPORTED_VERSIONS), ("1.0", "1.1"))
        self.assertIn(CONTRACT_VERSION, SUPPORTED_VERSIONS)
        for v in SUPPORTED_VERSIONS:
            self.assertEqual(v.split(".", 1)[0], CONTRACT_MAJOR)


class TestLooseReadPaths(unittest.TestCase):

    def test_missing_version_still_reads_loosely(self):
        read = load_layout_json(_raw_legacy())
        self.assertIsNone(read.version)
        self.assertTrue(any("$.version" in w and "缺失" in w for w in read.warnings),
                        read.warnings)

    def test_older_same_major_version_reads_with_a_warning(self):
        read = load_layout_json(_with_version("1.0"))
        # 不抛：1.0 是老几何，读得进来、预览得了。
        self.assertEqual(read.version, "1.0")
        hit = [w for w in read.warnings if w.startswith("$.version:")]
        self.assertEqual(len(hit), 1, read.warnings)
        self.assertIn("1.0", hit[0])
        self.assertIn(CONTRACT_VERSION, hit[0])

    def test_current_version_reads_without_a_version_warning(self):
        read = load_layout_json(_with_version(CONTRACT_VERSION))
        self.assertEqual(read.version, CONTRACT_VERSION)
        self.assertFalse([w for w in read.warnings if w.startswith("$.version:")],
                         read.warnings)


class TestUnknownMajorIsAHardGate(unittest.TestCase):

    def test_unknown_major_raises(self):
        for version in ("2.0", "2", "10.0", 2.0, "3.1.4"):
            with self.subTest(version=version):
                with self.assertRaises(UnsupportedContractVersion) as ctx:
                    load_layout_json(_with_version(version))
                message = str(ctx.exception)
                self.assertIn("$.version", message)
                self.assertIn(repr(version), message)
                # 报错要把「本代码支持什么」讲清楚，不能只说「不认」。
                self.assertIn(CONTRACT_MAJOR, message)
                self.assertIn(CONTRACT_VERSION, message)

    def test_the_error_carries_the_evidence(self):
        with self.assertRaises(UnsupportedContractVersion) as ctx:
            load_layout_json(_with_version("2.0"))
        self.assertEqual(ctx.exception.version, "2.0")
        self.assertEqual(tuple(ctx.exception.supported), tuple(SUPPORTED_VERSIONS))

    def test_the_error_is_catchable_as_a_contract_error(self):
        # 调用方只想「契约相关的错一起接」时不必知道这个子类。
        self.assertTrue(issubclass(UnsupportedContractVersion, ContractError))
        self.assertTrue(issubclass(UnsupportedContractVersion, ValueError))


class TestWriteSideKeepsWhatIsThere(unittest.TestCase):
    """``dump_layout`` 只补**缺**的版本号，不改写已经写死的值（PR-C 的关键取舍）。"""

    def test_a_missing_version_is_filled_with_the_current_one(self):
        doc = dump_layout(load_layout_json(_raw_legacy()).layout)
        self.assertEqual(doc["version"], CONTRACT_VERSION)
        self.assertEqual(validate_doc(doc), [])

    def test_an_explicit_older_version_is_not_rewritten(self):
        read = load_layout_json(_with_version("1.0"))
        doc = dump_layout(read.layout)
        self.assertEqual(doc["version"], "1.0",
                         "老图纸往返不该被静默升版，否则「同一份 1.0」会有两种含义")
        self.assertEqual(validate_doc(doc), [])

    def test_the_current_version_survives_a_round_trip(self):
        doc = dump_layout(load_layout_json(_with_version(CONTRACT_VERSION)).layout)
        self.assertEqual(doc["version"], CONTRACT_VERSION)
        self.assertEqual(validate_doc(doc), [])


class TestSchemaDeclaresTheEnum(unittest.TestCase):
    """schema 是 Python 与 JS 共用的版本白名单，必须真的被求值（不是写着好看）。"""

    def test_schema_enum_matches_supported_versions(self):
        schema_path = os.path.join(cf.REPO_ROOT, "frontend", "schema",
                                   "pagelayout.schema.json")
        with open(schema_path, encoding="utf-8") as fh:
            schema = json.load(fh)
        node = schema["properties"]["version"]
        self.assertEqual(node.get("enum"), list(SUPPORTED_VERSIONS))
        self.assertIn(f"v{CONTRACT_VERSION}", schema["title"])

    def test_schema_check_rejects_a_version_outside_the_enum(self):
        doc = _valid_doc()
        doc["version"] = "1.2"
        paths = [e["path"] for e in validate_doc(doc)]
        self.assertIn("$.version", paths)

    def test_schema_check_accepts_both_declared_versions(self):
        for version in SUPPORTED_VERSIONS:
            with self.subTest(version=version):
                doc = _valid_doc()
                doc["version"] = version
                self.assertEqual(validate_doc(doc), [])


class TestDeliveredArtifacts(unittest.TestCase):
    """盘上的产物是生产路径的产物：重生成之后必须带当前版本号。"""

    def setUp(self):
        if not os.path.isdir(cf.DEMO_ROOT):
            cf.skip_or_fail(self,
                            "out/demo 未生成（fresh clone；先跑 scripts/build_*_demo.py）")
        self.paths = cf.demo_layout_paths()
        self.assertTrue(self.paths, "out/demo 存在时不该一份 pagelayout 都没有")

    def test_every_artifact_carries_a_version_the_code_supports(self):
        for rel in self.paths:
            with self.subTest(path=rel):
                with open(os.path.join(cf.REPO_ROOT, rel), encoding="utf-8") as fh:
                    on_disk = json.load(fh)
                self.assertIn(on_disk.get("version"), SUPPORTED_VERSIONS, rel)
                # 重新生成之后应当是当前版本；仍然是 1.0 说明产物没重跑。
                self.assertEqual(on_disk.get("version"), CONTRACT_VERSION, rel)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
