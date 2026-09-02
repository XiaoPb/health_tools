"""公共 API 到 Click/Rich 终端的适配工具。"""

from contextlib import AbstractContextManager
from typing import Dict, Optional

import click
from rich.console import Console
from rich.progress import Progress, TaskID

from health_tools.api import (
    BatchResult,
    ExecutionContext,
    GHealthError,
    ItemStatus,
    ProgressEvent,
)
from health_tools.utils.reporting import FileResult, ResultCollector, print_summary


class CliExecution(AbstractContextManager):
    """把 API 进度事件呈现为 Rich 进度条。"""

    def __init__(self, console: Console) -> None:
        self.progress = Progress(console=console)
        self.tasks: Dict[str, TaskID] = {}
        self.context = ExecutionContext(on_progress=self._update)
        self.started = False

    def __enter__(self) -> ExecutionContext:
        return self.context

    def __exit__(self, exc_type, exc_value, traceback) -> Optional[bool]:
        if self.started:
            self.progress.stop()
        return None

    def _update(self, event: ProgressEvent) -> None:
        if event.total is None or event.total <= 1:
            return
        if not self.started:
            self.progress.start()
            self.started = True
        task = self.tasks.get(event.stage)
        if task is None:
            task = self.progress.add_task(event.message or event.stage, total=event.total)
            self.tasks[event.stage] = task
        self.progress.update(
            task, completed=event.completed, description=event.message or event.stage
        )


def print_batch(title: str, result: BatchResult, console: Console, verbose: bool) -> None:
    collector = ResultCollector()
    for item in result.items:
        collector.add(
            FileResult(
                status=item.status.value,
                input=item.input,
                output=item.output,
                reason=item.reason,
                detail=item.detail,
                category=item.category,
                rows=item.rows,
            )
        )
    print_summary(
        title,
        collector,
        console=console,
        verbose=verbose,
        max_examples=len(result.items) if verbose else 10,
    )
    if result.artifacts and verbose:
        console.print("输出文件:")
        for path in result.artifacts:
            console.print(f"  {path}")
    if verbose:
        for item in result.items:
            if item.status is ItemStatus.OK and item.detail:
                console.print(item.detail)


def invoke_api(call):
    try:
        return call()
    except GHealthError as exc:
        raise click.ClickException(str(exc)) from exc
