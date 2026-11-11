"""回读校验：把 PPTX 里的形状按 name 读成可断言的字典。

用于证明「液柱是 AUTO_SHAPE 而非 PICTURE」「EMU 高度 = 3.0*v/V_max」。
"""
from pptx import Presentation


def read_shapes(pptx_path: str) -> dict[str, dict]:
    prs = Presentation(pptx_path)
    out: dict[str, dict] = {}
    for sh in prs.slides[0].shapes:
        # auto_shape_type / adjustments 只在 AUTO_SHAPE 上有意义；文本框返回 None/[]。
        try:
            ast = sh.auto_shape_type
            ast_name = getattr(ast, "name", None) or (str(ast) if ast else None)
        except (AttributeError, ValueError):
            ast_name = None
        try:
            adjs = [float(a) for a in sh.adjustments]
        except (AttributeError, ValueError):
            adjs = []
        out[sh.name] = {
            "shape_type": sh.shape_type,
            "height": int(sh.height),
            "left": int(sh.left),
            "top": int(sh.top),
            "width": int(sh.width),
            "text": sh.text if sh.has_text_frame else "",
            "auto_shape_type": ast_name,
            "adjustments": adjs,
        }
    return out
