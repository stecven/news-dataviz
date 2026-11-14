// 单位换算层：英寸 / 磅 → 像素。**只有换算与取整，不含任何绘制逻辑。**
//
// 契约里所有坐标字段都是英寸（spec C1），换算只在这里发生。两套取整
// **不可互换**（Plan Review Focus #1，差 1px 会让整页错位累积）：
//
//   * 卡内单卡渲染（T3）走 Python ``int()`` 的**截断**口径 → ``truncPx`` /
//     ``boxPxTrunc``
//   * 整版合成（T4）走 Python ``int(round())`` 的**四舍五入**口径 → ``roundPx`` /
//     ``boxPxRound``
//
// 两个出口各自叫“截断”与“四舍五入”，**故意不提供**“默认取整”这种含糊入口：
// 调用方必须显式选边，选错时读代码就能看出来。
//
// 真实夹具里的分水岭数字：``3.37654`` 英寸 → 截断 337、四舍五入 338。
//
// **“四舍五入”必须走 ``pyRound``，不是 ``Math.round``**。Python 的 ``round()`` 是
// half-to-even（银行家舍入），``Math.round`` 是 half-up，两者在恰好落 ``.5`` 时分叉。
// 真实产物里这处分叉是**可观测**的（R36）：
//
//   * 字号 9.0 磅 → ``9 * 100/72`` 在双精度里**精确**等于 ``12.5``：
//     Python ``int(round(12.5))`` 得 **12**，``Math.round(12.5)`` 得 13
//     —— 全 11 份产物里有 12 个 ``title`` 元素用这个字号，差 1px 字号会让
//     墨迹宽多 8%、基线再低 1px；
//   * 插图 ``rect[1] = 1.065`` 英寸 → ``106.5``：Python 106、``Math.round`` 107，
//     5 张插图受影响。
//
// 所以两个“四舍五入”出口（``roundPx`` / ``boxPxRound``）与字号、行高一律经
// ``pyRound``；``truncPx`` / ``boxPxTrunc`` 仍用 ``Math.trunc``（Python ``int()``
// 是向零截断，两者本来就一致，不要顺手改）。
//
// 本文件是**最底层**（不 import 任何兄弟模块）：``theme.js`` 反过来从这里
// re-export ``LINE_HEIGHT_RATIO``，两者共用同一个数值定义，不会漂。

/** 每英寸像素数。与 ``loop/preview.py`` 同值；**不是** 96。 */
export const PX_PER_IN = 100;

/**
 * 行高系数：行高 = 字号 × 该系数（只给预览层的折行用；PPTX 端自带行距）。
 *
 * 契约的 ``theme`` 里**没有**这一项（Python 侧是 ``loop/palette.py`` 的模块级常量），
 * 属 P2 已知偏差；``theme.js`` 原样 re-export 它，调用方两边都能拿到。
 */
export const LINE_HEIGHT_RATIO = 1.35;

/** 每磅像素数（1 磅 = 1/72 英寸）。 */
export const PX_PER_PT = PX_PER_IN / 72;

/**
 * Pillow ``getmetrics()[0]``（ascent）的等价系数。
 *
 * 实测结论，别“顺手修正”：``ceil(px * 1.058)`` 在 px=6..64 上与 Pillow
 * 的 ascent 零偏差；换成 ``1.059`` 在 px=17 / 34 / 51 就错，``1.0625`` 错 19 处，
 * ``round(px * 1.0625)`` 错 19 处。T3 的文字基线断言直接依赖它。
 */
export const ASCENT_RATIO = 1.058;

/** 英寸 → 像素，**不取整**（保留小数，供需要连续性计算的地方用）。 */
export function pxFromIn(inches) {
  return (Number(inches) || 0) * PX_PER_IN;
}

/**
 * Python ``round()`` 的等价实现：恰好 ``.5`` 时取偶（half-to-even），
 * 不是 ``Math.round`` 的 half-up。
 *
 * 判据（已逐点对过 CPython 的 ``int(round(x))``）：
 * ``pyRound(12.5) === 12``、``pyRound(182.5) === 182``、``pyRound(106.5) === 106``、
 * ``pyRound(57.5) === 58``、``pyRound(0.5) === 0``、``pyRound(1.5) === 2``、
 * ``pyRound(2.5) === 2``、``pyRound(-0.5) === 0``、``pyRound(-1.5) === -2``、
 * ``pyRound(-2.5) === -2``、``pyRound(-12.5) === -12``。
 *
 * 浮点注意：**不要**加 epsilon 兜底。``9 * (100/72)`` 在双精度里恰好是 ``12.5``
 * （``=== 12.5`` 为真），而 ``0.565 * 100`` 是 ``56.499999999999993``（真值就不落
 * ``.5``，该往 56 走）。对 ``x - floor(x)`` 与 ``0.5`` 做**精确**相等比较，两者
 * 就都对得上 Python 的整数运算语义。
 *
 * @param {number} x
 * @returns {number} 最近的整数，恰在中点时取偶数
 */
export function pyRound(x) {
  const value = Number(x);
  if (!Number.isFinite(value)) return value; // NaN / ±Infinity 原样透出，不静默变 0
  const floor = Math.floor(value);
  const diff = value - floor; // 恒在 [0, 1)
  if (diff > 0.5) return floor + 1;
  if (diff < 0.5) return floor;
  // 恰好在中点：取偶。`floor` 为偶时留在 `floor`，否则进到 `floor + 1`
  // （对负数同样成立：-12.5 的 floor 是 -13（奇）→ -12；-0.5 的 floor 是 -1（奇）→ -0）。
  return floor % 2 === 0 ? floor : floor + 1;
}

/** 磅 → 像素，四舍五入到整像素（Python ``int(round())`` 口径，见 {@link pyRound}）。 */
export function pxFromPt(pt) {
  return pyRound((Number(pt) || 0) * PX_PER_PT);
}

/** 英寸 → 像素，**截断**（Python ``int()`` 口径，负数向零截断，与 Python 一致）。 */
export function truncPx(inches) {
  return Math.trunc((Number(inches) || 0) * PX_PER_IN);
}

/** 英寸 → 像素，**四舍五入**（Python ``int(round())`` 口径，见 {@link pyRound}）。 */
export function roundPx(inches) {
  return pyRound((Number(inches) || 0) * PX_PER_IN);
}

/**
 * 盒子的四元组 ``[x0, y0, x1, y1]``，每个坐标**各自**截断。
 *
 * 不是“整体包围盒”式取整：``boxPxTrunc`` 与 ``boxPxRound`` 混用会在宽高上
 * 各差至多 1px。缺 ``w_in`` / ``h_in`` 时按 0 处理（老样本的占位元素可能缺这两键），
 * 不许因此得到 NaN。
 */
export function boxPxTrunc(el) {
  const x0 = Number(el && el.x_in) || 0;
  const y0 = Number(el && el.y_in) || 0;
  const w = Number(el && el.w_in) || 0;
  const h = Number(el && el.h_in) || 0;
  return [truncPx(x0), truncPx(y0), truncPx(x0 + w), truncPx(y0 + h)];
}

/**
 * 同 {@link boxPxTrunc}，但走四舍五入口径（整版合成用这一套）。
 *
 * 内部**只调** {@link roundPx}，所以自动继承 half-to-even：这里不另写取整逻辑，
 * 也不许在调用点绕开它直接 `Math.round`。
 */
export function boxPxRound(el) {
  const x0 = Number(el && el.x_in) || 0;
  const y0 = Number(el && el.y_in) || 0;
  const w = Number(el && el.w_in) || 0;
  const h = Number(el && el.h_in) || 0;
  return [roundPx(x0), roundPx(y0), roundPx(x0 + w), roundPx(y0 + h)];
}

/**
 * 行高（像素）：``round(未取整的 px * LINE_HEIGHT_RATIO)``。
 *
 * 注意是拿**未取整**的 px 去乘，不是 ``round(pxFromPt(pt) * 1.35)``：
 * 11.26 磅 → ``round(15.6388… * 1.35) = 21``，而先取整再乘会得到 22。
 * 对齐 ``loop/palette.py::line_height_px``。
 *
 * 取整走 {@link pyRound}：19 个真实 ``font_pt`` 上两侧恰好同值（无分歧），
 * 但口径必须一致 —— 少一处 ``Math.round`` 就少一个将来翻车的入口。
 */
export function lineHeightPx(pt) {
  return pyRound((Number(pt) || 0) * PX_PER_PT * LINE_HEIGHT_RATIO);
}

/** 文字基线到墨迹顶部的距离（像素），Pillow ascent 的等价写法。 */
export function ascentPx(px) {
  return Math.ceil((Number(px) || 0) * ASCENT_RATIO);
}

/**
 * 卡片相对基准画布的缩放比：``min(w/baseW, h/baseH)``，任一维 ≤ 0 时兜底 1。
 *
 * 取**小**的那一维：只放大宽（或只放大高）时，字号不许跟着放大到溢出另一维。
 * 对齐 ``loop/palette.py::canvas_scale``；基准画布默认 ``[10, 6]``（英寸），
 * 与 ``theme.base_canvas_in`` 的缺省一致，调用方可以显式传入图纸里的值。
 */
export function cardScale(card, baseCanvasIn = [10, 6]) {
  const w = Number(card && card.w_in) || 0;
  const h = Number(card && card.h_in) || 0;
  if (w <= 0 || h <= 0) return 1;
  const baseW = Number(baseCanvasIn && baseCanvasIn[0]) || 10;
  const baseH = Number(baseCanvasIn && baseCanvasIn[1]) || 6;
  return Math.min(w / baseW, h / baseH);
}
