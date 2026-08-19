"""数据分析公共 API 编排。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np  # noqa: F401
    import pandas as pd  # noqa: F401

import fnmatch
import json
import re
import shutil
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple, cast

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
from health_tools.core.analysis.raw import analyze_raw_file, detect_chip, infer_activity
from health_tools.core.analysis.reporting import (
    write_evidence_figure,
    write_markdown,
    write_ppt,
    write_structured,
)
from health_tools.core.analysis.workspace import AnalysisWorkspace, request_fingerprint
from health_tools.rules.loader import RuleLoader

ANALYSIS_AUXILIARY_CSVS = {
    "check_report.csv",
    "check_report_compact.csv",
    "analysis_summary.csv",
    "analysis_diagnosis.csv",
}


def _validate(request: AnalyzeRequest) -> None:
    if request.analysis_type not in {"hr", "spo2", "other"}:
        raise RequestValidationError("analysis_type 仅支持 hr、spo2 或 other")
    if request.analysis_type == "other" and not request.rule_file:
        raise RequestValidationError("other 分析必须提供 --rule")
    if request.scene not in {"auto", "static", "dynamic"}:
        raise RequestValidationError("scene 仅支持 auto、static 或 dynamic")
    if request.activity not in {
        "auto",
        "rest",
        "walk",
        "run",
        "cycle",
        "strength",
        "interval",
        "recovery",
        "other",
    }:
        raise RequestValidationError("activity 场景不受支持")
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


def _raw_files(source: Path, excluded_root: Optional[Path] = None) -> Tuple[Path, List[Path]]:
    root = source.parent if source.is_file() else source
    if source.is_file():
        files = [source]
    else:
        excluded = excluded_root.resolve() if excluded_root is not None else None
        files = [
            path
            for path in sorted(source.rglob("*.csv"))
            if path.name.lower() not in ANALYSIS_AUXILIARY_CSVS
            and (excluded is None or not _inside(path, excluded))
        ]
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


def _request_key(request: AnalyzeRequest, source: Path) -> Dict[str, object]:
    return {
        "input": str(source),
        "analysis_type": request.analysis_type,
        "rule": request.rule_file or "",
        "chip": request.chip_name or "",
        "scene": request.scene,
        "sample_rate": request.sample_rate,
        "ref_column": request.ref_column or "",
        "pred_column": request.pred_column or "",
        "timestamp_column": request.timestamp_column or "",
        "focus": tuple(request.focus),
        "report": request.report,
        "offline_version": request.offline_version or "",
        "allow_offline": request.allow_offline,
        "workers": request.workers,
        "accuracy_thresholds": tuple(request.accuracy_thresholds or ()),
        "accuracy_inclusive": request.accuracy_inclusive,
        "check_report": str(request.check_report_path or ""),
        "offline_result": str(request.offline_result_path or ""),
        "figure_paths": tuple(str(path) for path in request.figure_paths),
        "activity": request.activity,
    }


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _remove_owned_analysis_outputs(output: Path) -> None:
    targets = [
        output / "analysis_state.json",
        output / "analysis_summary.json",
        output / "file_diagnosis.csv",
        output / "segment_diagnosis.csv",
        output / "analysis_report.md",
        output / "analysis_report.pptx",
        output / "stages",
        output / "figures",
        output / "evaluate_input",
    ]
    for target in targets:
        if not target.exists() or not _inside(target, output):
            continue
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()


def _prepare_workspace(
    request: AnalyzeRequest,
    output: Path,
    request_key: Mapping[str, object],
    core_outputs: Sequence[Path],
) -> AnalysisWorkspace:
    state_path = output / "analysis_state.json"
    has_core_output = any(path.exists() for path in core_outputs)
    if request.restart:
        _remove_owned_analysis_outputs(output)
        return AnalysisWorkspace.create(output, request_key)
    if state_path.exists():
        if not request.resume:
            raise RequestValidationError("输出目录已有分析状态；如需重新开始请使用 --restart")
        state = AnalysisWorkspace.load(output)
        if state.state.request_fingerprint != request_fingerprint(request_key):
            raise RequestValidationError("输出目录已有其他分析请求的状态；如需覆盖请使用 --restart")
        return state
    if has_core_output:
        raise RequestValidationError(f"输出目录已包含分析产物但没有状态清单: {output}")
    return AnalysisWorkspace.create(output, request_key)


def _stage_fingerprint(stage: str, request_key: Mapping[str, object]) -> str:
    return request_fingerprint({"stage": stage, "request": request_key})


def _stage_artifact_paths(state: AnalysisWorkspace, stage: str) -> List[Path]:
    return [Path(artifact.path) for artifact in state.state.stages[stage].artifacts]


def _records_from_payload(values: Sequence[Mapping[str, Any]]) -> List[AnalysisRecord]:
    records: List[AnalysisRecord] = []
    for value in values:
        segments = [AnalysisSegment(**segment) for segment in value.get("segments", [])]
        records.append(
            AnalysisRecord(
                file=str(value.get("file", "")),
                source=str(value.get("source", "")),
                analysis_type=str(value.get("analysis_type", "hr")),
                scene=str(value.get("scene", "unknown")),
                activity=str(value.get("activity", "other")),
                focused=bool(value.get("focused", False)),
                features=dict(value.get("features", {})),
                metrics=dict(value.get("metrics", {})),
                segments=segments,
                psd=dict(value.get("psd", {})),
                cause=dict(value["cause"]) if isinstance(value.get("cause"), Mapping) else None,
                conclusion=str(value.get("conclusion", "证据不足")),
                confidence=float(value.get("confidence", 0.0) or 0.0),
                notes=[str(item) for item in value.get("notes", [])],
                warnings=[str(item) for item in value.get("warnings", [])],
                figure=str(value["figure"]) if value.get("figure") else None,
                secondary_figure=(
                    str(value["secondary_figure"]) if value.get("secondary_figure") else None
                ),
            )
        )
    return records


def _load_diagnosis_records(path: Path) -> List[AnalysisRecord]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise RequestValidationError(f"诊断快照格式无效: {path}")
    return _records_from_payload(payload)


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


def _normalized_artifact_key(value: object) -> str:
    text = "" if value is None else str(value).strip()
    return "" if text.lower() == "nan" else text.replace("\\", "/")


def _record_file_counts(records: Sequence[AnalysisRecord]) -> Tuple[Counter[str], Counter[str]]:
    names = Counter(Path(record.file).name for record in records)
    stems = Counter(Path(record.file).stem for record in records)
    return names, stems


def _rows_for_record(
    report: pd.DataFrame,
    records: Sequence[AnalysisRecord],
    record: AnalysisRecord,
    exact_columns: Sequence[str],
    fallback_columns: Sequence[str],
) -> pd.DataFrame:
    relative = _normalized_artifact_key(record.file)
    for column in exact_columns:
        if column not in report.columns:
            continue
        values: pd.Series = report[column].map(_normalized_artifact_key)
        rows = cast("pd.DataFrame", report.loc[values == relative])
        if not rows.empty:
            return rows
    names, stems = _record_file_counts(records)
    if names[Path(record.file).name] == 1:
        for column in fallback_columns:
            if column not in report.columns:
                continue
            values = report[column].map(_normalized_artifact_key)
            rows = cast(
                "pd.DataFrame",
                report.loc[values.map(lambda value: Path(value).name) == Path(record.file).name],
            )
            if not rows.empty:
                return rows
    if stems[Path(record.file).stem] == 1:
        for column in fallback_columns:
            if column not in report.columns:
                continue
            values = report[column].map(_normalized_artifact_key)
            rows = cast(
                "pd.DataFrame",
                report.loc[values.map(lambda value: Path(value).stem) == Path(record.file).stem],
            )
            if not rows.empty:
                return rows
    return cast("pd.DataFrame", report.iloc[0:0])


def _record_for_file(file_name: str, records: Sequence[AnalysisRecord]) -> Optional[AnalysisRecord]:
    normalized = _normalized_artifact_key(file_name)
    exact = [record for record in records if _normalized_artifact_key(record.file) == normalized]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return None
    name_matches = [record for record in records if Path(record.file).name == Path(normalized).name]
    if len(name_matches) == 1:
        return name_matches[0]
    if len(name_matches) > 1:
        return None
    stem_matches = [record for record in records if Path(record.file).stem == Path(normalized).stem]
    return stem_matches[0] if len(stem_matches) == 1 else None


def _offline_record_for(
    record: AnalysisRecord, offline_records: Sequence[AnalysisRecord]
) -> Optional[AnalysisRecord]:
    normalized = _normalized_artifact_key(record.file)
    exact = [item for item in offline_records if _normalized_artifact_key(item.file) == normalized]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return None
    name_matches = [
        item for item in offline_records if Path(item.file).name == Path(record.file).name
    ]
    if len(name_matches) == 1:
        return name_matches[0]
    if len(name_matches) > 1:
        return None
    stem_matches = [
        item for item in offline_records if Path(item.file).stem == Path(record.file).stem
    ]
    return stem_matches[0] if len(stem_matches) == 1 else None


def _apply_check_results(records: List[AnalysisRecord], report_path: Optional[Path], rule) -> None:
    import pandas as pd

    if report_path is None or not report_path.exists():
        return
    report = pd.read_csv(report_path, encoding="utf-8-sig")
    for record in records:
        if record.features.get("input_status") == "SKIP":
            continue
        row = _rows_for_record(report, records, record, ("文件相对路径",), ("文件名",))
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


def _apply_compact_check_results(
    records: List[AnalysisRecord], report_path: Optional[Path], rule
) -> None:
    """将精简 check 长表按文件聚合为诊断事实，不解析说明文本。"""
    import pandas as pd

    if report_path is None or not report_path.exists():
        return
    report = pd.read_csv(report_path, encoding="utf-8-sig")
    if "检查项" not in report.columns:
        return
    for record in records:
        if record.features.get("input_status") == "SKIP":
            continue
        rows = _rows_for_record(report, records, record, ("文件相对路径",), ("文件名",))
        if rows.empty:
            continue
        channel_metrics: Dict[str, Dict[str, float]] = {}
        mapping = {
            "异常占比": "abnormal_ratio",
            "总数": "total_count",
            "近0占比": "near_zero_ratio",
            "近满量程占比": "near_full_ratio",
            "AGC变化次数": "agc_change_count",
            "AGC有效对数": "agc_pair_count",
            "AGC变化占比": "agc_change_ratio_percent",
        }
        for _, row in rows.iterrows():
            channel = str(row.get("通道", "-") or "-")
            metrics = channel_metrics.setdefault(channel, {})
            for column, key in mapping.items():
                raw_value = row.get(column)
                if raw_value is None:
                    continue
                try:
                    value = float(raw_value)
                except (TypeError, ValueError):
                    continue
                if pd.notna(value):
                    metrics[key] = max(value, metrics.get(key, 0.0))
        record.features["check_channel_metrics"] = channel_metrics
        for key in ("near_zero_ratio", "near_full_ratio", "agc_change_count"):
            values = [metric[key] for metric in channel_metrics.values() if key in metric]
            if values:
                record.features[key] = max(values)
        record.features["near_zero"] = record.features.get("near_zero_ratio", 0.0) >= 5.0
        record.features["near_full"] = record.features.get("near_full_ratio", 0.0) >= 5.0
        ratios = []
        for metric in channel_metrics.values():
            if "agc_change_ratio_percent" in metric:
                ratios.append(metric["agc_change_ratio_percent"] / 100.0)
            elif metric.get("agc_pair_count", 0.0) > 0:
                ratios.append(metric.get("agc_change_count", 0.0) / metric["agc_pair_count"])
        record.features["agc_change_ratio"] = max(ratios, default=0.0)
        record.features["agc_unstable"] = record.features["agc_change_ratio"] >= 0.05
        record.features["channel_dropout"] = any(
            metric.get("near_zero_ratio", 0.0) >= 5.0 for metric in channel_metrics.values()
        )
        _refresh_diagnosis(record, rule)


def _apply_evaluate_results(
    records: List[AnalysisRecord], detail_path: Optional[Path], rule
) -> None:
    import pandas as pd

    if detail_path is None or not detail_path.exists():
        return
    details = pd.read_csv(detail_path)
    for record in records:
        row = _rows_for_record(details, records, record, ("file",), ("file",))
        if row.empty:
            continue
        values = row.iloc[0]
        for key in ("mae", "rmse", "std", "correlation", "samples"):
            value = values.get(key)
            if value is not None and pd.notna(value):
                numeric = float(value)
                record.metrics[f"evaluate_{key}"] = numeric
                record.features[f"evaluate_{key}"] = numeric
        _refresh_diagnosis(record, rule)


def _raw_records(
    request: AnalyzeRequest,
    source: Path,
    rule,
    context: ExecutionContext,
    root: Optional[Path] = None,
    files: Optional[Sequence[Path]] = None,
) -> Tuple[List[AnalysisRecord], Path, List[Path], Set[str], Optional[str]]:
    if root is None or files is None:
        root, discovered_files = _raw_files(source)
    else:
        discovered_files = list(files)
    if not discovered_files:
        raise RequestValidationError(f"输入目录没有 CSV: {source}")
    report_items = []
    if request.check_report_path is not None and Path(request.check_report_path).is_file():
        report_index = ArtifactIndex.build(discovered_files, check_report=request.check_report_path)
        report_items = list(report_index.items.values())
    names = [item.relative_path for item in report_items] or [
        _logical(path, root) for path in discovered_files
    ]
    focused = _focus(names, request.focus)
    existing_files = [
        item.csv_path for item in report_items if item.csv_path.exists()
    ] or discovered_files
    chip = request.chip_name or detect_chip(existing_files[0])
    records: List[AnalysisRecord] = []
    total = len(report_items) if report_items else len(discovered_files)
    context.emit(ProgressEvent("analyze", "raw", 0, total, "分析原始数据"))
    raw_items = (
        [(item.relative_path, item.csv_path, item.status, item.reason) for item in report_items]
        if report_items
        else [(_logical(path, root), path, "OK", "") for path in discovered_files]
    )
    analyzed_files: List[Path] = []
    for index, (name, path, status, reason) in enumerate(raw_items, 1):
        context.check_cancelled("raw", records)
        try:
            if status != "OK" or not path.exists():
                raise FileNotFoundError(reason or "文件不存在")
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
                    activity_override=request.activity,
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
                    activity_override=request.activity,
                )
            features = result["features"]
            features.update(result["metrics"])
            decision = diagnose(features, rule)
            record = AnalysisRecord(
                file=name,
                source=str(path),
                analysis_type=request.analysis_type,
                scene=str(features.get("scene", "unknown")),
                activity=str(features.get("activity", "other")),
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
            analyzed_files.append(path)
        except Exception as exc:
            skip_reason = reason if status == "SKIP" else ""
            record = AnalysisRecord(
                file=name,
                source=str(path),
                analysis_type=request.analysis_type,
                focused=name in focused,
                conclusion="证据不足",
                features=(
                    {"input_status": "SKIP", "skip_reason": skip_reason} if status == "SKIP" else {}
                ),
                notes=[skip_reason or f"读取或分析失败: {exc}"],
            )
        records.append(record)
        context.emit(ProgressEvent("analyze", "raw", index, total, "完成", name))
    return records, root, analyzed_files or existing_files, focused, chip


def run_raw_stage(
    request: AnalyzeRequest,
    source: Path,
    rule,
    context: ExecutionContext,
    root: Optional[Path] = None,
    files: Optional[Sequence[Path]] = None,
):
    """可替换的原始数据阶段入口，便于断点编排和测试。"""
    return _raw_records(request, source, rule, context, root, files)


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
    candidates = [
        record
        for record in records
        if record.features.get("input_status") != "SKIP"
        and (record.focused or record.conclusion == "证据不足")
    ]
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
        match = _psd_for_record(record, psd_results)
        if match:
            _merge_psd(record, match, rule)
        else:
            record.notes.append("离线结果中未找到对应 PSD")
    return paths


def _psd_for_record(
    record: AnalysisRecord, psd_results: Dict[str, Dict[str, object]]
) -> Optional[Dict[str, object]]:
    normalized = _normalized_artifact_key(record.file)
    exact = [
        value for key, value in psd_results.items() if _normalized_artifact_key(key) == normalized
    ]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return None
    by_name = [
        value for key, value in psd_results.items() if Path(key).name == Path(record.file).name
    ]
    if len(by_name) == 1:
        return by_name[0]
    if len(by_name) > 1:
        return None
    by_stem = [
        value for key, value in psd_results.items() if Path(key).stem == Path(record.file).stem
    ]
    return by_stem[0] if len(by_stem) == 1 else None


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
        match = _record_for_file(image.stem, records)
        if match and image.exists():
            match.figure = str(image)


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
        activity = infer_activity(Path(name), request.activity, features)
        features.setdefault("activity", activity)
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
                activity=activity,
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
    request_key = _request_key(request, source)
    state = _prepare_workspace(request, output, request_key, core_outputs)
    rule_name = request.rule_file or f"analysis_{request.analysis_type}.yaml"
    rule = _load_rule(RuleLoader.load_analysis_rule, rule_name, "分析")
    if request.analysis_type != "other" and rule.type != request.analysis_type:
        raise RequestValidationError("分析规则 type 与 --type 不一致")
    output.mkdir(parents=True, exist_ok=True)
    stages = output / "stages"
    figures = output / "figures"
    source_offline_result = request.offline_result_path is not None
    source_psd_result = source.is_dir() and any(source.rglob("*_result.vshb"))
    current_input_artifacts: List[Path] = []
    current_raw_root: Optional[Path] = None
    current_raw_files: List[Path] = []
    if not source_offline_result and not source_psd_result:
        current_raw_root, current_raw_files = _raw_files(source, output)
        current_input_artifacts = list(current_raw_files)
    elif source_offline_result:
        offline_result_path = request.offline_result_path
        assert offline_result_path is not None
        offline_source = _require_path(offline_result_path)
        current_input_artifacts = [offline_source]
    else:
        current_input_artifacts = list(source.rglob("*_result.vshb"))
    upstream_stages = ("discover", "check", "raw", "evaluate", "offline", "plot")
    for stage in upstream_stages:
        stage_state = state.state.stages[stage]
        if stage_state.status != "completed":
            continue
        if stage in {"discover", "raw"}:
            current_artifacts = current_input_artifacts
        else:
            current_artifacts = None
        if not state.can_reuse(
            stage,
            request_key,
            fingerprint=_stage_fingerprint(stage, request_key),
            artifacts=current_artifacts,
        ):
            state.invalidate_from(stage)
            break
    escalated: List[Path] = []
    diagnose_fingerprint = _stage_fingerprint("diagnose", request_key)
    diagnose_artifacts = _stage_artifact_paths(state, "diagnose")
    diagnosis_reused = False
    diagnose_reusable = bool(diagnose_artifacts) and state.can_reuse(
        "diagnose", request_key, fingerprint=diagnose_fingerprint
    )
    if diagnose_artifacts and not diagnose_reusable:
        state.invalidate_from("diagnose")
        diagnose_artifacts = []
    if diagnose_reusable:
        detail_paths = diagnose_artifacts
        records = _load_diagnosis_records(detail_paths[0])
        diagnosis_reused = True
    elif request.offline_result_path is not None:
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
        if current_raw_root is not None:
            root, raw_files = current_raw_root, current_raw_files
        else:
            root, raw_files = _raw_files(source, output)
        if not raw_files:
            raise RequestValidationError(f"未找到可分析的原始 CSV: {source}")
        discover_fingerprint = _stage_fingerprint("discover", request_key)
        state.start("discover", discover_fingerprint)
        state.complete("discover", raw_files, fingerprint=discover_fingerprint)
        chip = request.chip_name or detect_chip(raw_files[0])
        check_path: Optional[Path] = request.check_report_path
        check_fingerprint = _stage_fingerprint("check", request_key)
        state.start("check", check_fingerprint)
        if check_path is None and chip:
            try:
                check_path = run_check_stage(request, source, chip, stages, ctx)
                if check_path:
                    state.complete("check", [check_path], fingerprint=check_fingerprint)
                else:
                    state.complete("check", fingerprint=check_fingerprint)
            except GHealthError as exc:
                state.fail("check", exc)
                check_path = None
                stage_notes = [f"数据检查未完成: {exc}"]
            else:
                stage_notes = []
        else:
            stage_notes = []
            if check_path is not None and Path(check_path).exists():
                state.complete("check", [Path(check_path)], fingerprint=check_fingerprint)
            else:
                state.complete("check", fingerprint=check_fingerprint)
        raw_fingerprint = _stage_fingerprint("raw", request_key)
        state.start("raw", raw_fingerprint)
        try:
            records, root, raw_files, _, chip = run_raw_stage(
                request, source, rule, ctx, root, raw_files
            )
        except Exception as exc:
            state.fail("raw", exc)
            raise
        state.complete("raw", raw_files, fingerprint=raw_fingerprint)
        evaluate_fingerprint = _stage_fingerprint("evaluate", request_key)
        state.start("evaluate", evaluate_fingerprint)
        try:
            supporting_notes, _unused_check_path, evaluate_path = _run_supporting_stages(
                request, source, raw_files, root, chip, stages, rule, ctx
            )
        except Exception as exc:
            state.fail("evaluate", exc)
            raise
        state.complete(
            "evaluate",
            [evaluate_path] if evaluate_path is not None else [],
            fingerprint=evaluate_fingerprint,
        )
        stage_notes.extend(supporting_notes)
        if stage_notes:
            for record in records:
                record.notes.extend(stage_notes)
        if check_path and Path(check_path).name == "check_report_compact.csv":
            _apply_compact_check_results(records, check_path, rule)
        else:
            _apply_check_results(records, check_path, rule)
            compact_path = (
                Path(check_path).with_name("check_report_compact.csv") if check_path else None
            )
            _apply_compact_check_results(records, compact_path, rule)
        _apply_evaluate_results(records, evaluate_path, rule)
        existing_offline = request.offline_result_path
        offline_fingerprint = _stage_fingerprint("offline", request_key)
        reuse_offline_stage = (
            state.can_reuse("offline", request_key, fingerprint=offline_fingerprint)
            and (stages / "offline").exists()
        )
        if existing_offline is not None:
            state.start("offline", offline_fingerprint)
            offline_records, _ = _offline_records(request, _require_path(existing_offline), rule)
            for record in records:
                match = _offline_record_for(record, offline_records)
                if match:
                    _merge_psd(record, match.psd, rule)
            escalated = []
            state.complete("offline", [Path(existing_offline)], fingerprint=offline_fingerprint)
        elif reuse_offline_stage:
            offline_records, _ = _offline_records(request, stages / "offline", rule)
            for record in records:
                match = _offline_record_for(record, offline_records)
                if match:
                    _merge_psd(record, match.psd, rule)
            escalated = []
        else:
            state.start("offline", offline_fingerprint)
            try:
                escalated = _escalate(request, records, root, chip, rule, stages, ctx)
            except Exception as exc:
                state.fail("offline", exc)
                raise
            offline_artifacts = [stages / "offline"] if (stages / "offline").exists() else []
            state.complete("offline", offline_artifacts, fingerprint=offline_fingerprint)
        plot_fingerprint = _stage_fingerprint("plot", request_key)
        state.start("plot", plot_fingerprint)
        try:
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
                            record.secondary_figure = str(item.secondary_figures[0])
                            record.notes.append(
                                "已复用现有副图: "
                                + ", ".join(path.name for path in item.secondary_figures)
                            )
        except Exception as exc:
            state.fail("plot", exc)
            raise
        plot_artifacts = [
            Path(path)
            for record in records
            for path in (record.figure, record.secondary_figure)
            if path
        ]
        state.complete("plot", plot_artifacts, fingerprint=plot_fingerprint)
    if not diagnosis_reused:
        for index, record in enumerate(records):
            if (
                not record.figure
                and not record.psd
                and (record.cause or {}).get("id") == "data_incomplete"
            ):
                write_evidence_figure(
                    record, figures / f"{index:04d}_{_safe_name(record.file)}.png"
                )
        state.start("diagnose", diagnose_fingerprint)
        try:
            if _custom_accuracy(request):
                detail_paths = write_structured(records, output, request.accuracy_thresholds)
            else:
                detail_paths = write_structured(records, output)
        except Exception as exc:
            state.fail("diagnose", exc)
            raise
        state.complete("diagnose", detail_paths, fingerprint=diagnose_fingerprint)
    reports: List[Path] = []
    report_fingerprint = _stage_fingerprint("report", request_key)
    report_artifacts = _stage_artifact_paths(state, "report")
    if report_artifacts and state.can_reuse("report", request_key, fingerprint=report_fingerprint):
        reports = report_artifacts
    else:
        if report_artifacts:
            state.invalidate_from("report")
        state.start("report", report_fingerprint)
        try:
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
        except Exception as exc:
            state.fail("report", exc)
            raise
        state.complete("report", reports, fingerprint=report_fingerprint)
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
