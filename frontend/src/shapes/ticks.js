// `ticks` 复合图元的几何展开：把一个元素展开成一串短横刻度矩形。
//
// 这是 `loop/thermo_shape.py:17-34` 的逐行照抄。判据不是「看起来像」，是**每个
// 数字都与 Python 相同**（测试容差 1e-9）。改动本文件前请先改 Python 侧，再回来抄。
//
// 单位：输入（`el.x_in/y_in/w_in/h_in` 与 `geometry`）和输出**全是英寸**。
// 像素换算属 T3 的事，本模块不碰 `PX_PER_IN`，也不产出任何颜色/字号——主题归
// `theme.js`，这里只管几何。

/**
 * 取 `geometry` 上的**必需**键。缺键就抛错，不兜默认值。
 *
 * Python 侧是 `int(g["count"])` / `float(g["len"])`，缺键直接 `KeyError`。JS 这边
 * `Number(undefined)` 会安静地变成 `NaN`（再往下就是一堆 `NaN` 坐标），所以显式
 * 拦一道：拼错参数名必须炸，而不是画到画布左上角。
 *
 * 与之相对，`pad_top` / `pad_bottom` / `flare_deg` 在 Python 里是**有意**的
 * `g.get(..., 默认值)`，那几个键不许拦（见各自的调用处）。
 */
function required(geometry, key) {
  if (!(key in geometry)) {
    throw new Error(`ticks: geometry 缺少必需键 "${key}"`);
  }
  return Number(geometry[key]);
}

/**
 * 把 `ticks` 元素展开成 `[[x, y, w, h], ...]`（英寸，y 向下）。
 *
 * 刻度贴在**管身右缘内侧**：右端恒等于管右缘（`x_in + w_in`）。刻度带上下各留
 * 一段 inset：上让出半圆管口的圆顶（否则最上面一条会从弧顶戳出来），下让出锥形
 * 收口（原版刻度到颈口为止）。
 *
 * @param {{x_in: number, y_in: number, w_in: number, h_in: number, geometry: object}} el
 * @returns {number[][]} 每个 `[x, y, w, h]`，**自下而上**排列。
 */
export function tickRects(el) {
  const g = el.geometry || {};
  // Python 是 `int(g["count"])`，对浮点**向零截断**；照抄成 Math.trunc，不是 Math.round。
  const count = Math.trunc(required(g, 'count'));
  const length = required(g, 'len');
  const thick = required(g, 'thick');
  // 这两个是可选的：Python 是 `g.get("pad_top", 0.0)`，缺键按 0 处理。
  const padTop = 'pad_top' in g ? Number(g.pad_top) : 0.0;
  const padBottom = 'pad_bottom' in g ? Number(g.pad_bottom) : 0.0;

  const right = el.x_in + el.w_in;
  const top = el.y_in + padTop;
  const step = (el.h_in - padTop - padBottom) / count;

  const rects = [];
  for (let i = 0; i < count; i += 1) {
    // `count - 1 - i` 而不是 `i`：**自下而上**。i=0 那根 y 最大（y 轴向下 ⇒ 最靠下），
    // 最后一根贴着刻度带上沿。改成 `i` 会让整串刻度上下颠倒，而肉眼在 13 根等距短线
    // 上极难分辨——所以测试里有一条专门的「第一根在最下」断言钉着它。
    rects.push([right - length, top + (count - 1 - i) * step, length, thick]);
  }
  return rects;
}
