"""数据分析公共 API 编排。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np  # noqa: F401
    import pandas as pd  # noqa: F401

import fnmatch
import re
import shutil
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from health_tools.api.context import ExecutionContext
from health_tools.api.errors import GHealthError, RequestValidationError
from health_tools.api.models import (
    AnalyzeRequest,
    AnalyzeResult,
    BatchResult,
    CheckRequest,
    EvaluateRequest,
    ItemResult,
    ItemStatus,
    OfflineRequest,
    PlotRequest,
    ProgressEvent,
)
from health_tools.api.operations import _context, _load_rule, _require_path
from health_tools.core.analysis.artifacts import ArtifactIndex
from health_tools.core.analysis.diagnosis import diagnose
from health_tools.core.analysis.models import AnalysisRecord, AnalysisSegment
from health_tools.core.analysis.psd import analyze_psd_directory
from health_tools.core.analysis.raw import analyze_raw_file, detect_chip
from health_tools.core.analysis.reporting import (
    write_evidence_figure,
    write_markdown,
    write_ppt,
    write_structured,
)
from health_tools.core.analysis.workspace import AnalysisWorkspace, request_fingerprint
from health_tools.rules.loader import RuleLoader


def _validate(request: AnalyzeRequest) -> None:
    if request.analysis_type not in {"hr", "spo2", "other"}:
        raise RequestValidationError("analysis_type 仅支持 hr、spo2 或 other")
    if request.analysis_type == "other" and not request.rule_file:
        raise RequestValidationError("other 分析必须提供 --rule")
    if request.scene not in {"auto", "static", "dynamic"}:
        raise RequestValidationError("scene 仅支持 auto、static 或 dynamic")
    if request.report not in {"markdown", "pptx", "all"}:
        raise RequestValidationError("report 仅支持 markdown、pptx 或 all")
    if request.sample_rate is not None and request.sample_rate <= 0:
        raise RequestValidationError("sample_rate 必须大于 0")
    if request.workers < 1:
        raise RequestValidationError("workers 必须大于 0")


def _normalize_accuracy_request(request: AnalyzeRequest) -> AnalyzeRequest:
    from health_tools.utils.accuracy import normalize_accuracy_thresholds

    try:
        thresholds = normalize_accuracy_thresholds(request.accuracy_thresholds)
    except ValueError as exc:
        raise RequestValidationError(str(exc)) from exc
    return replace(request, accuracy_thresholds=thresholds)


def _custom_accuracy(request: AnalyzeRequest) -> bool:
    return request.accuracy_thresholds is not None or request.accuracy_inclusive


def _raw_files(source: Path) -> Tuple[Path, List[Path]]:
    root = source.parent if source.is_file() else source
    files = [source] if source.is_file() else sorted(source.rglob("*.csv"))
    return root, files


def _logical(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _focus(names: Sequence[str], patterns: Sequence[str]) -> Set[str]:
    selected: Set[str] = set()
    for raw_pattern in patterns:
        pattern = raw_pattern.replace("\\", "/")
        matches = {name for name in names if fnmatch.fnmatchcase(name, pattern)}
        if not matches:
            raise RequestValidationError(f"--focus 未匹配任何文件: {raw_pattern}")
        selected.update(matches)
    return selected


def _safe_name(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", value).strip("._") or "analysis"


def _plot_data(
    frame: pd.DataFrame,
    features: Dict[str, object],
    ref_column: Optional[str],
    pred_column: Optional[str],
    timestamp_column: Optional[str],
) -> Dict[str, object]:
    import numpy as np
    import pandas as pd

    rate_value = features.get("sample_rate")
    rate = float(rate_value) if isinstance(rate_value, (int, float, str)) else 1.0
    time = np.arange(len(frame), dtype=float) / rate
    if timestamp_column and timestamp_column in frame.columns:
        timestamp = pd.to_numeric(frame[timestamp_column], errors="coerce")
        if timestamp.notna().sum() > 1:
            values = timestamp.interpolate(limit_direction="both").to_numpy(dtype=float)
            values = values - values[0]
            expected_duration = len(frame) / rate
            if np.nanmax(values) > expected_duration * 10_000:
                values = values / 1_000_000.0
            elif np.nanmax(values) > expected_duration * 10:
                values = values / 1000.0
            time = values
    ppg_value = features.get("ppg_columns")
    acc_value = features.get("acc_columns")
    ppg_columns = (
        [str(value) for value in ppg_value] if isinstance(ppg_value, (list, tuple)) else []
    )
    acc_columns = (
        [str(value) for value in acc_value] if isinstance(acc_value, (list, tuple)) else []
    )
    data: Dict[str, object] = {"time": time}
    if ppg_columns:
        data["ppg"] = pd.to_numeric(frame[ppg_columns[0]], errors="coerce").to_numpy()
        data["ppg_name"] = ppg_columns[0]
        data["ppg_signals"] = {
            column: pd.to_numeric(frame[column], errors="coerce").to_numpy()
            for column in ppg_columns[:2]
        }
    if len(acc_columns) == 3:
        acc = frame[acc_columns].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
        data["acc"] = np.sqrt(np.nansum(np.square(acc), axis=1))
    if ref_column and ref_column in frame.columns:
        data["reference"] = pd.to_numeric(frame[ref_column], errors="coerce").to_numpy()
    if pred_column and pred_column in frame.columns:
        data["prediction"] = pd.to_numeric(frame[pred_column], errors="coerce").to_numpy()
    if len(time) > 1:
        data["sample_interval"] = np.diff(time)
        data["interval_time"] = time[1:]
    frame_column = "FRAME_ID" if "FRAME_ID" in frame.columns else None
    if frame_column:
        data["frame_step"] = pd.to_numeric(frame[frame_column], errors="coerce").diff().to_numpy()
    return data


def _copy_files(files: Sequence[Path], root: Path, output: Path) -> Dict[str, Path]:
    copied: Dict[str, Path] = {}
    for path in files:
        relative = Path(_logical(path, root))
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied[relative.as_posix()] = target
    return copied


def _run_supporting_stages(
    request: AnalyzeRequest,
    source: Path,
    files: Sequence[Path],
    root: Path,
    chip: Optional[str],
    output: Path,
    rule,
    context: ExecutionContext,
) -> Tuple[List[str], Optional[Path], Optional[Path]]:
    notes: List[str] = []
    check_path: Optional[Path] = None
    evaluate_path: Optional[Path] = None
    staging = output / "evaluate_input"
    _copy_files(files, root, staging)
    from health_tools.api.operations import run_evaluate

    try:
        if _custom_accuracy(request):
            evaluate_request = EvaluateRequest(
                input_path=staging,
                output_path=output / "evaluate",
                eval_type=request.analysis_type if request.analysis_type != "other" else "hr",
                ref_column=request.ref_column,
                pred_column=request.pred_column,
                chip=chip,
                accuracy_thresholds=request.accuracy_thresholds,
                accuracy_inclusive=request.accuracy_inclusive,
            )
        else:
            evaluate_request = EvaluateRequest(
                input_path=staging,
                output_path=output / "evaluate",
                eval_type=request.analysis_type if request.analysis_type != "other" else "hr",
                ref_column=request.ref_column,
                pred_column=request.pred_column,
                chip=chip,
            )
        evaluate_result = run_evaluate(
            evaluate_request,
            context=context,
        )
        evaluate_path = next(
            (path for path in evaluate_result.artifacts if path.name == "file_details.csv"),
            None,
        )
    except GHealthError as exc:
        notes.append(f"准确度评估未完成: {exc}")
    return notes, check_path, evaluate_path


def _refresh_diagnosis(record: AnalysisRecord, rule) -> None:
    features = dict(record.features)
    features.update(record.metrics)
    decision = diagnose(features, rule)
    cause = decision["cause"]
    if cause and cause.get("id") == "acc_invalid" and features.get("check_acc_title"):
        cause = {**cause, "title": str(features["check_acc_title"])}
    record.cause = cause
    record.conclusion = decision["conclusion"]
    record.confidence = decision["confidence"]
    record.notes = [decision["evidence"], *record.notes[1:]]


def _polar_warnings(features: Dict[str, object]) -> List[str]:
    issues = features.get("polar_issues")
    if not features.get("polar_review_required") or not isinstance(issues, list):
        return []
    return [f"Polar 警告：{issue}；需人工复审，不据此进行错误归因" for issue in issues]


def _acc_detail_label(column: str) -> str:
    replacements = {
        "ACC全零次数": "全零异常次数",
        "ACC全零最长帧": "全零最长连续帧",
        "ACC全零前10帧": "全零异常帧位置(前10)",
        "ACC静止XYZ次数": "静止异常次数",
        "ACC静止XYZ最长帧": "静止最长连续帧",
        "ACC静止XYZ前10帧": "静止异常帧位置(前10)",
        "ACC循环XYZ次数": "循环异常次数",
        "ACC循环XYZ最长帧": "循环最长连续帧",
        "ACC循环XYZ前10帧": "循环异常帧位置(前10)",
    }
    return replacements.get(column, column)


def _specific_acc_title(values: pd.Series) -> str:
    import numpy as np

    kinds = []
    for column, title in (
        ("ACC全零次数", "全零"),
        ("ACC静止XYZ次数", "静止"),
        ("ACC循环XYZ次数", "循环"),
    ):
        try:
            value = float(values.get(column, 0) or 0)
        except (TypeError, ValueError):
            value = 0.0
        if np.isfinite(value) and value > 0:
            kinds.append(title)
    return f"check 检测到 ACC {'、'.join(kinds)}异常" if kinds else "check 检测到 ACC 异常"


def _apply_check_results(records: List[AnalysisRecord], report_path: Optional[Path], rule) -> None:
    import pandas as pd

    if report_path is None or not report_path.exists():
        return
    report = pd.read_csv(report_path, encoding="utf-8-sig")
    for record in records:
        row = report[
            (report.get("文件相对路径", pd.Series(dtype=str)).astype(str) == record.file)
            | (report.get("文件名", pd.Series(dtype=str)).astype(str) == Path(record.file).name)
        ]
        if row.empty:
            continue
        values = row.iloc[0]
        failures = []
        for column in report.columns:
            if not column.endswith("(结果)") or column == "总异常(结果)":
                continue
            status = str(values.get(column, "")).upper()
            if status == "FAIL":
                failures.append(column.removesuffix("(结果)"))
        record.features["check_failures"] = failures
        details: Dict[str, str] = {}
        for name in failures:
            parts = []
            description = values.get(f"{name}(说明)", "")
            if pd.notna(description) and str(description).strip():
                parts.append(str(description).strip())
            if "ACC" in name.upper():
                for column in report.columns:
                    if not column.upper().startswith("ACC") or column.endswith(
                        ("(结果)", "(说明)")
                    ):
                        continue
                    value = values.get(column, "")
                    text = "" if pd.isna(value) else str(value).strip()
                    if text not in {"", "-", "0", "0.0"}:
                        if column.endswith("前10帧"):
                            text = text.replace(",", "，")
                        parts.append(f"{_acc_detail_label(column)}={text}")
            details[name] = "；".join(parts) or "check 判定失败"
        record.features["check_details"] = details
        if any("帧" in name or "时间戳" in name for name in failures):
            record.features["data_complete"] = False
        record.features["check_range_failed"] = any("范围" in name for name in failures)
        record.features["check_acc_failed"] = any("ACC" in name.upper() for name in failures)
        if record.features["check_acc_failed"]:
            record.features["check_acc_title"] = _specific_acc_title(values)
        record.features["check_signal_failed"] = any(
            "居中" in name or "IPD" in name.upper() for name in failures
        )
        record.features["raw_valid"] = bool(record.features.get("raw_valid") and not failures)
        _refresh_diagnosis(record, rule)


def _apply_evaluate_results(
    records: List[AnalysisRecord], detail_path: Optional[Path], rule
) -> None:
    import pandas as pd

    if detail_path is None or not detail_path.exists():
        return
    details = pd.read_csv(detail_path)
    for record in records:
        row = details[
            details.get("file", pd.Series(dtype=str)).astype(str) == Path(record.file).name
        ]
        if row.empty:
            continue
        values = row.iloc[0]
        for key in ("mae", "rmse", "std", "correlation", "samples"):
            if key in values and pd.notna(values[key]):
                record.metrics[f"evaluate_{key}"] = float(values[key])
                record.features[f"evaluate_{key}"] = float(values[key])
        _refresh_diagnosis(record, rule)


def _raw_records(
    request: AnalyzeRequest,
    source: Path,
    rule,
    context: ExecutionContext,
) -> Tuple[List[AnalysisRecord], Path, List[Path], Set[str], Optional[str]]:
    root, files = _raw_files(source)
    if not files:
        raise RequestValidationError(f"输入目录没有 CSV: {source}")
    names = [_logical(path, root) for path in files]
    focused = _focus(names, request.focus)
    chip = request.chip_name or detect_chip(files[0])
    records: List[AnalysisRecord] = []
    total = len(files)
    context.emit(ProgressEvent("analyze", "raw", 0, total, "分析原始数据"))
    for index, path in enumerate(files, 1):
        context.check_cancelled("raw", records)
        name = _logical(path, root)
        try:
            if _custom_accuracy(request):
                result, frame, _ = analyze_raw_file(
                    path,
                    rule,
                    request.analysis_type,
                    chip_name=request.chip_name,
                    sample_rate=request.sample_rate,
                    ref_column=request.ref_column,
                    pred_column=request.pred_column,
                    timestamp_column=request.timestamp_column,
                    scene_override=request.scene,
                    accuracy_thresholds=request.accuracy_thresholds,
                    accuracy_inclusive=request.accuracy_inclusive,
                )
            else:
                result, frame, _ = analyze_raw_file(
                    path,
                    rule,
                    request.analysis_type,
                    chip_name=request.chip_name,
                    sample_rate=request.sample_rate,
                    ref_column=request.ref_column,
                    pred_column=request.pred_column,
                    timestamp_column=request.timestamp_column,
                    scene_override=request.scene,
                )
            features = result["features"]
            features.update(result["metrics"])
            decision = diagnose(features, rule)
            record = AnalysisRecord(
                file=name,
                source=str(path),
                analysis_type=request.analysis_type,
                scene=str(features.get("scene", "unknown")),
                focused=name in focused,
                features=features,
                metrics=result["metrics"],
                segments=[AnalysisSegment(**segment) for segment in result["segments"]],
                cause=decision["cause"],
                conclusion=decision["conclusion"],
                confidence=decision["confidence"],
                notes=[decision["evidence"]],
                warnings=_polar_warnings(features),
                plot_data=_plot_data(
                    frame,
                    features,
                    request.ref_column or rule.columns.get("reference"),
                    request.pred_column or rule.columns.get("prediction"),
                    request.timestamp_column or rule.columns.get("timestamp"),
                ),
            )
        except Exception as exc:
            record = AnalysisRecord(
                file=name,
                source=str(path),
                analysis_type=request.analysis_type,
                focused=name in focused,
                conclusion="证据不足",
                notes=[f"读取或分析失败: {exc}"],
            )
        records.append(record)
        context.emit(ProgressEvent("analyze", "raw", index, total, "完成", name))
    return records, root, files, focused, chip


def run_raw_stage(request: AnalyzeRequest, source: Path, rule, context: ExecutionContext):
    """可替换的原始数据阶段入口，便于断点编排和测试。"""
    return _raw_records(request, source, rule, context)


def run_check_stage(
    request: AnalyzeRequest,
    source: Path,
    chip: Optional[str],
    output: Path,
    context: ExecutionContext,
) -> Optional[Path]:
    if request.check_report_path is not None:
        return request.check_report_path
    if not chip:
        return None
    from health_tools.api.check_operation import run_check

    result = run_check(
        CheckRequest(
            input_path=source,
            chip_name=chip,
            timestamp_column=request.timestamp_column,
            output_path=output / "check" / "check_report.csv",
            workers=request.workers,
        ),
        context=context,
    )
    return result.report_path


def _merge_psd(record: AnalysisRecord, psd: Dict[str, object], rule) -> None:
    record.psd = psd
    raw_reference_valid = record.features.get("reference_valid")
    record.features.update(psd)
    if raw_reference_valid is False:
        record.features["reference_valid"] = False
    merged_warnings = [*record.warnings, *_polar_warnings(psd)]
    record.warnings = list(dict.fromkeys(merged_warnings))
    comparisons = psd.get("comparisons")
    if isinstance(comparisons, dict):
        record.metrics["comparisons"] = comparisons
    if psd.get("scene") and record.scene == "unknown":
        record.scene = str(psd["scene"])
        record.features["scene"] = record.scene
    decision = diagnose(record.features, rule)
    record.cause = decision["cause"]
    record.conclusion = decision["conclusion"]
    record.confidence = decision["confidence"]
    record.notes = [decision["evidence"]]


def _escalate(
    request: AnalyzeRequest,
    records: List[AnalysisRecord],
    root: Path,
    chip: Optional[str],
    rule,
    output: Path,
    context: ExecutionContext,
) -> List[Path]:
    candidates = [record for record in records if record.focused or record.conclusion == "证据不足"]
    if not candidates:
        return []
    if request.analysis_type != "hr" or not rule.offline.get("enabled"):
        return []
    if not request.allow_offline:
        for record in candidates:
            record.notes.append("已通过 --no-offline 禁用离线 PSD 分析")
        return []
    if not chip:
        for record in candidates:
            record.notes.append("无法识别芯片，未执行离线 PSD 分析")
        return []
    paths = [Path(record.source) for record in candidates]
    offline_input = output / "offline_input"
    _copy_files(paths, root, offline_input)
    from health_tools.api.offline_operation import run_offline

    try:
        result = run_offline(
            OfflineRequest(
                input_path=offline_input,
                output_path=output / "offline",
                chip_name=chip,
                ver=request.offline_version,
                accuracy_thresholds=request.accuracy_thresholds,
                accuracy_inclusive=request.accuracy_inclusive,
            ),
            context=context,
        )
    except GHealthError as exc:
        for record in candidates:
            record.notes.append(f"离线 PSD 分析未完成: {exc}")
        return paths
    if _custom_accuracy(request):
        psd_results = analyze_psd_directory(
            result.output_dir or output / "offline",
            rule,
            request.accuracy_thresholds,
            request.accuracy_inclusive,
        )
    else:
        psd_results = analyze_psd_directory(result.output_dir or output / "offline", rule)
    for record in candidates:
        matches = [
            value for key, value in psd_results.items() if Path(key).stem == Path(record.file).stem
        ]
        if matches:
            _merge_psd(record, matches[0], rule)
        else:
            record.notes.append("离线结果中未找到对应 PSD")
    return paths


def _generate_psd_plots(
    source: Path,
    records: List[AnalysisRecord],
    output: Path,
    context: ExecutionContext,
    accuracy_thresholds: Optional[Sequence[float]] = None,
    accuracy_inclusive: bool = False,
) -> None:
    if not source.exists() or not any(source.rglob("*_result.vshb")):
        return
    from health_tools.api.file_operations import run_plot

    acc_mode = "rms" if any(source.rglob("*.accrmspsd")) else "axis"
    try:
        result = run_plot(
            PlotRequest(
                input_path=source,
                output_path=output,
                plot_type="psd",
                psd_acc=acc_mode,
                no_show=True,
                accuracy_thresholds=(
                    tuple(accuracy_thresholds) if accuracy_thresholds is not None else None
                ),
                accuracy_inclusive=accuracy_inclusive,
            ),
            context=context,
        )
    except GHealthError as exc:
        for record in records:
            if record.psd:
                record.notes.append(f"plot psd 未完成: {exc}")
        return
    for item in result.items:
        image = Path(item.output)
        matches = [record for record in records if Path(record.file).stem == image.stem]
        if matches and image.exists():
            matches[0].figure = str(image)


def _generate_raw_plots(
    request: AnalyzeRequest,
    records: List[AnalysisRecord],
    chip: Optional[str],
    output: Path,
    rule,
    context: ExecutionContext,
) -> None:
    from health_tools.api.file_operations import run_plot

    ac_causes = {"motion_artifact", "low_perfusion"}
    ppg_causes = {
        "signal_saturated",
        "signal_flat",
        "baseline_drift",
        "data_range_invalid",
        "signal_conversion_invalid",
    }
    for index, record in enumerate(records):
        if record.figure or record.psd or not Path(record.source).is_file():
            continue
        if record.conclusion == "未发现异常" and not record.focused and not record.warnings:
            continue
        if record.conclusion == "证据不足" and request.analysis_type == "hr":
            continue
        cause_id = str((record.cause or {}).get("id", ""))
        if cause_id == "data_incomplete":
            continue
        ppg = list(record.features.get("ppg_columns") or [])
        acc = list(record.features.get("acc_columns") or [])
        ref = (
            request.ref_column
            or rule.columns.get("reference")
            or ("REF_RESULT5" if request.analysis_type == "spo2" else "REF_RESULT0")
        )
        pred = (
            request.pred_column
            or rule.columns.get("prediction")
            or ("ALGO_RESULT5" if request.analysis_type == "spo2" else "ALGO_RESULT0")
        )
        plot_type = "time"
        channels: List[str] = []
        if request.analysis_type == "spo2" or cause_id in ac_causes:
            if chip and ppg:
                plot_type = "ac"
                channels = ppg[:4]
            else:
                channels = [*ppg[:1], *acc]
        elif cause_id in ppg_causes:
            channels = ppg[:1]
        elif cause_id == "acc_invalid":
            channels = acc
        elif cause_id == "channel_inconsistent":
            channels = ppg[:2]
        else:
            channels = [ref, pred]
        if not channels:
            record.notes.append("没有可供 plot 绘制的列")
            continue
        try:
            result = run_plot(
                PlotRequest(
                    input_path=Path(record.source),
                    output_path=output / f"{index:04d}",
                    chip_name=chip,
                    plot_type=plot_type,
                    channels=",".join(channels),
                    sample_rate=int(record.features.get("sample_rate") or 25),
                    no_show=True,
                ),
                context=context,
            )
        except GHealthError as exc:
            record.notes.append(f"plot {plot_type} 未完成: {exc}")
            continue
        artifacts = [Path(path) for path in result.artifacts if Path(path).exists()]
        if artifacts:
            record.figure = str(artifacts[0])
        elif result.items:
            record.notes.append(f"plot {plot_type} 未生成图片: {result.items[0].detail}")


def _offline_records(
    request: AnalyzeRequest, source: Path, rule
) -> Tuple[List[AnalysisRecord], Set[str]]:
    if "hr_psd" not in rule.detectors:
        raise RequestValidationError("当前 analysis 规则未启用 hr_psd，不能应用心率 PSD 检测")
    if _custom_accuracy(request):
        psd_results = analyze_psd_directory(
            source,
            rule,
            request.accuracy_thresholds,
            request.accuracy_inclusive,
        )
    else:
        psd_results = analyze_psd_directory(source, rule)
    if not psd_results:
        raise RequestValidationError(f"结果目录未找到 _result.vshb: {source}")
    focused = _focus(list(psd_results), request.focus)
    records: List[AnalysisRecord] = []
    for name, psd in psd_results.items():
        features = dict(psd)
        features.setdefault("data_complete", bool(psd.get("available")))
        features.setdefault("signal_saturated", False)
        features.setdefault("signal_flat", False)
        features.setdefault("scene", psd.get("scene", "unknown"))
        decision = diagnose(features, rule)
        metric_names = [
            "samples",
            "mae",
            "max_error",
            "error_ratio",
            *(key for key in psd if key.startswith("within_")),
        ]
        records.append(
            AnalysisRecord(
                file=name,
                source=str(psd.get("vshb_path", source)),
                analysis_type=request.analysis_type,
                scene=str(features.get("scene", "unknown")),
                focused=name in focused,
                features=features,
                metrics={key: psd.get(key) for key in metric_names},
                psd=psd,
                cause=decision["cause"],
                conclusion=decision["conclusion"],
                confidence=decision["confidence"],
                notes=[decision["evidence"]],
                warnings=_polar_warnings(features),
            )
        )
        comparisons = psd.get("comparisons")
        if isinstance(comparisons, dict):
            records[-1].metrics["comparisons"] = comparisons
    return records, focused


def run_analyze(
    request: AnalyzeRequest, *, context: Optional[ExecutionContext] = None
) -> AnalyzeResult:
    """分析原始 CSV 或已有离线 PSD 结果，并生成结构化及人类可读报告。"""
    _validate(request)
    request = _normalize_accuracy_request(request)
    ctx = _context(context)
    source = _require_path(request.input_path)
    output = Path(request.output_path)
    core_outputs = [
        output / "analysis_summary.json",
        output / "analysis_report.md",
        output / "analysis_report.pptx",
    ]
    state_path = output / "analysis_state.json"
    if any(path.exists() for path in core_outputs) and not state_path.exists():
        raise RequestValidationError(f"输出目录已包含分析产物但没有状态清单: {output}")
    state: Optional[AnalysisWorkspace] = None
    request_key = {
        "input": str(source),
        "analysis_type": request.analysis_type,
        "rule": request.rule_file,
        "check_report": str(request.check_report_path or ""),
        "offline_result": str(request.offline_result_path or ""),
    }
    if request.restart and state_path.exists():
        state_path.unlink()
    if request.resume and state_path.exists():
        state = AnalysisWorkspace.load(output)
        if state.state.request_fingerprint != request_fingerprint(request_key):
            state = None
    if state is None:
        state = AnalysisWorkspace.create(output, request_key)
    rule_name = request.rule_file or f"analysis_{request.analysis_type}.yaml"
    rule = _load_rule(RuleLoader.load_analysis_rule, rule_name, "分析")
    if request.analysis_type != "other" and rule.type != request.analysis_type:
        raise RequestValidationError("分析规则 type 与 --type 不一致")
    output.mkdir(parents=True, exist_ok=True)
    stages = output / "stages"
    figures = output / "figures"
    escalated: List[Path] = []
    if request.offline_result_path is not None:
        offline_source = _require_path(request.offline_result_path)
        records, _ = _offline_records(request, offline_source, rule)
        state.complete("offline", [offline_source])
    elif source.is_dir() and any(source.rglob("*_result.vshb")):
        records, _ = _offline_records(request, source, rule)
        state.complete("offline", [source])
        if _custom_accuracy(request):
            _generate_psd_plots(
                source,
                records,
                figures / "psd",
                ctx,
                request.accuracy_thresholds,
                request.accuracy_inclusive,
            )
        else:
            _generate_psd_plots(source, records, figures / "psd", ctx)
    else:
        root, raw_files = _raw_files(source)
        chip = request.chip_name or detect_chip(raw_files[0])
        check_path: Optional[Path] = request.check_report_path
        if check_path is None and chip:
            try:
                check_path = run_check_stage(request, source, chip, stages, ctx)
                if check_path:
                    state.complete("check", [check_path])
            except GHealthError as exc:
                check_path = None
                stage_notes = [f"数据检查未完成: {exc}"]
            else:
                stage_notes = []
        else:
            stage_notes = []
            if check_path is not None and Path(check_path).exists():
                state.complete("check", [Path(check_path)])
        records, root, raw_files, _, chip = run_raw_stage(request, source, rule, ctx)
        supporting_notes, _unused_check_path, evaluate_path = _run_supporting_stages(
            request, source, raw_files, root, chip, stages, rule, ctx
        )
        stage_notes.extend(supporting_notes)
        if stage_notes:
            for record in records:
                record.notes.extend(stage_notes)
        _apply_check_results(records, check_path, rule)
        _apply_evaluate_results(records, evaluate_path, rule)
        existing_offline = request.offline_result_path
        if existing_offline is not None:
            offline_records, _ = _offline_records(request, _require_path(existing_offline), rule)
            by_name = {Path(item.file).stem: item for item in offline_records}
            for record in records:
                match = by_name.get(Path(record.file).stem)
                if match:
                    _merge_psd(record, match.psd, rule)
            escalated = []
        elif state.state.stages["offline"].status == "completed" and (stages / "offline").exists():
            offline_records, _ = _offline_records(request, stages / "offline", rule)
            by_name = {Path(item.file).stem: item for item in offline_records}
            for record in records:
                match = by_name.get(Path(record.file).stem)
                if match:
                    _merge_psd(record, match.psd, rule)
            escalated = []
        else:
            escalated = _escalate(request, records, root, chip, rule, stages, ctx)
            if (stages / "offline").exists():
                state.complete("offline", [stages / "offline"])
        if _custom_accuracy(request):
            _generate_psd_plots(
                stages / "offline",
                records,
                figures / "psd",
                ctx,
                request.accuracy_thresholds,
                request.accuracy_inclusive,
            )
        else:
            _generate_psd_plots(stages / "offline", records, figures / "psd", ctx)
        _generate_raw_plots(request, records, chip, figures / "raw", rule, ctx)
        if request.figure_paths:
            artifact_index = ArtifactIndex.build(
                raw_files, request.figure_paths, request.check_report_path
            )
            for record in records:
                item = artifact_index.item_for(record.file)
                if item and item.primary_figure:
                    record.figure = str(item.primary_figure)
                    if item.secondary_figures:
                        record.notes.append(
                            "已复用现有副图: "
                            + ", ".join(path.name for path in item.secondary_figures)
                        )
    for index, record in enumerate(records):
        if (
            not record.figure
            and not record.psd
            and (record.cause or {}).get("id") == "data_incomplete"
        ):
            write_evidence_figure(record, figures / f"{index:04d}_{_safe_name(record.file)}.png")
    if _custom_accuracy(request):
        detail_paths = write_structured(records, output, request.accuracy_thresholds)
    else:
        detail_paths = write_structured(records, output)
    reports: List[Path] = []
    if request.report in {"markdown", "all"}:
        if _custom_accuracy(request):
            reports.append(
                write_markdown(
                    records,
                    output / "analysis_report.md",
                    request.accuracy_thresholds,
                    request.accuracy_inclusive,
                )
            )
        else:
            reports.append(write_markdown(records, output / "analysis_report.md"))
    if request.report in {"pptx", "all"}:
        if _custom_accuracy(request):
            reports.append(
                write_ppt(
                    records,
                    output / "analysis_report.pptx",
                    request.accuracy_thresholds,
                    request.accuracy_inclusive,
                )
            )
        else:
            reports.append(write_ppt(records, output / "analysis_report.pptx"))
    state.complete("report", [*detail_paths, *reports])
    items = tuple(
        ItemResult(
            ItemStatus.OK if record.conclusion == "未发现异常" else ItemStatus.WARN,
            record.source,
            record.figure or "",
            reason=record.conclusion,
            detail=record.notes[0] if record.notes else "",
            category=record.scene,
        )
        for record in records
    )
    artifacts = tuple(
        [*detail_paths, *reports, *(Path(record.figure) for record in records if record.figure)]
    )
    batch = BatchResult("analyze", items, artifacts)
    counts = Counter(record.conclusion for record in records)
    return AnalyzeResult(
        batch=batch,
        output_dir=output,
        reports=tuple(reports),
        summary_path=detail_paths[0],
        detail_paths=tuple(detail_paths[1:]),
        escalated_files=tuple(escalated),
        conclusion_counts=dict(counts),
    )
