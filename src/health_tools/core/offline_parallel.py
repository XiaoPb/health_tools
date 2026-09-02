"""离线跑库并发任务的发现与输出隔离模型。"""

import hashlib
import re
import shutil
from collections import deque
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Deque, Dict, List, Optional, Sequence, Tuple

from health_tools.core.offline import (
    OfflineRunResult,
    count_supported_csv_files,
    reorganize_output,
)
from health_tools.core.offline_input_filter import MovedOfflineInput, move_offline_input


@dataclass(frozen=True)
class OfflineTask:
    """一个一级输入目录对应的离线任务。"""

    task_id: str
    input_dir: Path
    relative_dir: Path
    raw_output: Optional[Path] = None
    log_path: Optional[Path] = field(default=None, kw_only=True)
    attempts: int = 0
    last_failed_csv: Optional[Path] = None
    moved_files: Tuple[MovedOfflineInput, ...] = ()


@dataclass(frozen=True)
class OfflineTaskResult:
    """单个离线任务的最终尝试结果。"""

    task: OfflineTask
    run_result: OfflineRunResult
    status: str
    reason: str = ""


@dataclass(frozen=True)
class OfflineTaskBatch:
    """一批离线任务的稳定汇总。"""

    succeeded: Tuple[OfflineTaskResult, ...]
    failed: Tuple[OfflineTaskResult, ...]


@dataclass(frozen=True)
class OfflineMergeResult:
    """任务私有输出合并到版本目录后的稳定汇总。"""

    succeeded: Tuple[OfflineTaskResult, ...]
    failed: Tuple[OfflineTaskResult, ...]


def safe_task_name(name: str) -> str:
    """保留 Unicode 文字，将不适合任务目录的标点压缩为下划线。"""
    safe = re.sub(r"[^\w.-]+", "_", name, flags=re.UNICODE).strip("_")
    return safe or "task"


def _utf16_units(value: str) -> int:
    """返回字符串占用的 UTF-16 编码单元数。"""
    return sum(2 if ord(character) > 0xFFFF else 1 for character in value)


def _truncate_utf16(value: str, max_units: int) -> str:
    """在不拆分非 BMP 字符的前提下按 UTF-16 编码单元截断。"""
    used_units = 0
    characters = []
    for character in value:
        character_units = 2 if ord(character) > 0xFFFF else 1
        if used_units + character_units > max_units:
            break
        characters.append(character)
        used_units += character_units
    return "".join(characters)


def _build_task_id(index: int, name: str) -> str:
    """构造不超过 251 个 UTF-16 编码单元的稳定任务 ID。"""
    prefix = f"{index:04d}_"
    safe_name = safe_task_name(name)
    task_id = f"{prefix}{safe_name}"
    if _utf16_units(task_id) <= 251:
        return task_id

    digest = hashlib.sha256(safe_name.encode("utf-8")).hexdigest()[:8]
    suffix = f"_{digest}"
    name_units = 251 - _utf16_units(prefix) - _utf16_units(suffix)
    return f"{prefix}{_truncate_utf16(safe_name, name_units)}{suffix}"


def discover_offline_tasks(input_dir: Path) -> List[OfflineTask]:
    """按离线跑库约定发现输入任务，并按目录名稳定排序。"""
    input_dir = Path(input_dir)
    children = sorted(path for path in input_dir.iterdir() if path.is_dir())
    if not children:
        return [OfflineTask("0000_root", input_dir, Path())]

    candidates = [path for path in children if count_supported_csv_files(path) > 0]
    return [
        OfflineTask(
            task_id=_build_task_id(index, path.name),
            input_dir=path,
            relative_dir=Path(path.name),
        )
        for index, path in enumerate(candidates)
    ]


def assign_task_outputs(tasks: List[OfflineTask], version_output: Path) -> List[OfflineTask]:
    """为每个任务分配版本目录下互不冲突的私有 raw 输出目录。"""
    version_output = Path(version_output)
    return [
        replace(
            task,
            raw_output=version_output / ".offline_tasks" / task.task_id / "raw",
            log_path=version_output / "offline_logs" / f"{task.task_id}.log",
        )
        for task in tasks
    ]


def merge_task_outputs(
    version_output: Path,
    task_results: Sequence[OfflineTaskResult],
    *,
    cleanup: bool = True,
) -> OfflineMergeResult:
    """整理成功任务的私有输出，并在确认无冲突后合并到版本目录。"""
    version_output = Path(version_output)
    ordered_results = sorted(task_results, key=lambda item: item.task.task_id)
    planned_moves: Dict[Path, Tuple[Path, OfflineTaskResult]] = {}
    conflicts: List[Path] = []

    for task_result in ordered_results:
        task = task_result.task
        if task.raw_output is None:
            reason = f"任务 {task.task_id} 未分配 raw 输出目录"
            failed = tuple(
                replace(item, status="failed", reason=reason) for item in ordered_results
            )
            return OfflineMergeResult((), failed)

        try:
            task_reorganized = reorganize_output(
                task.input_dir,
                task.raw_output,
                show_progress=False,
            )
        except Exception as exc:
            reason = f"整理输出失败: {exc}"
            failed = tuple(
                replace(item, status="failed", reason=reason) for item in ordered_results
            )
            return OfflineMergeResult((), failed)

        destination_root = version_output / "数据整理" / task.relative_dir
        for source in sorted(path for path in task_reorganized.rglob("*") if path.is_file()):
            destination = destination_root / source.relative_to(task_reorganized)
            if destination.exists() or destination in planned_moves:
                conflicts.append(destination)
                continue
            planned_moves[destination] = (source, task_result)

    if conflicts:
        conflict_text = ", ".join(str(path) for path in sorted(set(conflicts), key=str))
        reason = f"目标文件冲突: {conflict_text}"
        failed = tuple(replace(item, status="failed", reason=reason) for item in ordered_results)
        return OfflineMergeResult((), failed)

    completed_moves: List[Tuple[Path, Path]] = []
    try:
        for destination, (source, _task_result) in sorted(
            planned_moves.items(), key=lambda item: str(item[0])
        ):
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            completed_moves.append((source, destination))
    except OSError as exc:
        rollback_failures = []
        for source, destination in reversed(completed_moves):
            try:
                source.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(destination), str(source))
            except OSError as rollback_exc:
                rollback_failures.append(f"{destination}: {rollback_exc}")
        reason = f"合并输出失败: {exc}"
        if rollback_failures:
            reason += "; 回滚失败: " + ", ".join(rollback_failures)
        failed = tuple(replace(item, status="failed", reason=reason) for item in ordered_results)
        return OfflineMergeResult((), failed)

    task_root = version_output / ".offline_tasks"
    if cleanup and task_root.exists():
        shutil.rmtree(task_root)
    return OfflineMergeResult(tuple(ordered_results), ())


def run_offline_tasks(
    tasks: List[OfflineTask],
    runner_factory: Callable[[OfflineTask], object],
    input_root: Path,
    *,
    workers: int = 8,
    timeout: int = 300,
    settle_timeout: int = 10,
    is_cancelled: Optional[Callable[[], bool]] = None,
) -> OfflineTaskBatch:
    """并发执行离线任务，隔离失败输入并公平地将可重试任务重新入队。"""

    if not tasks:
        return OfflineTaskBatch((), ())
    worker_count = max(1, min(int(workers), 8, len(tasks)))
    input_root = Path(input_root)
    cancelled = is_cancelled or (lambda: False)
    pending: Deque[OfflineTask] = deque(tasks)
    active: Dict[Future[OfflineTaskResult], OfflineTask] = {}
    results: Dict[str, OfflineTaskResult] = {}

    def attempt(task: OfflineTask) -> OfflineTaskResult:
        runner = runner_factory(task)
        if task.raw_output is None:
            raise RuntimeError(f"任务 {task.task_id} 未分配 raw 输出目录")
        run_result = runner.run(
            task.input_dir,
            task.raw_output,
            timeout=timeout,
            settle_timeout=settle_timeout,
            is_cancelled=cancelled,
            log_path=task.log_path,
            attempt=task.attempts + 1,
        )
        return OfflineTaskResult(task, run_result, "succeeded" if run_result.success else "failed")

    def failed_result(
        task: OfflineTask, run_result: OfflineRunResult, reason: str
    ) -> OfflineTaskResult:
        return OfflineTaskResult(task, run_result, "failed", reason)

    def submit_available(executor: ThreadPoolExecutor) -> None:
        while pending and len(active) < worker_count and not cancelled():
            task = pending.popleft()
            future = executor.submit(attempt, task)
            active[future] = task

    executor = ThreadPoolExecutor(max_workers=worker_count)
    try:
        submit_available(executor)
        while active or pending:
            if cancelled():
                for future in active:
                    future.cancel()
                # Wait for already-running runners so their process cleanup completes.
                wait(tuple(active))
                raise InterruptedError("离线任务已取消")
            if not active:
                submit_available(executor)
                continue
            done, _ = wait(tuple(active), return_when=FIRST_COMPLETED)
            for future in sorted(done, key=lambda item: active[item].task_id):
                task = active.pop(future)
                try:
                    outcome = future.result()
                except InterruptedError:
                    raise
                except Exception as exc:  # 单任务异常隔离，继续处理其他任务
                    run_result = OfflineRunResult(success=False, error=str(exc))
                    results[task.task_id] = failed_result(
                        replace(task, attempts=task.attempts + 1), run_result, str(exc)
                    )
                    continue

                run_result = outcome.run_result
                attempted_task = replace(task, attempts=task.attempts + 1)
                if run_result.success:
                    results[task.task_id] = replace(outcome, task=attempted_task)
                    continue

                last_csv = run_result.last_csv_path
                if last_csv is None:
                    results[task.task_id] = failed_result(
                        attempted_task, run_result, run_result.error or "日志未定位失败 CSV"
                    )
                    continue
                last_csv = Path(last_csv).resolve()
                if task.last_failed_csv is not None and last_csv == task.last_failed_csv.resolve():
                    results[task.task_id] = failed_result(
                        attempted_task, run_result, "重复失败文件"
                    )
                    continue
                if not last_csv.is_file():
                    results[task.task_id] = failed_result(
                        attempted_task, run_result, "失败 CSV 已不存在"
                    )
                    continue
                try:
                    moved = move_offline_input(last_csv, input_root, "算法执行失败")
                except Exception as exc:
                    results[task.task_id] = failed_result(attempted_task, run_result, str(exc))
                    continue
                updated = replace(
                    attempted_task,
                    last_failed_csv=last_csv,
                    moved_files=attempted_task.moved_files + (moved,),
                )
                if count_supported_csv_files(task.input_dir) <= 0:
                    results[task.task_id] = failed_result(
                        updated, run_result, "隔离后目录没有剩余 CSV"
                    )
                else:
                    pending.append(updated)
            submit_available(executor)
    finally:
        executor.shutdown(wait=True, cancel_futures=True)

    ordered = sorted(results.values(), key=lambda item: item.task.task_id)
    return OfflineTaskBatch(
        tuple(item for item in ordered if item.status == "succeeded"),
        tuple(item for item in ordered if item.status != "succeeded"),
    )
