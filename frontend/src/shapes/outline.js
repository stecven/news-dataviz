// `outline` 复合图元的几何展开：沿「半圆顶 + 竖直管身 + 锥形收口 + 球泡外环」描出
// **一条**闭合折线（球与外环之间的留白就是报纸原版的「双重轮廓」）。
//
// 这是 `loop/thermo_shape.py:37-98` 的逐行照抄。判据是**每个点都与 Python 相同**
// （容差 1e-9），点序、点数（74）也都必须一致——点少了轮廓上会留豁口。
//
// 单位：输入输出**全是英寸**，y 向下。本模块不碰像素、不碰颜色与字号。

/**
 * 球泡外环与锥形收口在圆周上的接合角（度，自 +x 轴顺时针，y 向下）。
 *
 * 与 `loop/thermo_shape.py:14` 的 `_FLARE_DEG` 同值。只有在 `geometry` 没给
 * `flare_deg` 时才用它。
 */
const FLARE_DEG = 35.0;

/**
 * 取 `geometry` 上的**必需**键：缺键抛错，不兜默认值。
 *
 * Python 是 `float(g["R"])`，缺键 `KeyError`。JS 的 `Number(undefined)` 会给 `NaN`
 * 且一路安静传下去，所以显式拦一道——拼错参数名必须炸。
 */
function required(geometry, key) {
  if (!(key in geometry)) {
    throw new Error(`outline: geometry 缺少必需键 "${key}"`);
  }
  return Number(geometry[key]);
}

/**
 * 二次贝塞尔采样，**含两端点**：返回 `n + 1` 个点。
 *
 * 对应 `loop/thermo_shape.py:37-45`。`n = 6`（默认）时返回 7 点。两端点必须都在：
 * 收口用 `[1:]` 掐掉与上一段重复的首点，若采样本身不含终点，轮廓会在与球环的接缝
 * 处留一道豁口——而且画出来仍然「像个温度计」，很难一眼看出。
 *
 * @param {[number, number]} p0 起点
 * @param {[number, number]} p1 控制点
 * @param {[number, number]} p2 终点
 * @param {number} [n] 分段数，默认 6（⇒ 7 点）
 * @returns {number[][]} `[[x, y], ...]`，长度 `n + 1`
 */
export function quad(p0, p1, p2, n = 6) {
  const out = [];
  for (let i = 0; i <= n; i += 1) {
    const t = i / n;
    const u = 1.0 - t;
    out.push([
      u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
      u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1],
    ]);
  }
  return out;
}

/**
 * 沿外圈轮廓取一圈点（首尾重合，可直接 `close` 收口），英寸。
 *
 * 对应 `loop/thermo_shape.py:48-98`。结构（顺时针，y 向下）：
 * 半圆顶（apex = 管口）→ 右壁 → 锥形收口 → 球泡外环右→下→左 → 左收口 → 左壁 → 闭合。
 * 球环比管身宽，所以轮廓最宽处在球环而不是管身——这正是原版「管细球胖」的观感。
 *
 * 点数固定 **74** = 半圆顶 9 + 右壁 1 + 右收口 6 + 球环 50 + 左收口 6 + 左壁 1 + 闭合 1。
 *
 * @param {{x_in: number, y_in: number, w_in: number, h_in: number, geometry: object}} el
 * @returns {number[][]} `[[x, y], ...]`，首末点相同。
 */
export function outlinePolyline(el) {
  const g = el.geometry || {};
  const R = required(g, 'R');
  const capR = required(g, 'cap_r');
  const neckH = required(g, 'neck_h');

  // geometry 里的 cx / cy / cap_top / tube_bottom 是**创建时**的坐标系（内容坐标），
  // 而 el.x_in / el.y_in 是**当前**的外接盒（图框平移后是卡片坐标）。两者不一定同源，
  // 所以**一律以外接盒为锚**：geometry 只提供相对尺寸，位置由 bbox 决定。
  // bbox 左上角对应 (cx - R, cap_top)。
  const ox = el.x_in - (required(g, 'cx') - R);
  const oy = el.y_in - required(g, 'cap_top');
  const cx = required(g, 'cx') + ox;
  const cy = required(g, 'cy') + oy;
  const capTop = el.y_in;
  const tubeBottom = required(g, 'tube_bottom') + oy;
  // flare_deg 是可选的：Python 是 `g.get("flare_deg", _FLARE_DEG)`。
  const flare = ((('flare_deg' in g ? Number(g.flare_deg) : FLARE_DEG)) * Math.PI) / 180;

  const pts = [];

  // 1) 半圆顶：圆心在 (cx, capTop + capR)，apex 恰好落在管口 capTop。
  const capCy = capTop + capR;
  for (let i = 0; i < 9; i += 1) {
    const a = Math.PI + (Math.PI * i) / 8;   // 180° → 360°，y 向下即向上鼓
    pts.push([cx + capR * Math.cos(a), capCy + capR * Math.sin(a)]);
  }

  // 2) 右壁：自半圆右端竖直下到收口起点。
  const pFlareY = tubeBottom - neckH;
  pts.push([cx + capR, pFlareY]);

  // 3) 锥形收口：向外张开接到球环。`[1:]` 去掉与右壁终点重复的首点。
  const hitR = [cx + R * Math.cos(flare), cy - R * Math.sin(flare)];
  pts.push(...quad([cx + capR, pFlareY], [cx + capR, tubeBottom], hitR).slice(1));

  // 4) 球泡外环：自 -flare 顺时针扫到 180° + flare。
  // 步数取 50 是为了让 0° / 90° / 180° 三个极点**恰好落在采样点上**：采样不到极点时，
  // 折线最左/最右点会内缩半个步长，出图看着像球泡被削平。改步数等于改观感。
  const total = Math.PI + 2 * flare;
  for (let i = 1; i <= 50; i += 1) {
    const a = -flare + (total * i) / 50;
    pts.push([cx + R * Math.cos(a), cy + R * Math.sin(a)]);
  }

  // 5) 左收口 + 6) 左壁。
  const pLeftFlare = [cx - capR, pFlareY];
  const hitL = [cx - R * Math.cos(flare), cy - R * Math.sin(flare)];
  pts.push(...quad(hitL, [cx - capR, tubeBottom], pLeftFlare).slice(1));
  pts.push([cx - capR, capTop + capR]);

  // 7) 闭合：回到起点（Python 侧就是 `pts.append(pts[0])`）。
  pts.push(pts[0]);
  return pts;
}
