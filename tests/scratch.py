"""测试专用工具：把临时目录固定在工作区内。

DSH 的 workspace-write 沙箱拒绝写工作区之外的路径；裸
`tempfile.mkdtemp()` 会落到 `%TEMP%\\dsh-*` 并以
`PermissionError: [Errno 13] Permission denied` 失败。

更精确的实测结论（scripts/_probe_dirs.py，同一进程内三选一）：
  * `os.makedirs()` 新建目录 → 可写（pptx.save 成功）
  * `os.mkdir()`   新建目录 → 可写（pptx.save 成功）
  * `tempfile.mkdtemp()` 新建目录 → **不可写**（即便 dir= 指向工作区内）

也就是说问题出在 `tempfile.mkdtemp()` 本身，不是「Python 运行时新建目录」
一律被拒。因此这里用 `os.makedirs()` + uuid 造唯一目录，既落在工作区内、
又不碰被拒的 tempfile 路径，测试之间仍然彼此隔离。造过的目录在进程退出时
由 atexit 清理，不在 out/scratch/ 堆积产物。
"""
import atexit
import os
import shutil
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = os.path.join(ROOT, "out", "scratch")

_TEMPDIRS: list[str] = []


def mkdtemp(prefix: str = "case-") -> str:
    """新建并返回一个可写的工作区内唯一目录（不用 tempfile.mkdtemp）。"""
    os.makedirs(SCRATCH, exist_ok=True)
    d = os.path.join(SCRATCH, f"{prefix}{uuid.uuid4().hex[:10]}")
    os.makedirs(d)
    _TEMPDIRS.append(d)
    return d


@atexit.register
def _cleanup() -> None:
    for d in _TEMPDIRS:
        shutil.rmtree(d, ignore_errors=True)
    _TEMPDIRS.clear()
