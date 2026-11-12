"""声明式规格模型：本项目唯一的可编辑源。

PageSpec 是「代码规格 JSON」，PPTX / PNG 都只是它的渲染产物。
改数据 = 换一份 PageSpec = 重渲染，形状尺寸由确定性脚手架重算。
"""
from dataclasses import asdict, dataclass, field


@dataclass
class Scale:
    v_max: float
    h_in: float
    unit: str
    # B 节新增清单：factor = h_in/v_max（= 液柱每单位数值的英寸数），
    # domain 是比例尺的声明式输入区间。二者都是可选字段，缺省 None 以保持
    # 老 pagespec.json 可读。
    factor: float | None = None
    domain: list | None = None


@dataclass
class ElementSpec:
    id: str
    type: str
    role: str
    x_in: float
    y_in: float
    w_in: float
    h_in: float
    fill: str | None = None
    text: str | None = None
    binding: dict | None = None
    # B 节新增清单：geometry_expr 存声明式求解表达式（E.1 ④ 审计留痕）；
    # geometry 存 bbox 之外的求解结果（半圆 start/end angle、cx/cy/R）。
    # 新增字段一律放在末尾，避免破坏既有按位置构造的 ElementSpec(...)。
    geometry_expr: str | None = None
    geometry: dict | None = None
    # 第五层接线（用户 m04220）：图片图元（type == "image"）引用的磁盘文件路径，
    # 相对项目根。**不复用 binding**——binding 载的是数据点 {value,label}，
    # 图片载的是文件位置，混用会让「数据链接」校验器误判图片有数据绑定。
    # 缺省 None，保证改版前的 pagespec.json 仍能 from_dict 读回。
    image_path: str | None = None
    # 1.0 契约新增（Spec §5.6 / D10）：契约里的折行结果、实际字号、可否单独
    # 选中。三者都由渲染前的求解填，读老样本时为 None——缺省 None 保证改版前
    # 的 pagespec.json / pagelayout.json 仍能读回。**必须留在末尾**：
    # loop/layout.py::flatten 等处按位置构造 ElementSpec 的代码不受影响。
    lines: list | None = None
    font_pt: float | None = None
    editable: bool | None = None


@dataclass
class PageSpec:
    width_in: float
    height_in: float
    chart_key: str
    chart_title: str
    scale: Scale
    elements: list[ElementSpec] = field(default_factory=list)
    semantic_tags: list = field(default_factory=list)
    # B 节新增清单：constraints 存约束声明，layout 存 plot segment 参数。
    constraints: list = field(default_factory=list)
    layout: dict = field(default_factory=dict)
    # 图框（用户 m04818）：包框之后 width_in/height_in 指的是**框**，而内容
    # （数据图形）原来占的那块记在 content_bbox。两个尺寸都留着，版式引擎才能
    # 决定按框缩放还是按内容缩放——只记画布尺寸会把「内容有多大」这个信息丢掉。
    # 都是 [x, y, w, h]，缺省 None 保证改版前的 pagespec.json 仍可读。
    content_bbox: list | None = None
    frame_bbox: list | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PageSpec":
        return cls(
            width_in=d["width_in"],
            height_in=d["height_in"],
            chart_key=d["chart_key"],
            chart_title=d["chart_title"],
            scale=Scale(**d["scale"]),
            elements=[ElementSpec(**e) for e in d.get("elements", [])],
            semantic_tags=d.get("semantic_tags", []),
            constraints=d.get("constraints", []),
            layout=d.get("layout", {}),
            content_bbox=d.get("content_bbox"),
            frame_bbox=d.get("frame_bbox"),
        )
