// doc.js 的口径测试。
//
// 读图纸分两条路（对齐 `loop/contract.py`）：
//   * **宽松读** `normalizeDoc` —— 0.x 老样本缺 `version` / `theme` / `images`
//     照样读得进来，缺什么降级成一条 warning，**不抛**；
//   * **严格校验** `assertDoc` —— 写出侧 / 消费端的门槛，结构不对就抛，
//     错误消息带 JSONPath 风格路径（对齐 `loop/schema_check.py` 的习惯）。
//
// 夹具：
//   * `tests/fixtures/contract/legacy/_plain.pagelayout.json`（入库，永远在）
//   * `tests/fixtures/contract/legacy/auto_layout.pagelayout.json`（入库，永远在）
//   * `out/demo/auto_layout/pagelayout.json`（1.0 样本，fresh clone 里没有 → skip）
import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { assertDoc, normalizeDoc } from '../src/doc.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, '../..');

const LEGACY_PLAIN = resolve(
  REPO_ROOT, 'tests/fixtures/contract/legacy/_plain.pagelayout.json');
const LEGACY_AUTO = resolve(
  REPO_ROOT, 'tests/fixtures/contract/legacy/auto_layout.pagelayout.json');
const DEMO_10 = resolve(REPO_ROOT, 'out/demo/auto_layout/pagelayout.json');

const HAS_DEMO = existsSync(DEMO_10);

function readJson(path) {
  return JSON.parse(readFileSync(path, 'utf8'));
}

/** 深拷贝一份夹具，供“改坏它”的用例用（不许污染别的用例）。 */
function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

describe('doc: 宽松读 1.0 样本', () => {
  it.skipIf(!HAS_DEMO)('reads_version_1_0_without_warnings', () => {
    const { doc, warnings } = normalizeDoc(readJson(DEMO_10));
    expect(warnings).toEqual([]);
    expect(doc.version).toBe('1.0');
  });

  it.skipIf(!HAS_DEMO)('keeps_all_twelve_top_level_keys', () => {
    const { doc } = normalizeDoc(readJson(DEMO_10));
    expect(Object.keys(doc).sort()).toEqual([
      'blocks', 'cards', 'column_count', 'column_gutter_in', 'gutter_in',
      'height_in', 'images', 'margin_in', 'rows', 'theme', 'version', 'width_in',
    ]);
  });
});

describe('doc: 宽松读 0.x 老样本', () => {
  it('reads_legacy_plain_with_three_warnings', () => {
    const { doc, warnings } = normalizeDoc(readJson(LEGACY_PLAIN));
    // 不抛，且缺的三键各降级成一条 warning（路径分得开，不是一句笼统的“缺字段”）。
    expect(warnings.length).toBe(3);
    expect(warnings.some((w) => w.includes('$.version'))).toBe(true);
    expect(warnings.some((w) => w.includes('$.theme'))).toBe(true);
    expect(warnings.some((w) => w.includes('$.images'))).toBe(true);
    // 老样本没有 version，读出来是 null（对齐 ReadResult.version）。
    expect(doc.version).toBeNull();
  });

  it('reads_legacy_auto_layout_with_three_warnings', () => {
    const { doc, warnings } = normalizeDoc(readJson(LEGACY_AUTO));
    expect(warnings.length).toBe(3);
    expect(doc.version).toBeNull();
    expect(doc.cards.length).toBe(2);
    expect(doc.blocks.length).toBe(4);
  });

  it('fills_missing_images_with_empty_array', () => {
    // P1 实测有 6 份老样本没有 images 键：兜底成 []，调用方不必到处判 nil。
    const { doc } = normalizeDoc(readJson(LEGACY_PLAIN));
    expect(doc.images).toEqual([]);
  });

  it('fills_missing_rows_with_empty_array', () => {
    const raw = clone(readJson(LEGACY_PLAIN));
    delete raw.rows;
    const { doc, warnings } = normalizeDoc(raw);
    expect(doc.rows).toEqual([]);
    // rows 缺失不属于 0.x 的三处已知缺口，但它同样是“缺就降级”，要出声。
    expect(warnings.some((w) => w.includes('$.rows'))).toBe(true);
  });

  it('does_not_mutate_the_input', () => {
    const raw = readJson(LEGACY_PLAIN);
    const before = JSON.stringify(raw);
    normalizeDoc(raw);
    expect(JSON.stringify(raw)).toBe(before);
  });
});

describe('doc: 严格校验', () => {
  it('assert_doc_throws_on_empty_object_with_path', () => {
    expect(() => assertDoc({})).toThrow(/\$\.width_in/);
  });

  it.skipIf(!HAS_DEMO)('assert_doc_passes_a_real_1_0_document', () => {
    // 真实 1.0 样本必须一次通过 —— 否则渲染库“读得进但校验不过”，那才是灾难。
    expect(() => assertDoc(readJson(DEMO_10))).not.toThrow();
  });

  it.skipIf(!HAS_DEMO)('assert_doc_reports_element_level_path', () => {
    const bad = clone(readJson(DEMO_10));
    bad.cards[0].spec.elements[0].x_in = 'not-a-number';
    let message = '';
    try {
      assertDoc(bad);
    } catch (err) {
      message = err.message;
    }
    // 路径要精确到元素级的坐标字段，不是笼统的“cards 有问题”。
    expect(message).toContain('$.cards[0].spec.elements[0].x_in');
  });

  it.skipIf(!HAS_DEMO)('assert_doc_reports_unknown_element_type', () => {
    const bad = clone(readJson(DEMO_10));
    bad.cards[0].spec.elements[0].type = 'hexagon';
    expect(() => assertDoc(bad)).toThrow(/hexagon/);
  });

  it.skipIf(!HAS_DEMO)('assert_doc_catches_wrong_type_for_cards', () => {
    const bad = clone(readJson(DEMO_10));
    bad.cards = 'not-an-array';
    expect(() => assertDoc(bad)).toThrow(/\$\.cards/);
  });
});

describe('doc: normalizeDoc 与 assertDoc 的关系', () => {
  it('normalize_does_not_assert', () => {
    // 宽松读**不**做严格校验：老样本能读进来是特性，不是漏网。
    expect(() => normalizeDoc(readJson(LEGACY_PLAIN))).not.toThrow();
    expect(() => assertDoc(readJson(LEGACY_PLAIN))).toThrow();
  });
});
