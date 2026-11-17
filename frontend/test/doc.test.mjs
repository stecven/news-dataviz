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
//   * `out/demo/auto_layout/pagelayout.json`（1.1 样本，fresh clone 里没有 → skip；
//     `REQUIRE_ARTIFACTS=1` 时改为直接失败，见下面的 `requireArtifacts`）
import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { ContractError, assertDoc, contractCapability, normalizeDoc } from '../src/doc.js';
import { requireArtifacts } from './helpers/golden.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, '../..');

const LEGACY_PLAIN = resolve(
  REPO_ROOT, 'tests/fixtures/contract/legacy/_plain.pagelayout.json');
const LEGACY_AUTO = resolve(
  REPO_ROOT, 'tests/fixtures/contract/legacy/auto_layout.pagelayout.json');
const DEMO_10 = resolve(REPO_ROOT, 'out/demo/auto_layout/pagelayout.json');

const HAS_DEMO = existsSync(DEMO_10);

// 严格模式（REQUIRE_ARTIFACTS=1）：缺产物直接让本文件失败，而不是整组 skip。
requireArtifacts(['out/demo/auto_layout/pagelayout.json']);

function readJson(path) {
  return JSON.parse(readFileSync(path, 'utf8'));
}

/** 深拷贝一份夹具，供“改坏它”的用例用（不许污染别的用例）。 */
function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

describe('doc: 宽松读 1.1 样本', () => {
  it.skipIf(!HAS_DEMO)('reads_version_1_1_without_warnings', () => {
    const { doc, warnings } = normalizeDoc(readJson(DEMO_10));
    expect(warnings).toEqual([]);
    expect(doc.version).toBe('1.1');
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

/**
 * 一份**最小但合法**的 1.1 图纸：`assertDoc` 必须一次通过。
 *
 * 这几条“把某处改坏”的用例要的是**区分力**——改坏前必须绿、改坏后必须红。
 * 用 `out/demo/` 的真样本最贴近现实，但它不入库（`.gitignore` 里有 `out/`），
 * fresh clone 上会走 `skipIf` 而永远不跑。夹具 `legacy/auto_layout` 虽然入库，
 * 却**本来就**过不了 `assertDoc`（缺 version / theme / images），拿它当底板
 * 的话“改坏了”和“本来就坏”分不开。
 *
 * 所以这里手工搭一份刚好卡在 `assertDoc` 的受限子集之内（必备键齐全、类型正确）
 * 的最小图纸：底板本身零错误，于是任何一条新错误都只可能来自被测的那一处改动。
 */
function minimalValidDoc() {
  return {
    version: '1.1',
    theme: { palette: { primary: 'C01F2A' }, font_sizes: { body: 11 } },
    width_in: 10,
    height_in: 6,
    margin_in: 0.4,
    gutter_in: 0.2,
    column_count: 12,
    column_gutter_in: 0.1,
    rows: [{ y_in: 0, h_in: 6 }],
    cards: [{
      x_in: 0, y_in: 0, w_in: 6.072, h_in: 3.37654,
      spec: {
        width_in: 6.072,
        height_in: 3.37654,
        chart_key: 'thermometer',
        chart_title: '示例',
        scale: { v_max: 11, h_in: 1.37, unit: '倍(超)', factor: 0.1, domain: [0, 11] },
        elements: [{
          id: 'frame', type: 'rect', role: 'frame', x_in: 0, y_in: 0, w_in: 1, h_in: 1,
        }],
      },
    }],
    blocks: [],
    images: [],
  };
}

/** 跑一次 `assertDoc`，把抛出的错误的 `.errors` 交出来（不抛就断言失败）。 */
function collectErrors(doc) {
  try {
    assertDoc(doc);
  } catch (err) {
    return err;
  }
  throw new Error('assertDoc 本应抛 ContractError，却通过了');
}

describe('doc: 严格校验', () => {
  it('assert_doc_throws_on_empty_object_with_path', () => {
    expect(() => assertDoc({})).toThrow(/\$\.width_in/);
  });

  it('minimal_valid_doc_passes', () => {
    // 下面那组“改坏一处”的用例全靠这份底板；底板自己不绿，那组就毫无区分力。
    expect(() => assertDoc(minimalValidDoc())).not.toThrow();
  });

  // ---- A：数值键的 null 不许被静默接受 ----
  //
  // schema 里坐标/尺寸键声明的是 `{"type": "number"}`，**不是** `["number","null"]`
  // （19 个可空节点里不含任何坐标/尺寸键：真正可空的只有 version / theme /
  // content_bbox / frame_bbox / chart / fill / text / binding / geometry_expr /
  // geometry / image_path / lines / font_pt / editable / scale.factor /
  // scale.domain / image.asset_id / image.tag / image.semantic）。
  // Python 侧对 `x_in: null` 报 `expected number, got null`，JS 侧必须同口径。
  it('assert_doc_rejects_null_element_coordinate', () => {
    const bad = minimalValidDoc();
    bad.cards[0].spec.elements[0].x_in = null;
    const err = collectErrors(bad);
    expect(err).toBeInstanceOf(ContractError);
    const hit = err.errors.find((e) => e.path === '$.cards[0].spec.elements[0].x_in');
    expect(hit, `errors=${JSON.stringify(err.errors)}`).toBeTruthy();
    expect(hit.message).toContain('expected number');
    expect(hit.message).toContain('null');
  });

  it('assert_doc_rejects_null_top_level_number', () => {
    const bad = minimalValidDoc();
    bad.width_in = null;
    const err = collectErrors(bad);
    const hit = err.errors.find((e) => e.path === '$.width_in');
    expect(hit, `errors=${JSON.stringify(err.errors)}`).toBeTruthy();
    expect(hit.message).toContain('expected number');
  });

  // ---- B：spec.scale 的子结构（schema 的 $defs.scale）----
  //
  // `SPEC_REQUIRED` 以前只把 `scale` 当存在性键，从不递归它，于是
  // scale='oops' / scale=null / scale={} / 删 unit / 删 v_max / h_in='x'
  // 六种在 Python 侧全报错、JS 侧全放行。schema 明确：
  // required=['v_max','h_in','unit']，v_max/h_in 是 number，unit 是 string。
  it('assert_doc_rejects_non_object_spec_scale', () => {
    const bad = minimalValidDoc();
    bad.cards[0].spec.scale = 'oops';
    const err = collectErrors(bad);
    const hit = err.errors.find((e) => e.path === '$.cards[0].spec.scale');
    expect(hit, `errors=${JSON.stringify(err.errors)}`).toBeTruthy();
    expect(hit.message).toContain('expected dict');
  });

  it('assert_doc_rejects_null_spec_scale', () => {
    const bad = minimalValidDoc();
    bad.cards[0].spec.scale = null;
    const err = collectErrors(bad);
    const hit = err.errors.find((e) => e.path === '$.cards[0].spec.scale');
    expect(hit, `errors=${JSON.stringify(err.errors)}`).toBeTruthy();
    expect(hit.message).toContain('expected dict');
    expect(hit.message).toContain('null');
  });

  it('assert_doc_rejects_spec_scale_missing_unit', () => {
    const bad = minimalValidDoc();
    delete bad.cards[0].spec.scale.unit;
    const err = collectErrors(bad);
    const hit = err.errors.find((e) => e.path === '$.cards[0].spec.scale.unit');
    expect(hit, `errors=${JSON.stringify(err.errors)}`).toBeTruthy();
    expect(hit.message).toBe('required key is missing');
  });

  it('assert_doc_rejects_spec_scale_non_numeric_v_max', () => {
    const bad = minimalValidDoc();
    bad.cards[0].spec.scale.v_max = 'x';
    const err = collectErrors(bad);
    const hit = err.errors.find((e) => e.path === '$.cards[0].spec.scale.v_max');
    expect(hit, `errors=${JSON.stringify(err.errors)}`).toBeTruthy();
    expect(hit.message).toContain('expected number');
  });

  it.skipIf(!HAS_DEMO)('assert_doc_passes_a_real_1_1_document', () => {
    // 真实 1.1 样本必须一次通过 —— 否则渲染库“读得进但校验不过”，那才是灾难。
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

describe('doc: 契约版本闸门（D9 / P3 方案 §5 兼容矩阵）', () => {
  it('contract_capability_maps_every_case', () => {
    // 判定点只有这一个函数，四种能力各钉一条，P3 的编辑/导出闸门照它开关。
    expect(contractCapability('1.1')).toBe('current');
    expect(contractCapability('1.0')).toBe('preview-only');
    expect(contractCapability('1.2')).toBe('preview-only');
    expect(contractCapability(null)).toBe('legacy');
    expect(contractCapability(undefined)).toBe('legacy');
    expect(contractCapability('2.0')).toBe('unsupported');
    // 前缀比较不是「看起来像 1」就算数：'10.0' 的主版本是 '10'。
    expect(contractCapability('10.0')).toBe('unsupported');
  });

  it('assert_doc_accepts_the_older_1_0_geometry', () => {
    // 1.0 是 P1/P2 时代的老几何：读得进来、校验得过、预览得了，
    // 只是 P3 不许在它上面编辑导出（那是 contractCapability 的事）。
    const old = minimalValidDoc();
    old.version = '1.0';
    expect(() => assertDoc(old)).not.toThrow();
  });

  it('assert_doc_rejects_an_unknown_major_version', () => {
    const bad = minimalValidDoc();
    bad.version = '2.0';
    const err = collectErrors(bad);
    expect(err).toBeInstanceOf(ContractError);
    const hit = err.errors.find((e) => e.path === '$.version');
    expect(hit, `errors=${JSON.stringify(err.errors)}`).toBeTruthy();
    expect(hit.message).toContain('unsupported major version');
    expect(hit.message).toContain('2.0');
  });

  it('normalize_doc_warns_loudly_but_does_not_throw_on_an_unknown_major', () => {
    // 宽松读这一层的契约是「不抛」：它只把话说重，硬闸留给 assertDoc。
    const raw = minimalValidDoc();
    raw.version = '2.0';
    const { doc, warnings } = normalizeDoc(raw);
    expect(doc.version).toBe('2.0');   // 如实反映，不改写、不伪造
    expect(warnings.some((w) => w.includes('主版本不认识'))).toBe(true);
  });
});

describe('doc: normalizeDoc 与 assertDoc 的关系', () => {
  it('normalize_does_not_assert', () => {
    // 宽松读**不**做严格校验：老样本能读进来是特性，不是漏网。
    expect(() => normalizeDoc(readJson(LEGACY_PLAIN))).not.toThrow();
    expect(() => assertDoc(readJson(LEGACY_PLAIN))).toThrow();
  });
});
