"""统一的命令行进度条工具。"""

from collections.abc import Iterable, Iterator
from typing import Optional, TypeVar

from rich.console import Console
from rich.progress import Progress

T = TypeVar("T")


def progress_track(
    items: Iterable[T],
    description: str,
    console: Optional[Console] = None,
    enabled: bool = True,
    total: Optional[int] = None,
) -> Iterator[T]:
    """使用 Rich 显示进度条，或在关闭时原样迭代。"""
    if not enabled:
        yield from items
        return

    with Progress(console=console) as progress:
        yield from progress.track(items, description=description, total=total)
