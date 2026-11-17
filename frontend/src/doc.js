// 图纸读取层：`pagelayout.json` 的**宽松读**与**严格校验**。
//
// 两条路刻意分开，对齐 `loop/contract.py` / `loop/schema_check.py`：
//
//   * `normalizeDoc` —— 宽松读。0.x 老样本缺 `version` / `theme` / `images`
//     照样读得进来，缺什么降级成一条 warning，**不抛**。读旧图纸不该被当成
//     写错图纸。
//   * `assertDoc` —— 严格校验。消费端（渲染器）的门槛：结构不对就抛，错误
//     消息带 JSONPath 风格路径（`$.cards[0].spec.elements[3].x_in`），对齐
//     `loop/schema_check.py` 的口径。
//
// **已知偏差（契约 §5.7 的受限子集）**：这里只查“必备键存在 + 基本类型 +
// 元素类型枚举”，**不实现 JSON Schema 求值**（不读 `frontend/schema/*.json`、
// 不解释 `$ref` / `minimum` / `additionalProperties`）。理由是 v1 的校验需求
// 就这么小：一个契约、一个消费端，把 schema 求值器搬进浏览器只会多一处两边
// 行为不一致的地方（写出一侧仍由 Python 的 `validate_doc` 把关）。
import { CONTRACT_MAJOR, CONTRACT_VERSION, SUPPORTED_VERSIONS } from './version.js';

/** 结构不符时抛的错误。`errors` 是 `[{path, message}]`，与 Python 同形。 */
export class ContractError extends Error {
  constructor(errors) {
    const head = errors.slice(0, 5)
      .map((e) => `${e.path}: ${e.message}`)
      .join('; ');
    super(`${errors.length} 处不符合契约（前 5 条）：${head}`);
    this.name = 'ContractError';
    this.errors = errors;
  }
}

/** 版本号的主版本（点号前那一段）。判不出（非字符串）就当不认识。 */
function majorOf(version) {
  return String(version).split('.', 1)[0];
}

/**
 * 这份图纸的版本能拿来干什么 —— P3 方案 §5 兼容矩阵的**唯一**判定点。
 *
 *   * `'current'`      —— 本代码的当前版本：可读、可预览、可编辑、可导出
 *   * `'preview-only'` —— 主版本相同但版本号不是当前值（含 `'1.0'` 老几何）：
 *                          可读、可预览，**P3 编辑器不许在它上面编辑导出**
 *   * `'legacy'`       —— 没有版本号（0.x 老样本）：同上，只读可预览
 *   * `'unsupported'`  —— 主版本不认识：字段口径可能整体变过，明确报错
 *
 * @param {string|null|undefined} version
 * @returns {'current'|'preview-only'|'legacy'|'unsupported'}
 */
export function contractCapability(version) {
  if (version == null) return 'legacy';
  if (majorOf(version) !== CONTRACT_MAJOR) return 'unsupported';
  return version === CONTRACT_VERSION ? 'current' : 'preview-only';
}

/** 图元词汇表：7 + 1 个（spec §5.5）。 */
const ELEMENT_TYPES = [
  'rect', 'ellipse', 'arc', 'text', 'ticks', 'outline', 'image', 'chart',
];

const ELEMENT_REQUIRED = ['id', 'type', 'role', 'x_in', 'y_in', 'w_in', 'h_in'];
const SPEC_REQUIRED = ['width_in', 'height_in', 'chart_key', 'chart_title', 'scale'];
//: `$defs.scale.required`：缺任一项渲染就不知道值域/换算基准，必查。
const SCALE_REQUIRED = ['v_max', 'h_in', 'unit'];
const DOC_REQUIRED = [
  'version', 'theme', 'width_in', 'height_in', 'margin_in', 'gutter_in',
  'column_count', 'column_gutter_in', 'rows', 'cards', 'blocks', 'images',
];

/** 实际取值的类型名，用来拼人能读的错误消息（对齐 `schema_check._kind`）。 */
function kind(value) {
  if (value === null) return 'null';
  if (Array.isArray(value)) return 'list';
  if (typeof value === 'object') return 'dict';
  if (typeof value === 'number') return Number.isInteger(value) ? 'int' : 'float';
  return typeof value;
}

function isNumber(value) {
  return typeof value === 'number' && Number.isFinite(value);
}

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

/** 深拷贝（只处理 JSON 能表达的类型，图纸本来就是 JSON）。 */
function cloneJson(value) {
  if (Array.isArray(value)) return value.map(cloneJson);
  if (value !== null && typeof value === 'object') {
    const out = {};
    for (const [k, v] of Object.entries(value)) out[k] = cloneJson(v);
    return out;
  }
  return value;
}

/**
 * 宽松读入一份图纸：补缺键、收警告，**不抛**。
 *
 * 返回 `{ doc, warnings }`。`doc` 是**深拷贝**（不改调用方的对象），缺的键按
 * 下面的口径补齐：
 *
 *   * `version` → `null`（老样本没有，如实反映，不伪造成 "1.0"）
 *   * `images` → `[]`
 *   * `rows` → `[]`
 *   * `theme` → 保持缺失（渲染器需要自备色板，补个空板只会画成空白）
 *
 * @param {object} doc 解析好的 `pagelayout.json`
 * @param {{ version?: string }} [opts] `version` 是本代码支持的契约版本
 * @returns {{doc: object, warnings: string[]}}
 */
export function normalizeDoc(doc, opts = {}) {
  const expected = opts.version || CONTRACT_VERSION;
  if (!isObject(doc)) {
    throw new Error(`pagelayout: 顶层不是对象（读到 ${kind(doc)}）`);
  }
  const warnings = [];
  const out = cloneJson(doc);

  if (out.version == null) {
    warnings.push('$.version: 缺失，按 0.x 宽松读');
    out.version = null;
  } else if (majorOf(out.version) !== CONTRACT_MAJOR) {
    // 宽松读仍然不抛（这一层的契约就是「不抛」），但要把话说重：主版本不认识时
    // 字段口径可能整体变过，画出来的东西不可信。硬闸在 assertDoc（D9）。
    warnings.push(
      `$.version: 读到 ${JSON.stringify(out.version)}，主版本不认识`
      + `（本代码只支持 ${JSON.stringify(`${CONTRACT_MAJOR}.x`)}：`
      + `${SUPPORTED_VERSIONS.join('、')}）；字段口径可能整体变过，`
      + '渲染结果不可信，assertDoc 会拒绝',
    );
  } else if (out.version !== expected) {
    warnings.push(`$.version: 读到 ${JSON.stringify(out.version)}，本代码是 ${JSON.stringify(expected)}`);
  }

  if (!('images' in out)) {
    warnings.push('$.images: 缺失，按空列表读');
    out.images = [];
  }
  if (!('rows' in out)) {
    warnings.push('$.rows: 缺失，按空列表读');
    out.rows = [];
  }
  if (!('theme' in out)) {
    warnings.push('$.theme: 缺失（0.x 样本没有主题，渲染器需自备色板）');
  }

  return { doc: out, warnings };
}

/** 校验一个对象节点的必备键与若干数值键，错误推进 `errors`。 */
function checkObject(node, path, required, numericKeys, errors) {
  if (!isObject(node)) {
    errors.push({ path, message: `expected dict, got ${kind(node)}` });
    return false;
  }
  for (const key of required) {
    if (!(key in node) || node[key] === undefined) {
      errors.push({ path: `${path}.${key}`, message: 'required key is missing' });
    }
  }
  for (const key of numericKeys) {
    // 这里**不放行 null**：`numericKeys` 里全是 schema 声明为 `{"type":"number"}`
    // （或 `integer`）的坐标/尺寸键，可空的键（`font_pt` / `scale.factor` 等）
    // 一个都没进来。Python 侧对 `x_in: null` 报 `expected number, got null`，
    // 这里必须同口径 —— 早先的 `!== null` 豁免会让所有数值键的 null 静默通过。
    if (key in node && !isNumber(node[key])) {
      errors.push({ path: `${path}.${key}`, message: `expected number, got ${kind(node[key])}` });
    }
  }
  return true;
}

/** 校验一个数组节点（逐项交给 `each`），返回该数组（非数组则返回 `[]`）。 */
function checkArray(node, path, errors, each) {
  if (!Array.isArray(node)) {
    errors.push({ path, message: `expected list, got ${kind(node)}` });
    return [];
  }
  node.forEach((item, i) => each(item, `${path}[${i}]`));
  return node;
}

/**
 * 严格校验一份图纸，不合规抛 {@link ContractError}。
 *
 * 校验范围（**受限子集**，见文件头）：顶层必备键与数值类型、`cards[].spec`
 * 的必备键、`spec.scale` 的必备键与 `v_max` / `h_in` 的数值类型、`elements[]`
 * 的必备键 + `type` 枚举 + 四个坐标字段的数值类型，`rows` / `blocks` / `images`
 * 是数组。**不**求值 JSON Schema、**不**查未知键。
 *
 * @param {object} doc
 * @throws {ContractError} 结构不符；`err.errors` 带逐条 `{path, message}`
 */
export function assertDoc(doc) {
  const errors = [];

  if (!checkObject(doc, '$', DOC_REQUIRED, [
    'width_in', 'height_in', 'margin_in', 'gutter_in',
    'column_count', 'column_gutter_in',
  ], errors)) {
    throw new ContractError(errors);
  }

  // version 允许 null（0.x 老样本），但一旦有值必须是字符串。
  if (doc.version != null && typeof doc.version !== 'string') {
    errors.push({ path: '$.version', message: `expected string | null, got ${kind(doc.version)}` });
  }
  // 主版本硬闸（D9 / P3 方案 §5）：类型对了、主版本不认识也要拒绝——严格校验这一层
  // 的职责就是「拿不准就别放行」，硬读出来的几何是错的。
  if (typeof doc.version === 'string' && majorOf(doc.version) !== CONTRACT_MAJOR) {
    errors.push({
      path: '$.version',
      message: `unsupported major version ${JSON.stringify(doc.version)}; `
        + `this code supports ${CONTRACT_MAJOR}.x (${SUPPORTED_VERSIONS.join(', ')})`,
    });
  }
  // theme 允许 null，但一旦有值必须是对象（渲染器拿它取色）。
  if (doc.theme != null && !isObject(doc.theme)) {
    errors.push({ path: '$.theme', message: `expected dict | null, got ${kind(doc.theme)}` });
  }
  // column_count 是整数（schema 的 type: integer）。
  if ('column_count' in doc && doc.column_count !== null
      && !(isNumber(doc.column_count) && Number.isInteger(doc.column_count))) {
    errors.push({ path: '$.column_count', message: `expected integer, got ${kind(doc.column_count)}` });
  }

  checkArray(doc.rows, '$.rows', errors, (row, path) => {
    checkObject(row, path, [], ['y_in', 'h_in'], errors);
  });

  checkArray(doc.cards, '$.cards', errors, (card, path) => {
    checkObject(card, path, [], ['x_in', 'y_in', 'w_in', 'h_in'], errors);
    const specPath = `${path}.spec`;
    if (checkObject(card.spec, specPath, SPEC_REQUIRED, ['width_in', 'height_in'], errors)) {
      // `scale` 以前只当存在性键，从不递归 —— 于是 `scale='oops'` / `scale=null` /
      // `scale={}` / 删 `unit` / 删 `v_max` / `h_in='x'` 六种在 Python 全报错、JS 全放行。
      // schema 的 `$defs.scale` 是 object 且 required=['v_max','h_in','unit']，
      // v_max / h_in 为 number。这一行补上子结构：非对象报 `expected dict, got ...`，
      // 缺键报 `required key is missing`，数值键类型错报 `expected number, got ...`。
      checkObject(card.spec.scale, `${specPath}.scale`, SCALE_REQUIRED, ['v_max', 'h_in'], errors);
      checkArray(card.spec.elements, `${specPath}.elements`, errors, (el, elPath) => {
        if (!checkObject(el, elPath, ELEMENT_REQUIRED,
          ['x_in', 'y_in', 'w_in', 'h_in'], errors)) {
          return;
        }
        if ('type' in el && !ELEMENT_TYPES.includes(el.type)) {
          errors.push({
            path: `${elPath}.type`,
            message: `unknown element type ${JSON.stringify(el.type)}; `
              + `expected one of ${ELEMENT_TYPES.join(', ')}`,
          });
        }
      });
    }
  });

  checkArray(doc.blocks, '$.blocks', errors, (block, path) => {
    checkObject(block, path, [], ['x_in', 'y_in', 'w_in', 'h_in'], errors);
  });

  checkArray(doc.images, '$.images', errors, (image, path) => {
    checkObject(image, path, [], ['x_in', 'y_in', 'w_in', 'h_in'], errors);
  });

  if (errors.length) throw new ContractError(errors);
}
