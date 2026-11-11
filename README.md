# 新闻数据可视化工作区

把报纸数据版做成「可编辑」的信息图（PowerPoint 原生图表，能点开改数据）。

## 目录

- `assets/` 版面原图
- `assets/icons/` 图标（PIL 画出来的温度计、雪花、水滴、暖气片、火焰、袜子、杯子、叶子等，`_soft` 是淡化版做背景）
- `db/assets.db` SQLite 素材库：pages / assets / paragraphs / chart_points
- `out/` 成品 pptx 与每轮预览 PNG
- `scripts/` 全部脚本

## 跑一遍

```powershell
$py = 'C:\Users\29642\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$env:PYTHONIOENCODING='utf-8'

& $py scripts\fetch_assets.py                       # 抓版面+正文+原图，写库
& $py scripts\seed_chart_data.py                    # 把图上的数据点写进 chart_points
& $py scripts\make_icons.py                         # 生成图标
& $py scripts\make_soft_icons.py                    # 生成淡化图标
& $py scripts\build_onepage.py                      # 出 pptx
```

## 导预览图

```powershell
$src='...\out\时令小家电换季热销_单页复刻.pptx'
$dir='...\out\preview'
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$app = New-Object -ComObject PowerPoint.Application
$pres = $app.Presentations.Open($src,$true,$false,$false)
$pres.SaveCopyAs("$dir\p",18)   # 18 = PNG
$pres.Close(); $app.Quit()
```

## 版式规则

坐标一律 `原图像素 / 100 = 英寸`，所以画布是 10 × 14.17 英寸，比例跟原图 1000×1417 完全一致。
原图每个区块的位置照抄，改版就改脚本里的像素坐标。

## 换一篇新闻

`fetch_assets.py` 接受版面 URL 参数，抓完改 `seed_chart_data.py` 里的 DATA 列表（图上数字得人肉读），再跑 `build_onepage.py`。
