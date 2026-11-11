"""生成报纸原版区块③的对照演示（百分比数据，带皮肤）。

用户 m02007 / m02273：0 点 = 球泡最上方顶点；柱体右侧刻度；外圈一圈。
数据取自原图「加热电器消费情况」：118% / 102% / 84% / 80% / 65%。
"""
from loop.render_thermo import render_pptx_thermo
from loop.preview import render_preview
from loop.scaffold import build_pagespec

PTS = [
    {"seq": 1, "label": "电热水龙头", "value": 118, "unit": "%"},
    {"seq": 2, "label": "台式即热\n饮水机", "value": 102, "unit": "%"},
    {"seq": 3, "label": "商用\n热水器", "value": 84, "unit": "%"},
    {"seq": 4, "label": "车载电热\n水壶/杯", "value": 80, "unit": "%"},
    {"seq": 5, "label": "电热\n饭盒", "value": 65, "unit": "%"},
]


def main(out_dir: str = "out/paper_c3") -> None:
    spec = build_pagespec(
        PTS, chart_title="加热电器细分品类成交额环比增速TOP5",
        width_in=10.0, height_in=6.0,
    )
    render_pptx_thermo(spec, f"{out_dir}/loop1.pptx")
    render_preview(spec, f"{out_dir}/preview.png")
    print(f"{out_dir}/loop1.pptx")
    print(f"{out_dir}/preview.png")


if __name__ == "__main__":
    import os
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "out/paper_c3"
    os.makedirs(target, exist_ok=True)
    main(target)
