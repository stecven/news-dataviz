"""渲染后端：一元素 = 一个 PPT 原生形状（可编辑产物，不是位图）。

每次调用都新建 Presentation，保证同路径重复渲染是覆盖写而非累加。
禁止用图片替代任何形状：液柱等必须是 AUTO_SHAPE，才能被 read_shapes 回读校验。

唯一例外是 ``type == "image"`` 的图元（第五层接线，用户 m04220）：它是**声明式
地要求一张位图**（占位图），不是用位图冒充形状。判断标准是「这个元素是否
本该由数据驱动几何」——图片元素没有 binding、不参与任何约束校验，所以画成
PICTURE 不损失可编辑性。
"""
import os

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Inches

from loop import palette
from loop.models import PageSpec
from loop.text_style import apply_fill, apply_text_style

#: 项目根：``image_path`` 按「相对项目根」存储，渲染时才拼成绝对路径。
#: 这样 pagespec.json 换机器也能读，不会写死 C:\Users\... 之类本机路径。
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve_image_path(image_path: str, root: str | None = None) -> str:
    """把规格里的相对路径解成绝对路径；不存在就抛，绝不静默跳过。

    静默跳过会让「占位图没画出来」变成一个只在预览里才发现的视觉问题，
    而调用方拿到的是「渲染成功」。所以这里主动失败并带上是哪个元素。
    """
    root = root or _ROOT
    if os.path.isabs(image_path):
        return image_path
    return os.path.join(root, image_path.replace("/", os.sep))


def _add_shape(slide, el):
    """按元素类型建一个原生形状，返回它；文本元素单独走 add_textbox。

    图片元素返回 PICTURE（唯一的位图分支），其余一律 AUTO_SHAPE。
    """
    if el.type == "text":
        shp = slide.shapes.add_textbox(
            Inches(el.x_in), Inches(el.y_in), Inches(el.w_in), Inches(el.h_in))
    elif el.type == "image":
        if not el.image_path:
            raise ValueError(
                f"{el.id}: image element has no image_path (type='image' "
                f"requires the path of a file on disk)")
        path = resolve_image_path(el.image_path)
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"{el.id}: image file not found: {el.image_path} "
                f"(resolved to {path})")
        shp = slide.shapes.add_picture(
            path, Inches(el.x_in), Inches(el.y_in),
            Inches(el.w_in), Inches(el.h_in))
    elif el.type == "ellipse":
        shp = slide.shapes.add_shape(
            MSO_SHAPE.OVAL, Inches(el.x_in), Inches(el.y_in),
            Inches(el.w_in), Inches(el.h_in))
    else:  # rect
        shp = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Inches(el.x_in), Inches(el.y_in),
            Inches(el.w_in), Inches(el.h_in))
    return shp


def render_pptx(spec: PageSpec, out_path: str) -> None:
    prs = Presentation()
    prs.slide_width = Inches(spec.width_in)
    prs.slide_height = Inches(spec.height_in)
    slide = prs.slides.add_slide(prs.slide_layouts[6])   # 空白版式
    # 画布变大/变小后字号跟着走（用户 m05688），比例取自图框尺寸。
    scale = palette.spec_scale(spec)

    for el in spec.elements:
        shp = _add_shape(slide, el)
        shp.name = el.id                                  # 回读校验的主键

        # 图片没有 fill / line：PICTURE 的填充由位图本身决定，设了会 AttributeError。
        if el.type != "image":
            apply_fill(shp, el)

        if el.type == "text":
            # 字号按 el.role 查色板字号表（m04549）再乘画布缩放（m05688）。
            apply_text_style(shp, el, scale)

    prs.save(out_path)
