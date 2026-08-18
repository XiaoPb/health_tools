"""离线算法跑库公共 API。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from health_tools.api.context import ExecutionContext
from health_tools.api.errors import (
    CallbackError,
    OperationCancelled,
    OperationError,
    RequestValidationError,
)
from health_tools.api.models import (
    BatchResult,
    ItemResult,
    ItemStatus,
    OfflineRequest,
    OfflineResult,
    ProgressEvent,
)
from health_tools.api.operations import _batch, _context, _require_path


def _configured_versions(chip: str) -> List[Optional[str]]:
    from health_tools.core.offline import get_offline_config

    config = get_offline_config().versions.get(chip, {})
    values = config.get("versions", {}) if isinstance(config, dict) else {}
    if isinstance(values, dict):
        return [version for entries in values.values() for version in entries]
    return list(values) if isinstance(values, list) else []


def _resolve_versions(request: OfflineRequest) -> List[Optional[str]]:
    if request.all_versions and (request.ver or request.versions):
        raise RequestValidationError("--all-versions 不能与 --version/--versions 同时使用")
    if request.ver and request.versions:
        raise RequestValidationError("--version 不能与 --versions 同时使用")
    if request.all_versions:
        if not request.chip_name:
            raise RequestValidationError("all_versions 需要 chip_name")
        versions = _configured_versions(request.chip_name)
        if not versions:
            raise RequestValidationError(f"未找到 {request.chip_name} 的已配置版本")
        return versions
    if request.versions:
        if not request.chip_name:
            raise RequestValidationError("versions 需要 chip_name")
        result: List[Optional[str]] = list(
            dict.fromkeys(value.strip() for value in request.versions.split(",") if value.strip())
        )
        if not result:
            raise RequestValidationError("versions 未提供有效版本")
        return result
    return [request.ver]


def _discover_versions(output: Path) -> List[Optional[str]]:
    if not output.exists() or (output / "数据整理").exists():
        return []
    discovered: List[Optional[str]] = [
        path.name
        for path in sorted(output.iterdir())
        if path.is_dir() and (path / "数据整理").exists()
    ]
    return discovered


def _version_output(output: Path, version: Optional[str], executable: Optional[Path]) -> Path:
    name = str(version) if version else (executable.parent.name if executable else None)
    return output / name if name else output


def _acc_mode(executable: Optional[Path]) -> str:
    if executable is None:
        return "axis"
    from health_tools.core.offline import get_category_label

    return (
        "rms"
        if get_category_label(executable.parent.parent.name.lower()) in {"medium", "basic"}
        else "axis"
    )


def _cancel_callback(context: ExecutionContext):
    def check() -> bool:
        if context.is_cancelled is None:
            return False
        try:
            return bool(context.is_cancelled())
        except Exception as exc:
            raise CallbackError(f"取消回调执行失败: {exc}") from exc

    return check


def _filter_input_files(input_dir: Path, chip_name: str):
    from health_tools.core.offline_input_filter import filter_offline_inputs
    from health_tools.rules.loader import RuleLoader

    return filter_offline_inputs(input_dir, RuleLoader.load_chip_rule(chip_name))


def run_offline(
    request: OfflineRequest, *, context: Optional[ExecutionContext] = None
) -> OfflineResult:
    """运行一个或多个离线算法版本并生成整理、PSD 和准确度结果。"""
    import pandas as pd

    from health_tools.core.offline import (
        OfflineConfigError,
        OfflineRunner,
        calculate_offline_accuracy,
        count_supported_csv_files,
        find_exe,
        list_versions,
        load_local_cmd_config,
        reorganize_output,
    )
    from health_tools.utils.accuracy import normalize_accuracy_thresholds

    ctx = _context(context)
    try:
        accuracy_thresholds = normalize_accuracy_thresholds(request.accuracy_thresholds)
    except ValueError as exc:
        raise RequestValidationError(str(exc)) from exc
    use_custom_accuracy = accuracy_thresholds is not None or request.accuracy_inclusive
    if request.do_list:
        ctx.check_cancelled("list")
        ctx.emit(ProgressEvent("offline", "list", 0, 1, "读取版本"))
        listed = list_versions(request.chip_name)
        versions: List[str] = []
        for info in listed.values():
            values = info.get("versions", {})
            if isinstance(values, dict):
                versions.extend(version for entries in values.values() for version in entries)
            elif isinstance(values, list):
                versions.extend(values)
        ctx.emit(ProgressEvent("offline", "list", 1, 1, "完成"))
        return OfflineResult(BatchResult("offline"), versions=tuple(versions))
    if request.input_path is None:
        raise RequestValidationError("需要指定 input_path")
    input_dir = _require_path(request.input_path)
    if not input_dir.is_dir():
        raise RequestValidationError(f"输入路径必须是目录: {input_dir}")
    output_dir = request.output_path or input_dir.parent / f"{input_dir.name}_offline_result"
    target_versions = _resolve_versions(request)
    if request.no_run and target_versions == [None]:
        target_versions = _discover_versions(output_dir) or target_versions
    multi_version = len(target_versions) > 1
    executables: Dict[Optional[str], Optional[Path]] = {}
    runners: Dict[Optional[str], OfflineRunner] = {}
    runner_messages: Dict[Optional[str], str] = {}

    if not request.no_run:
        if not request.chip_name:
            raise RequestValidationError("执行跑库需要 chip_name")
        for version in target_versions:
            executable = find_exe(request.chip_name, version)
            if executable is None:
                raise RequestValidationError(
                    f"未找到 {request.chip_name} 的离线工具: {version or '默认版本'}"
                )
            executables[version] = executable
            try:
                load_local_cmd_config(executable.parent)
                runner = OfflineRunner(
                    chip=request.chip_name,
                    version=version,
                    hba_fs=request.hba_fs,
                    scene_en=request.scene_en,
                    ch_num=request.ch_num,
                    column_indices=(
                        {"polar": request.ref_col} if request.ref_col is not None else None
                    ),
                    ppg_offset=request.ppg_offset,
                    ppg_maps=request.ppg_maps,
                )
                mapping = runner.resolve_ppg_mapping()
                messages = []
                if mapping:
                    messages.append(
                        "PPG列映射: "
                        + ", ".join(f"{name}={value}" for name, value in mapping.items())
                    )
                messages.extend(getattr(runner, "ppg_warnings", []))
                runner_messages[version] = "\n".join(messages)
                runners[version] = runner
            except OfflineConfigError as exc:
                raise RequestValidationError(f"离线工具配置无效: {exc}") from exc
        try:
            filtered = _filter_input_files(input_dir, request.chip_name)
        except Exception as exc:
            raise OperationError(str(exc)) from exc
        if filtered is not None and filtered.accepted_count == 0:
            raise OperationError("没有符合芯片规则的 CSV 文件，已停止跑库")
    elif multi_version:
        missing = [
            output_dir / str(version)
            for version in target_versions
            if not (output_dir / str(version)).exists()
        ]
        if missing:
            raise RequestValidationError(
                f"多版本 no_run 缺少结果目录: {', '.join(map(str, missing))}"
            )

    items: List[ItemResult] = []
    artifacts: List[Path] = []
    reports = []
    total_stages = len(target_versions) * (
        (0 if request.no_run else 1)
        + 1
        + (0 if request.no_plot else 1)
        + (0 if request.no_accuracy else 1)
    )
    completed = 0
    effective_timeout = request.timeout
    if request.timeout == 300:
        effective_timeout = 300 + max(0, count_supported_csv_files(input_dir) - 50) * 20

    def stage(name: str, message: str, current: Optional[str] = None) -> None:
        nonlocal completed
        ctx.check_cancelled(name, _batch("offline", items, artifacts))
        ctx.emit(ProgressEvent("offline", name, completed, total_stages, message, current))

    for version in target_versions:
        executable = executables.get(version)
        version_output = _version_output(output_dir, version, executable)
        label = str(version or (executable.parent.name if executable else "default"))
        if not request.no_run:
            stage("run", "运行离线算法", label)
            try:
                run_kwargs: Dict[str, Any] = {
                    "timeout": effective_timeout,
                    "settle_timeout": request.settle_timeout,
                }
                if ctx.is_cancelled:
                    run_kwargs["is_cancelled"] = _cancel_callback(ctx)
                run_result = runners[version].run(input_dir, version_output, **run_kwargs)
            except InterruptedError:
                partial = _batch("offline", items, artifacts)
                if ctx.is_cancelled:
                    ctx.check_cancelled("run", partial)
                raise OperationCancelled("run", partial)
            if not getattr(run_result, "success", False):
                items.append(
                    ItemResult(
                        ItemStatus.FAIL,
                        label,
                        str(version_output),
                        "外部工具失败",
                        getattr(run_result, "error", None) or "离线工具执行失败",
                    )
                )
                raise OperationError(getattr(run_result, "error", None) or "离线工具执行失败")
            completed += 1
            items.append(
                ItemResult(
                    ItemStatus.WARN if getattr(run_result, "warning", None) else ItemStatus.OK,
                    label,
                    str(version_output),
                    detail=(
                        "诊断:\n"
                        f"命令: {getattr(run_result, 'command', '')}\n"
                        f"返回码: {getattr(run_result, 'returncode', '')}\n"
                        f"输入CSV: {getattr(run_result, 'input_count', '')}\n"
                        f"结果VSHB: {getattr(run_result, 'result_count', '')}\n"
                        f"{runner_messages.get(version, '')}\n"
                        f"{getattr(run_result, 'warning', None) or ''}"
                    ),
                )
            )
        elif request.chip_name:
            executable = find_exe(request.chip_name, version)

        stage("reorganize", "整理离线结果", label)
        reorganized = version_output / "数据整理"
        if not (request.no_run and reorganized.exists()):
            reorganized = reorganize_output(input_dir, version_output, show_progress=False)
        artifacts.append(reorganized)
        completed += 1

        if not request.no_plot:
            stage("plot", "生成 PSD 图", label)
            from health_tools.core.psd_plotter import PsdPlotter

            if use_custom_accuracy:
                saved = PsdPlotter().plot(
                    reorganized,
                    save_dir=version_output / "psd_bmpfile",
                    show_progress=False,
                    acc_mode=_acc_mode(executable),
                    save_to_source=True,
                    accuracy_thresholds=accuracy_thresholds,
                    accuracy_inclusive=request.accuracy_inclusive,
                )
            else:
                saved = PsdPlotter().plot(
                    reorganized,
                    save_dir=version_output / "psd_bmpfile",
                    show_progress=False,
                    acc_mode=_acc_mode(executable),
                    save_to_source=True,
                )
            artifacts.extend(saved)
            completed += 1

        if not request.no_accuracy:
            stage("accuracy", "统计准确度", label)
            if use_custom_accuracy:
                report = calculate_offline_accuracy(
                    reorganized,
                    show_progress=False,
                    accuracy_thresholds=accuracy_thresholds,
                    accuracy_inclusive=request.accuracy_inclusive,
                )
            else:
                report = calculate_offline_accuracy(reorganized, show_progress=False)
            if report is not None and not report.empty:
                report_path = reorganized / "accuracy_report.csv"
                report.to_csv(report_path, index=False, encoding="utf-8-sig")
                artifacts.append(report_path)
                reports.append((label, report))
            completed += 1

    if multi_version and reports and not request.no_accuracy:
        frames = []
        for version, report in reports:
            frame = report.copy()
            frame.insert(0, "version", version)
            frames.append(frame)
        combined_path = output_dir / "accuracy_report_all_versions.csv"
        output_dir.mkdir(parents=True, exist_ok=True)
        pd.concat(frames, ignore_index=True).to_csv(
            combined_path, index=False, encoding="utf-8-sig"
        )
        artifacts.append(combined_path)
    result_batch = _batch("offline", items, artifacts)
    ctx.check_cancelled("complete", result_batch)
    ctx.emit(ProgressEvent("offline", "complete", completed, total_stages, "完成"))
    reports_paths = tuple(path for path in artifacts if path.name.startswith("accuracy_report"))
    return OfflineResult(
        result_batch,
        output_dir=output_dir,
        versions=tuple(str(version) for version in target_versions if version is not None),
        reports=reports_paths,
    )
