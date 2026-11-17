/**
 * 本代码支持的契约版本。对齐 `loop/contract.py::CONTRACT_VERSION`。
 *
 * 三份副本必须一致（Python 常量、本文件、`frontend/schema/pagelayout.schema.json`
 * 的 `version.enum`）；漂移由 `tests/test_step39_version_literal_sync.py` 与
 * `frontend/test/doc.test.mjs` 守着。
 *
 * 主版本是**硬闸**（P3 方案 §5 兼容矩阵 / D9）：主版本相同就敢按本代码的字段口径读；
 * 主版本不同必须明确报错，不许猜着读。
 */
export const CONTRACT_VERSION = '1.1';

/** 主版本：只比较点号前那一段。 */
export const CONTRACT_MAJOR = CONTRACT_VERSION.split('.', 1)[0];

/**
 * 本代码**认识**的契约版本（主版本相同）。
 * `'1.0'` 是 P1/P2 时代的老几何：读得进来、预览得了，但 P3 编辑器不许在它上面
 * 编辑导出（`contractCapability()` 会给出 `'preview-only'`）。
 */
export const SUPPORTED_VERSIONS = ['1.0', '1.1'];
