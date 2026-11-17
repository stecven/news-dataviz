// 主题读取层：把图纸里的 ``theme`` 解析成一组访问器。
//
// 这是**唯一**允许出现色值字面量的文件（V6 守卫豁免它，见
// ``tests/test_step36_contract_guards.py``）。即便如此，本文件里也**不放**
// 任何一个色值/字号字面量：真正的颜色与字号全部从 ``spec.theme`` 读，这里只
// 落两张“别名表”，因为那两项契约里没有。
//
// **P2 已知偏差**：下面两个常量在 ``pagelayout.json`` 的 ``theme`` 里查不到，
// 出处是 Python 侧的 ``loop/palette.py``（模块级常量，没有进 ``summary()``）：
//
//   * ``ROLE_ALIASES``      ← ``loop/palette.py::ROLE_ALIASES``
//   * ``LINE_HEIGHT_RATIO`` ← ``loop/palette.py::LINE_HEIGHT_RATIO``
//
// 原样抄成常量表，**不去改** ``loop/palette.py::summary()``（那是 Python 侧、
// 属另一条线的边界）。等契约补上这两项，这里改成从 ``theme`` 读即可。
//
// 同理 ``BORDER_ROLE`` ← ``loop/palette.py::BORDER_ROLE``。
import { LINE_HEIGHT_RATIO } from './units.js';

/**
 * 图元角色 → 色板角色 的别名表（逐条抄 ``loop/palette.py::ROLE_ALIASES``）。
 *
 * 图元里写的是 ``role: 'text'`` / ``role: 'liquid'`` 这类**语义**角色，色板里
 * 只有 ``neutral_dark`` / ``primary`` 这类**色值**角色，中间靠这张表翻译。
 */
export const ROLE_ALIASES = {
  liquid: 'primary',
  track: 'surface',
  outline: 'neutral_hairline',
  ticks: 'neutral_hairline',
  text: 'neutral_dark',
  placeholder_stroke: 'neutral_strong',
  placeholder_mid: 'neutral_mid',
  placeholder_light: 'neutral_light',
  canvas: 'surface',
};

/** 边框 / 描边的色板角色（``loop/palette.py::BORDER_ROLE``）。 */
export const BORDER_ROLE = 'neutral_mid';

/**
 * 行高系数：行高 = 字号 × 该系数（``loop/palette.py::LINE_HEIGHT_RATIO``）。
 *
 * 数值的唯一定义在 ``units.js``（最底层模块），这里只是 re-export：两边拿到的
 * 是同一个数，不会因为抄了两份而漂。
 */
export { LINE_HEIGHT_RATIO };

/** 色板角色的字典名（``theme.palette`` 是“名字 → 6 位 hex、不带 #”）。 */
function assertObject(value, what) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`theme.${what}: 缺失或不是对象，拒绝渲染（不许静默给空表）`);
  }
  return value;
}

/**
 * 建一个主题访问器。
 *
 * ``themeObj`` 是图纸的 ``theme`` 键（``loop/palette.py::summary()`` 的原样产物）。
 * 缺 ``palette`` 或 ``font_sizes`` 直接抛：静默给空色板会让整页画成空白，
 * 比当场炸难查得多。
 *
 * @param {object} themeObj 图纸里的 ``theme``
 * @returns {{color: (role: string) => string, fontPt: (role: string) => number,
 *            sectorStrokePt: () => number, baseCanvasIn: () => number[],
 *            fontPtClamp: () => number[], palette: object,
 *            fontSizes: object, roleToFont: object}}
 */
export function createTheme(themeObj) {
  if (!themeObj || typeof themeObj !== 'object') {
    throw new Error('theme: 整份主题缺失，拒绝渲染（0.x 老样本没有主题，需自备色板）');
  }
  const palette = assertObject(themeObj.palette, 'palette');
  const fontSizes = assertObject(themeObj.font_sizes, 'font_sizes');
  // 契约里 role_to_font 是 1.0 新增，缺了退回只查 font_sizes（设计角色直接命中）。
  const roleToFont = (themeObj.role_to_font && typeof themeObj.role_to_font === 'object')
    ? themeObj.role_to_font
    : {};

  /**
   * 按角色取颜色，返回带前导 ``#`` 的字符串。
   *
   * 先过别名表再查色板。未知角色**抛错**（对齐 ``loop/palette.py::color`` 的
   * KeyError：拼错角色名时应当立刻炸，而不是静默画成某个颜色）。
   */
  function color(role) {
    const key = Object.prototype.hasOwnProperty.call(ROLE_ALIASES, role)
      ? ROLE_ALIASES[role]
      : role;
    const hex = palette[key];
    if (hex == null) {
      throw new Error(
        `unknown palette role ${JSON.stringify(role)}; `
        + `known roles: ${Object.keys(palette).sort().join(', ')} `
        + `(aliases: ${Object.keys(ROLE_ALIASES).sort().join(', ')})`,
      );
    }
    return String(hex).startsWith('#') ? String(hex) : `#${hex}`;
  }

  /**
   * 按角色取字号（磅）。
   *
   * **两类角色都接**：
   *   1. 语义角色（``value`` / ``legend`` / ``center`` / ``scale_note`` …）→ 先经
   *      ``role_to_font`` 翻成设计角色，再查 ``font_sizes``；
   *   2. 设计角色（``title`` / ``subtitle`` / ``body`` / ``label`` / ``note``）→
   *      直接查 ``font_sizes``（T4 的整版块传的就是 block 的 ``style``）。
   *
   * 两类都查不到**抛错**。这一点与 Python 的 ``DEFAULT_FONT_ROLE = 'note'``
   * 有意不同：Python 那边静默降级是为了容错，JS 侧宁可当场炸 —— 把 14pt 的
   * 副标题悄悄画成 8pt 而不报错，肉眼很难发现。
   */
  function fontPt(role) {
    if (Object.prototype.hasOwnProperty.call(roleToFont, role)) {
      const mapped = roleToFont[role];
      const pt = fontSizes[mapped];
      if (pt != null) return pt;
    }
    if (Object.prototype.hasOwnProperty.call(fontSizes, role)) {
      const pt = fontSizes[role];
      if (pt != null) return pt;
    }
    throw new Error(
      `unknown font role ${JSON.stringify(role)}; `
      + `design roles: ${Object.keys(fontSizes).sort().join(', ')} `
      + `(roles mapped: ${Object.keys(roleToFont).sort().join(', ')})`,
    );
  }

  /** 扇区描边线宽（磅）。缺 ``sector_stroke`` 时退回 Python 侧的同值常量。 */
  function sectorStrokePt() {
    const stroke = themeObj.sector_stroke;
    if (stroke && stroke.pt != null) return Number(stroke.pt);
    return 0.5;
  }

  /** 基准画布（英寸）：``[10, 6]``。缺省与 ``loop/palette.py`` 的两个常量同值。 */
  function baseCanvasIn() {
    const arr = themeObj.base_canvas_in;
    if (Array.isArray(arr) && arr.length >= 2) {
      return [Number(arr[0]), Number(arr[1])];
    }
    return [10, 6];
  }

  /** 缩放后字号的上限与下限（磅）：``[6, 24]``，缺省同 Python 侧常量。 */
  function fontPtClamp() {
    const arr = themeObj.font_pt_clamp;
    if (Array.isArray(arr) && arr.length >= 2) {
      return [Number(arr[0]), Number(arr[1])];
    }
    return [6, 24];
  }

  return {
    color,
    fontPt,
    sectorStrokePt,
    baseCanvasIn,
    fontPtClamp,
    palette,
    fontSizes,
    roleToFont,
  };
}
