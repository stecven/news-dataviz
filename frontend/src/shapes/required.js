// `geometry` 入参的**唯一**取值口径：必需键（`required`）与可选键（`optional`）
// 两条路都从这里走。
//
// 为什么单独立一个文件：`ticks.js` 与 `outline.js` 之前各有一份**逐字相同**的
// `required()`，两份一模一样却各自维护，改一处漏一处的风险高于共用。
//
// 为什么除「缺键抛错」外还要查类型与有限性：
//
// * Python 侧是 `float(g["len"])` / `int(g["count"])`；
//   `float("abc")` 抛 `ValueError`，`float(None)` 抛 `TypeError`。
// * JS 的 `Number("abc")` 安静地给 `NaN`，`Number(null)` 更安静地给 `0`。
//   于是 `len = "abc"` 会得到一串 `NaN` 坐标，`thick = null` 会得到 0 粗细——
//   渲染器不报错，T3 直接把它拼进 SVG 属性，浏览器和 jsdom 都不吭声，图只是
//   悄悄消失或瘦成一条线。比抛错难查一个量级，所以显式拦一道。
//
// 接受：有限 `number`；可解析为有限数的字符串（Python 的 `float("0.5")` 同样成立）。
// 拒绝：`null` / `undefined` / 布尔 / 对象 / `NaN` / `±Infinity` / `"abc"` / `""`。
//
// 注意 `count` 的**截断**不归这里管：Python 是 `int(g["count"])`（对浮点向零截断），
// 调用处用 `Math.trunc(required(...))` 表达这件事，本模块不把 `count` 当整数校验。

/** 把任意入参描述成一句人能读的话，塞进错误信息里。 */
function describe(raw) {
  if (typeof raw === 'string') {
    return JSON.stringify(raw);
  }
  return String(raw);
}

/**
 * 把一个 `geometry` 取值转成有限数值；不是有限数值就抛错。
 *
 * @param {*} raw 原始值
 * @param {string} key 键名，只用于错误信息
 * @param {string} label 图元名（`ticks` / `outline`），只用于错误信息
 * @returns {number} 有限数字
 */
function toFiniteNumber(raw, key, label) {
  let value = NaN;
  if (typeof raw === 'number') {
    value = raw;
  } else if (typeof raw === 'string' && raw.trim() !== '') {
    value = Number(raw);
  }
  if (!Number.isFinite(value)) {
    throw new Error(
      `${label}: geometry["${key}"] 必须是有限数值，实际是 ${describe(raw)}`,
    );
  }
  return value;
}

/**
 * 取 `geometry` 上的**必需**键：缺键抛错，值不是有限数值也抛错，不兜默认值。
 *
 * Python 侧是 `float(g["R"])` 之类的直接下标，缺键即 `KeyError`。这里保留原来
 * 那句错误信息的格式（`<label>: geometry 缺少必需键 "<key>"`），便于既有排错
 * 经验与日志 grep 继续有效。
 *
 * @param {object} geometry 元素上的 `geometry`
 * @param {string} key 键名
 * @param {string} label 图元名，用于错误信息前缀
 * @returns {number} 有限数字
 */
export function required(geometry, key, label) {
  if (!(key in geometry)) {
    throw new Error(`${label}: geometry 缺少必需键 "${key}"`);
  }
  return toFiniteNumber(geometry[key], key, label);
}

/**
 * 取 `geometry` 上的**可选**键：缺键返回 `fallback`，给了就必须是有限数值。
 *
 * 对应 Python 的 `float(g.get("pad_top", 0.0))` / `g.get("flare_deg", _FLARE_DEG)`：
 * 「缺键取默认值」是有意为之的分支，不能像 `required` 那样抛。但**给了**一个
 * 非数值（`NaN` / `null` / `"abc"`）时 Python 同样会抛（`float(NaN)` 不抛，
 * 但 `NaN` 一路下沉到 SVG 属性里同样是灾难），所以这里一并拦掉。
 *
 * @param {object} geometry 元素上的 `geometry`
 * @param {string} key 键名
 * @param {number} fallback 缺键时的默认值
 * @param {string} label 图元名，用于错误信息前缀
 * @returns {number} 有限数字
 */
export function optional(geometry, key, fallback, label) {
  if (!(key in geometry)) {
    return fallback;
  }
  return toFiniteNumber(geometry[key], key, label);
}
