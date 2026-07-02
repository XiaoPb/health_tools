"""批量命令结果收集与摘要输出。"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

from rich.console import Console
from rich.table import Table

from health_tools.utils.errors import (
    REASON_PROCESS_FAILED,
    classify_exception,
    normalize_reason,
)


STATUS_OK = "OK"
STATUS_SKIP = "SKIP"
STATUS_FAIL = "FAIL"
STATUS_WARN = "WARN"


@dataclass
class FileResult:
    """单个输入文件的处理结果。"""

    status: str
    input: str
    output: str = ""
    reason: str = ""
    detail: str = ""
    category: str = ""
    rows: int = 0


class ResultCollector:
    """收集批量处理结果并提供统计。"""

    def __init__(self) -> None:
        self.results: List[FileResult] = []

    def add(self, result: FileResult) -> FileResult:
        result.reason = (
            normalize_reason(result.reason) if result.status != STATUS_OK else result.reason
        )
        self.results.append(result)
        return result

    def add_ok(
        self,
        input_path: object,
        output: object = "",
        detail: str = "",
        category: str = "",
        rows: int = 0,
    ) -> FileResult:
        return self.add(
            FileResult(
                status=STATUS_OK,
                input=_path_text(input_path),
                output=_path_text(output),
                detail=detail,
                category=category,
                rows=rows,
            )
        )

    def add_skip(
        self,
        input_path: object,
        reason: str,
        output: object = "",
        detail: str = "",
        category: str = "",
        rows: int = 0,
    ) -> FileResult:
        return self.add(
            FileResult(
                status=STATUS_SKIP,
                input=_path_text(input_path),
                output=_path_text(output),
                reason=reason,
                detail=detail,
                category=category,
                rows=rows,
            )
        )

    def add_fail(
        self,
        input_path: object,
        reason: str = REASON_PROCESS_FAILED,
        output: object = "",
        detail: str = "",
        category: str = "",
        rows: int = 0,
    ) -> FileResult:
        return self.add(
            FileResult(
                status=STATUS_FAIL,
                input=_path_text(input_path),
                output=_path_text(output),
                reason=reason,
                detail=detail,
                category=category,
                rows=rows,
            )
        )

    def add_exception(
        self,
        input_path: object,
        exc: BaseException,
        output: object = "",
        default_reason: str = REASON_PROCESS_FAILED,
    ) -> FileResult:
        return self.add_fail(
            input_path,
            reason=classify_exception(exc, default=default_reason),
            output=output,
            detail=str(exc),
        )

    def count(self, status: str) -> int:
        return sum(1 for result in self.results if result.status == status)

    def by_reason(self) -> Counter:
        return Counter(
            normalize_reason(result.reason)
            for result in self.results
            if result.status in {STATUS_SKIP, STATUS_FAIL, STATUS_WARN}
        )

    def problems(self) -> List[FileResult]:
        return [r for r in self.results if r.status in {STATUS_SKIP, STATUS_FAIL, STATUS_WARN}]

    def __len__(self) -> int:
        return len(self.results)


def result_from_exception(
    input_path: object,
    exc: BaseException,
    output: object = "",
    default_reason: str = REASON_PROCESS_FAILED,
) -> FileResult:
    """根据异常创建失败结果。"""
    return FileResult(
        status=STATUS_FAIL,
        input=_path_text(input_path),
        output=_path_text(output),
        reason=classify_exception(exc, default=default_reason),
        detail=str(exc),
    )


def print_summary(
    title: str,
    collector: ResultCollector,
    console: Optional[Console] = None,
    verbose: bool = False,
    max_examples: int = 10,
) -> None:
    """打印批量处理摘要，默认只展示聚合信息。"""
    console = console or Console()
    total = len(collector)
    ok_count = collector.count(STATUS_OK)
    skip_count = collector.count(STATUS_SKIP)
    fail_count = collector.count(STATUS_FAIL)
    warn_count = collector.count(STATUS_WARN)

    if total == 0:
        console.print(f"[yellow]{title}: 未处理任何文件[/yellow]")
        return

    console.print(
        f"[bold]{title}[/bold]: "
        f"[green]{ok_count} 成功[/green], "
        f"[yellow]{skip_count} 跳过[/yellow], "
        f"[red]{fail_count} 失败[/red], "
        f"[yellow]{warn_count} 警告[/yellow], "
        f"共 {total} 个文件"
    )

    reason_counts = collector.by_reason()
    if reason_counts:
        table = Table(title="异常/跳过原因统计", show_header=True)
        table.add_column("原因")
        table.add_column("数量", justify="right")
        for reason, count in reason_counts.most_common():
            table.add_row(reason, str(count))
        console.print(table)

    problem_results = collector.problems()
    if not verbose or not problem_results:
        return

    table = Table(title="文件明细", show_header=True)
    table.add_column("状态", no_wrap=True)
    table.add_column("文件")
    table.add_column("原因")
    table.add_column("说明")
    for result in problem_results[:max_examples]:
        table.add_row(
            _styled_status(result.status),
            _display_path(result.input),
            result.reason,
            result.detail,
        )
    console.print(table)
    if len(problem_results) > max_examples:
        console.print(f"[dim]仅显示前 {max_examples} 条，共 {len(problem_results)} 条。[/dim]")


def collector_from_results(results: Iterable[FileResult]) -> ResultCollector:
    collector = ResultCollector()
    for result in results:
        collector.add(result)
    return collector


def _path_text(path: object) -> str:
    if path is None:
        return ""
    if isinstance(path, Path):
        return str(path)
    return str(path)


def _display_path(path_text: str) -> str:
    if not path_text:
        return ""
    return Path(path_text).name


def _styled_status(status: str) -> str:
    style = {
        STATUS_OK: "green",
        STATUS_SKIP: "yellow",
        STATUS_FAIL: "red",
        STATUS_WARN: "yellow",
    }.get(status, "")
    return f"[{style}]{status}[/{style}]" if style else status
