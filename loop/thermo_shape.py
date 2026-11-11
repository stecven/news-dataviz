"""温度计皮肤图元的形状计算（纯函数，无 PPTX / PIL 依赖）。

用户 m02273 要的三件事，落成两种新图元：
  * `ticks`   —— 管身右侧的一串短横刻度线（一个 freeform 形状里多个分离轮廓）；
  * `outline` —— 沿「半圆顶 + 竖直管身 + 锥形收口 + 球泡外环」描出的**一条**
                 闭合轮廓（球与外环之间的留白就是报纸原版的「双重轮廓」）。

两个渲染后端（PPTX / PNG）都只调用本模块，保证像素口径唯一。所有坐标都是
英寸、屏幕坐标（y 向下）。
"""
import math

# 球泡外环与锥形收口在圆周上的接合角（度，自 +x 轴顺时针，y 向下）。
_FLARE_DEG = 35.0


def tick_rects(el) -> list[tuple]:
    """把一个 ticks 图元展开成若干 (x, y, w, h) 小矩形（自下而上等距）。

    刻度贴在**管身右缘内侧**：右端恒等于管右缘，长度 / 粗细来自 geometry。
    刻度带上下各留一段 inset：上让出半圆管口的圆顶（否则最上面一条会从
    弧顶戳出来），下让出锥形收口（原版刻度到颈口为止）。
    """
    g = el.geometry or {}
    count = int(g["count"])
    length = float(g["len"])
    thick = float(g["thick"])
    pad_top = float(g.get("pad_top", 0.0))
    pad_bottom = float(g.get("pad_bottom", 0.0))
    right = el.x_in + el.w_in
    top = el.y_in + pad_top
    step = (el.h_in - pad_top - pad_bottom) / count
    return [(right - length, top + (count - 1 - i) * step, length, thick)
            for i in range(count)]


def _quad(p0, p1, p2, n=6):
    """二次贝塞尔采样（含两端点），用于锥形收口。"""
    out = []
    for i in range(n + 1):
        t = i / n
        u = 1.0 - t
        out.append((u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
                    u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]))
    return out


def outline_polyline(el) -> list[tuple]:
    """沿外圈轮廓取一圈点（首尾重合，可直接 close=True 收口）。

    结构（顺时针，y 向下）：
      半圆顶(apex=管口) → 右壁 → 锥形收口 → 球泡外环右→下→左 → 左收口 → 左壁 → 闭合
    球环比管身宽，所以轮廓最宽处在球环而不是管身——这正是原版「管细球胖」的观感。
    """
    g = el.geometry or {}
    R = float(g["R"])
    cap_r = float(g["cap_r"])
    neck_h = float(g["neck_h"])
    # geometry 里的 cx / cy / cap_top / tube_bottom 是**创建时的坐标系**（内容
    # 坐标），而 el.x_in / el.y_in 是**当前**的外接盒（图框平移后是卡片坐标）。
    # 两者不一定同源——早先直接拿 geometry.cx 当页面坐标画，包框后整圈轮廓会
    # 左偏一个平移量（用户 m05104 肉眼发现的“液柱贴着管身左侧”其实是外圈错位）。
    # 现在一律以**外接盒**为锚点：geometry 只提供相对尺寸，位置由 bbox 决定。
    # bbox 的左上角对应 (cx - R, cap_top)。
    ox = el.x_in - (float(g["cx"]) - R)
    oy = el.y_in - float(g["cap_top"])
    cx, cy = float(g["cx"]) + ox, float(g["cy"]) + oy
    cap_top = el.y_in
    tube_bottom = float(g["tube_bottom"]) + oy
    flare = math.radians(float(g.get("flare_deg", _FLARE_DEG)))

    pts: list[tuple] = []
    # 1) 半圆顶：圆心在 (cx, cap_top + cap_r)，apex 恰好落在管口 cap_top。
    cap_cy = cap_top + cap_r
    for i in range(9):
        a = math.pi + math.pi * i / 8          # 180° → 360°，y 向下即向上鼓
        pts.append((cx + cap_r * math.cos(a), cap_cy + cap_r * math.sin(a)))
    # 2) 右壁：自半圆右端竖直下到收口起点。
    p_flare_y = tube_bottom - neck_h
    pts.append((cx + cap_r, p_flare_y))
    # 3) 锥形收口：向外张开接到球环。
    hit_r = (cx + R * math.cos(flare), cy - R * math.sin(flare))
    pts.extend(_quad((cx + cap_r, p_flare_y), (cx + cap_r, tube_bottom), hit_r)[1:])
    # 4) 球泡外环：自 -flare 顺时针扫到 180°+flare。
    # 步数取 50 是为了让 0° / 90° / 180° 三个极点**恰好落在采样点上**：
    # 采样不到极点时，折线最左/最右点会内缩半个步长，出图看着像球泡被削平。
    total = math.pi + 2 * flare
    for i in range(1, 51):
        a = -flare + total * i / 50
        pts.append((cx + R * math.cos(a), cy + R * math.sin(a)))
    # 5) 左收口 + 6) 左壁。
    p_left_flare = (cx - cap_r, p_flare_y)
    hit_l = (cx - R * math.cos(flare), cy - R * math.sin(flare))
    pts.extend(_quad(hit_l, (cx - cap_r, tube_bottom), p_left_flare)[1:])
    pts.append((cx - cap_r, cap_top + cap_r))
    # 7) 闭合：回到起点。
    pts.append(pts[0])
    return pts
