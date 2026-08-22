"""数据质量检查公共 API。"""

from __future__ import annotations

import csv
import math
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, cast

import numpy as np
import pandas as pd

from health_tools.api.context import ExecutionContext
from health_tools.api.errors import RequestValidationError
from health_tools.api.models import (
    BatchResult,
    CheckAccuracyResult,
    CheckRequest,
    CheckResult,
    ItemResult,
    ItemStatus,
    ProgressEvent,
)
from health_tools.api.operations import _batch, _context, _load_rule, _require_path
from health_tools.utils.accuracy import format_metric_name, resolve_accuracy_methods
from health_tools.utils.errors import (
    REASON_PROCESS_FAILED,
    classify_exception,
    format_exception_detail,
)

SORT_CATEGORIES = (
    "frame",
    "range",
    "acc_fail",
    "acc_warning",
    "timestamp",
    "center",
    "reference",
    "frame_warning",
    "accuracy",
    "agc",
    "ipd",
    "total_fail",
    "normal",
)

_MAX_FILE_WORKERS = 32

_FULL_REPORT_HEADER = {
    "文件名",
    "芯片",
    "总异常(结果)",
    "场景分类",
    "主要异常项",
    "文件相对路径",
}
_COMPACT_REPORT_HEADER = {
    "文件名",
    "场景分类",
    "文件相对路径",
    "芯片",
    "检查项",
    "状态",
    "通道",
}


def _is_check_report_csv(path: Path) -> bool:
    """按表头识别 check 完整报告和 compact 报告。"""
    try:
        with path.open("r", newline="", encoding="utf-8-sig") as handle:
            header = {column.strip() for column in next(csv.reader(handle))}
    except (OSError, UnicodeError, csv.Error, StopIteration):
        return False
    return _FULL_REPORT_HEADER.issubset(header) or _COMPACT_REPORT_HEADER.issubset(header)


def _discover_check_inputs(target: Path) -> List[Path]:
    """发现待检查 CSV；报告识别延后到文件读取失败时执行。"""
    if target.is_file():
        return [target]
    return sorted(target.rglob("*.csv"))


def _is_failed_check_report(item: ItemResult, path: Path) -> bool:
    """仅对失败/跳过文件识别 check 完整报告和 compact 报告。"""
    if item.status not in {ItemStatus.SKIP, ItemStatus.FAIL}:
        return False
    return _is_check_report_csv(path)


def _compact_report_path(report_path: Path) -> Path:
    """根据完整报告路径生成对应的精简报告路径。"""
    return report_path.with_name(f"{report_path.stem}_compact{report_path.suffix}")


TRAILING_CHECK_CATEGORIES = {
    "AGC调光": "agc",
    "AGC变化": "agc",
    "Ipd转换": "ipd",
}


# 主要异常与分拣共用的优先级事实来源；表项按优先级从高到低排列。
PRIMARY_RULES = (
    ("帧完整性(结果)", "FAIL", "frame", "帧不完整"),
    ("数据范围(结果)", "FAIL", "range", "数据范围异常"),
    ("ACC异常(结果)", "FAIL", "acc_fail", "ACC异常"),
    ("ACC异常(结果)", "WARNING", "acc_warning", "ACC警告"),
    ("时间戳间隔(结果)", "FAIL", "timestamp", "时间戳异常"),
    ("数据居中(结果)", "FAIL", "center", "数据未居中"),
    ("心率金标(结果)", "FAIL", "reference", "金标异常"),
    ("血氧金标(结果)", "FAIL", "reference", "金标异常"),
    ("帧完整性(结果)", "WARNING", "frame_warning", "首帧非0"),
    ("准确度标定分类", "__PRESENT__", "__accuracy__", ""),
    ("AGC变化(结果)", "FAIL", "agc", "AGC异常"),
    ("AGC调光(结果)", "FAIL", "agc", "AGC异常"),
    ("Ipd转换(结果)", "FAIL", "ipd", "Ipd转换异常"),
)


def _primary_match(row: Dict[str, str]) -> Tuple[str, str]:
    """返回报告行的统一优先级匹配结果（目录分类、中文摘要）。"""
    for column, expected, category, label in PRIMARY_RULES:
        if expected == "__PRESENT__":
            value = row.get(column, "").strip()
            if value:
                return _safe_category_name(value), row.get("准确度标定说明", "").strip() or value
            continue
        if row.get(column, "").strip().upper() == expected:
            return category, label
    return "", ""


def primary_issue(row: Dict[str, str]) -> str:
    """按统一优先级返回报告行的主要异常中文摘要。"""
    _, label = _primary_match(row)
    if label:
        return label
    failed = sorted(
        column[: -len("(结果)")]
        for column, value in row.items()
        if column.endswith("(结果)")
        and column != "总异常(结果)"
        and (value or "").strip().upper() == "FAIL"
        and column[: -len("(结果)")] not in TRAILING_CHECK_CATEGORIES
    )
    if failed:
        return failed[0]
    if row.get("总异常(结果)", "").strip().upper() == "FAIL":
        return "未分类异常"
    return "正常"


def _safe_category_name(check_name: str) -> str:
    """将扩展检查项名称转换为单个安全目录名。"""
    name = check_name.replace("\\", "/").split("/")[-1]
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return name or "total_fail"


def _fallback_check_category(row: Dict[str, str]) -> str:
    """识别低优先级检查项，未知项保留检查名称作为独立目录。"""
    failed = {
        column[: -len("(结果)")]
        for column, value in row.items()
        if column.endswith("(结果)")
        and column != "总异常(结果)"
        and (value or "").strip().upper() == "FAIL"
    }
    for check_name in ("AGC调光", "AGC变化", "Ipd转换"):
        if check_name in failed:
            return TRAILING_CHECK_CATEGORIES[check_name]
    unknown = sorted(failed - set(TRAILING_CHECK_CATEGORIES))
    return _safe_category_name(unknown[0]) if unknown else ""
    return ""


def _sort_category(row: Dict[str, str]) -> str:
    """按异常优先级为单个报告行选择唯一分拣目录。"""
    status = row.get("总异常(结果)", "").strip().upper()
    category, _ = _primary_match(row)
    if category:
        return category
    if status == "FAIL":
        return _fallback_check_category(row) or "total_fail"
    return "normal"


def _detect_chip(csv_file: Path) -> Optional[str]:
    try:
        first_line = csv_file.open("r", encoding="utf-8", errors="ignore").readline().lower()
    except Exception:
        return None
    for chip in ("gh3036", "gh3220", "gh3300"):
        if chip in first_line:
            return chip
    return None


@dataclass
class _FileCheckContext:
    """单个文件检查的共享输入。

    列解析结果在文件生命周期内固定；数值列按需转换并缓存，避免不同检查项
    为同一列重复执行 ``to_numeric``。这些字段只供 check operation 内部使用。
    """

    path: Path
    chip: str
    chip_rule: Any
    frame: pd.DataFrame
    checker: Any
    data_columns: List[str]
    frame_column: str
    acc_columns: List[str]
    ipd_columns: List[str]
    agc_columns: List[str]
    _numeric_columns: Dict[Tuple[str, ...], pd.DataFrame] = field(default_factory=dict)
    _timestamp_analysis: Dict[str, Tuple[Optional[pd.Series], str]] = field(default_factory=dict)
    _sample_positions: Dict[Tuple[float, str], np.ndarray] = field(default_factory=dict)
    _sample_frames: Dict[
        Tuple[str, str, str, Optional[str], float, Tuple[int, ...]], pd.DataFrame
    ] = field(default_factory=dict)

    @classmethod
    def create(cls, path: Path, chip: str, chip_rule: Any, frame: pd.DataFrame, checker: Any):
        def resolve(method_name: str, default, *, needs_frame: bool = False):
            method = getattr(checker, method_name, None)
            if method is None:
                return default
            return method(frame) if needs_frame else method()

        data_columns = [
            column for column in resolve("_get_data_columns", []) if column in frame.columns
        ]
        frame_column = resolve("_resolve_frame_column", "", needs_frame=True)
        acc_columns = resolve("_resolve_acc_columns", [], needs_frame=True)
        ipd_columns = [
            column for column in resolve("_get_ipd_columns", []) if column in frame.columns
        ]
        agc_columns = [
            column for column in resolve("_get_agc_columns", []) if column in frame.columns
        ]
        context = cls(
            path=path,
            chip=chip,
            chip_rule=chip_rule,
            frame=frame,
            checker=checker,
            data_columns=data_columns,
            frame_column=frame_column,
            acc_columns=acc_columns,
            ipd_columns=ipd_columns,
            agc_columns=agc_columns,
        )
        # DataChecker's existing resolution methods remain source-compatible while
        # using this file-scoped result for every subsequent check.
        checker._check_context = context
        return context

    def numeric(self, columns: Tuple[str, ...]) -> pd.DataFrame:
        """Return a lazily converted numeric view for the requested columns."""
        key = tuple(columns)
        cached = self._numeric_columns.get(key)
        if cached is None:
            cached = self.frame.loc[:, list(key)].apply(pd.to_numeric, errors="coerce")
            self._numeric_columns[key] = cached
        return cached

    def timestamp_analysis(self, column: str) -> Tuple[Optional[pd.Series], str]:
        """解析并缓存时间戳间隔，供检查和采样率预测共同使用。"""
        cached = self._timestamp_analysis.get(column)
        if cached is None:
            parser = getattr(self.checker, "_parse_timestamp_intervals_ms", None)
            if parser is None:
                # Test doubles and compatible checker implementations may not
                # expose the private parser; defer parsing to their public check.
                cached = (None, "")
                self._timestamp_analysis[column] = cached
                return cached
            cached = parser(self.frame[column])
            self._timestamp_analysis[column] = cached
        return cached

    def sample_positions(self, *, sample_rate: float, online_column: str) -> np.ndarray:
        key = (float(sample_rate), online_column)
        cached = self._sample_positions.get(key)
        if cached is None:
            from health_tools.core.check_sampling import build_sample_positions

            cached = build_sample_positions(
                self.frame, sample_rate=sample_rate, online_column=online_column
            )
            self._sample_positions[key] = cached
        return cached

    def sample_frame(
        self,
        *,
        positions: np.ndarray,
        sample_rate: float,
        timestamp_column: str,
        ref_column: str,
        online_column: str,
        comp_column: Optional[str],
    ) -> pd.DataFrame:
        key = (
            timestamp_column,
            ref_column,
            online_column,
            comp_column,
            float(sample_rate),
            tuple(int(value) for value in np.asarray(positions, dtype=np.int64)),
        )
        cached = self._sample_frames.get(key)
        if cached is None:
            from health_tools.core.check_sampling import sample_check_seconds

            cached = sample_check_seconds(
                self.frame,
                positions=positions,
                timestamp_column=timestamp_column,
                ref_column=ref_column,
                online_column=online_column,
                comp_column=comp_column,
            )
            self._sample_frames[key] = cached
        return cached


def _rule_mismatch(
    checker,
    frame,
    checks,
    timestamp_column,
    chip,
    require_acc,
    ref_hr_column=None,
    ref_spo2_column=None,
) -> str:
    missing = []
    cached = getattr(checker, "_check_context", None)
    data_columns = (
        cached.data_columns
        if cached is not None and cached.frame is frame
        else [column for column in checker._get_data_columns() if column in frame.columns]
    )
    frame_column = (
        cached.frame_column
        if cached is not None and cached.frame is frame
        else checker._resolve_frame_column(frame)
    )
    if ({"range", "center"} & checks) and not data_columns:
        missing.append("数据列")
    if "frame" in checks and not frame_column:
        missing.append("帧号列")
    if "ipd" in checks and chip.startswith("gh3036"):
        ipd_columns = (
            cached.ipd_columns
            if cached is not None and cached.frame is frame
            else [column for column in checker._get_ipd_columns() if column in frame.columns]
        )
        if not ipd_columns or not data_columns:
            missing.append("Ipd/Rawdata列")
    acc_columns = (
        cached.acc_columns
        if cached is not None and cached.frame is frame
        else checker._resolve_acc_columns(frame)
    )
    if require_acc and not acc_columns:
        missing.append("ACC列")
    if timestamp_column and timestamp_column not in frame.columns:
        missing.append(f"时间戳列 {timestamp_column}")
    if "ref" in checks:
        if ref_hr_column and ref_hr_column not in frame.columns:
            missing.append(f"心率金标列 {ref_hr_column}")
        if ref_spo2_column and ref_spo2_column not in frame.columns:
            missing.append(f"血氧金标列 {ref_spo2_column}")
    return f"列结构不符合规则，缺少 {'、'.join(dict.fromkeys(missing))}" if missing else ""


def _relative_path(path: Path, base: Optional[Path]) -> str:
    if base is None:
        return path.name
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.name


def _item_issue(item: ItemResult) -> str:
    """合并分类原因和底层异常详情，避免报告只显示笼统原因。"""
    reason = (item.reason or "未知原因").strip()
    detail = (item.detail or "").strip()
    if not detail or detail == reason or detail in reason:
        return reason
    return f"{reason}：{detail}"


def _compile_scene_regex(pattern: Optional[str]):
    if not pattern:
        return None
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        raise RequestValidationError(f"scene-regex 正则无效: {exc}") from exc
    if "scene" not in compiled.groupindex:
        raise RequestValidationError("scene-regex 必须包含命名捕获组 (?P<scene>...)")
    return compiled


def _scene_for_path(compiled, relative_path: str) -> Tuple[str, str, str]:
    if compiled is None:
        return "default", "default", "default"
    match = compiled.search(relative_path)
    if not match:
        return "default", "default", "default"
    groups = match.groupdict()
    return (
        groups.get("scene") or "default",
        groups.get("name") or "default",
        groups.get("hand") or "default",
    )


def _anomaly_fields(anomaly) -> List[object]:
    if anomaly.count <= 0:
        return [0, "-", "-"]
    return [
        anomaly.count,
        anomaly.max_duration,
        "'" + ",".join(str(value) for value in anomaly.frames[:10]),
    ]


_DEFAULT_ACCURACY_METHODS = (
    "mae",
    "within_5",
    "within_10",
    "within_15",
    "rmse",
    "correlation",
)


def _resolve_accuracy_methods(request: CheckRequest) -> List[str]:
    """按请求阈值覆盖规则中的 within_N 方法。"""
    return resolve_accuracy_methods(request.accuracy_methods, request.accuracy_thresholds)


def _accuracy_methods(reports) -> List[str]:
    configured = next(
        (
            tuple(getattr(report, "accuracy_methods", ()))
            for report in reports
            if getattr(report, "accuracy_methods", ())
        ),
        (),
    )
    methods = list(configured or _DEFAULT_ACCURACY_METHODS)
    for report in reports:
        result = getattr(report, "accuracy_result", None)
        for values in (getattr(result, "online", None), getattr(result, "comp", None)):
            if values:
                for method in values:
                    if method != "samples" and method not in methods:
                        methods.append(method)
    return methods


def _accuracy_header(prefix: str, methods: List[str]) -> List[str]:
    return [f"{prefix}准确度样本数"] + [
        f"{prefix}{('' if method == 'correlation' else ' ')}{('相关系数' if method == 'correlation' else format_metric_name(method))}{'准确度' if method.startswith('within_') else ''}"
        for method in methods
    ]


def _accuracy_values(result, methods: List[str]) -> List[object]:
    if result is None:
        return ["-"] * (len(methods) + 1)
    values = result or {}
    row: List[object] = [values.get("samples", "-")]
    for method in methods:
        value = values.get(method)
        if value is None:
            row.append("-")
        elif method.startswith("within_"):
            row.append(f"{float(value):.2f}%")
        else:
            row.append(f"{float(value):.2f}")
    return row


def _accuracy_mark_values(report) -> Tuple[str, str]:
    result = getattr(report, "accuracy_result", None)
    mark = getattr(result, "matched_mark", None) if result else None
    return (mark.category, mark.label) if mark else ("", "")


def _report_row_as_dict(
    report, check_names: List[str], acc_reports: dict, base: Path, include_axis: bool
):
    result_map = {result.name: result for result in report.results}
    row: Dict[str, object] = {
        "文件名": report.file_path.name,
        "芯片": report.chip,
        "总异常(结果)": report.total_status,
    }
    for name in check_names:
        result = result_map.get(name)
        row[f"{name}(结果)"] = result.status if result else "-"
        row[f"{name}(说明)"] = result.summary if result else "-"
    if acc_reports:
        acc = acc_reports.get(report.file_path)
        fields = []
        if acc:
            fields.extend(_anomaly_fields(acc.zero))
            fields.extend(_anomaly_fields(acc.static_xyz))
            fields.extend(_anomaly_fields(acc.cyclic_xyz))
            if include_axis:
                for name in (
                    "static_x",
                    "static_y",
                    "static_z",
                    "cyclic_x",
                    "cyclic_y",
                    "cyclic_z",
                ):
                    fields.extend(_anomaly_fields(getattr(acc, name)))
        else:
            fields = ["-"] * (27 if include_axis else 9)
        acc_names = [
            "ACC全零次数",
            "ACC全零最长帧",
            "ACC全零前10帧",
            "ACC静止XYZ次数",
            "ACC静止XYZ最长帧",
            "ACC静止XYZ前10帧",
            "ACC循环XYZ次数",
            "ACC循环XYZ最长帧",
            "ACC循环XYZ前10帧",
        ]
        if include_axis:
            for kind in ("静止", "循环"):
                for axis in "XYZ":
                    acc_names.extend(
                        [f"ACC{kind}{axis}次数", f"ACC{kind}{axis}最长帧", f"ACC{kind}{axis}前10帧"]
                    )
        row.update(dict(zip(acc_names, fields)))
    methods = _accuracy_methods([report])
    row["场景分类"] = report.scene
    row["姓名"] = report.name
    row["手别"] = report.hand
    row["主要异常项"] = primary_issue(
        {
            **{k: str(v) for k, v in row.items()},
            "准确度标定分类": _accuracy_mark_values(report)[0],
            "准确度标定说明": _accuracy_mark_values(report)[1],
        }
    )
    accuracy_result = getattr(report, "accuracy_result", None)
    row.update(
        dict(
            zip(
                _accuracy_header("Online", methods),
                _accuracy_values(getattr(accuracy_result, "online", None), methods),
            )
        )
    )
    row.update(
        dict(
            zip(
                _accuracy_header("Comp", methods),
                _accuracy_values(getattr(accuracy_result, "comp", None), methods),
            )
        )
    )
    mark_category, mark_label = _accuracy_mark_values(report)
    row["准确度标定分类"] = mark_category
    row["准确度标定说明"] = mark_label
    row["文件相对路径"] = _relative_path(report.file_path, base)
    return row, methods


def _save_report(
    reports,
    acc_reports,
    output: Path,
    base: Path,
    include_axis: bool,
    items=(),
) -> None:
    check_names = []
    for report in reports:
        for result in report.results:
            if result.name not in check_names:
                check_names.append(result.name)
    methods = _accuracy_methods(reports)
    header = ["文件名", "芯片", "总异常(结果)"]
    for name in check_names:
        header.extend([f"{name}(结果)", f"{name}(说明)"])
        if name in {"心率金标", "血氧金标"}:
            header.append(f"{name}(异常时间)")
    if acc_reports:
        header.extend(
            [
                "ACC全零次数",
                "ACC全零最长帧",
                "ACC全零前10帧",
                "ACC静止XYZ次数",
                "ACC静止XYZ最长帧",
                "ACC静止XYZ前10帧",
                "ACC循环XYZ次数",
                "ACC循环XYZ最长帧",
                "ACC循环XYZ前10帧",
            ]
        )
        if include_axis:
            for kind in ("静止", "循环"):
                for axis in "XYZ":
                    header.extend(
                        [f"ACC{kind}{axis}次数", f"ACC{kind}{axis}最长帧", f"ACC{kind}{axis}前10帧"]
                    )
    header.extend(["场景分类", "姓名", "手别", "主要异常项"])
    header.extend(_accuracy_header("Online", methods))
    header.extend(_accuracy_header("Comp", methods))
    header.extend(["准确度标定分类", "准确度标定说明", "文件相对路径"])
    leading_columns = [
        "文件名",
        "芯片",
        "总异常(结果)",
        "场景分类",
        "姓名",
        "手别",
        "主要异常项",
    ]
    output_header = leading_columns + [column for column in header if column not in leading_columns]
    output.parent.mkdir(parents=True, exist_ok=True)
    report_paths = {report.file_path.resolve() for report in reports}
    with output.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(output_header)
        for report in reports:
            row: List[object] = [report.file_path.name, report.chip, report.total_status]
            result_map = {result.name: result for result in report.results}
            for name in check_names:
                result = result_map.get(name)
                row.extend([result.status, result.summary] if result else ["-", "-"])
                if name in {"心率金标", "血氧金标"}:
                    metric: Dict[str, Any] = (
                        next(iter(result.channel_metrics.values()), {}) if result else {}
                    )
                    row.append(metric.get("abnormal_times", "") if result else "-")
            if acc_reports:
                acc = acc_reports.get(report.file_path)
                if acc:
                    row.extend(_anomaly_fields(acc.zero))
                    row.extend(_anomaly_fields(acc.static_xyz))
                    row.extend(_anomaly_fields(acc.cyclic_xyz))
                    if include_axis:
                        for name in (
                            "static_x",
                            "static_y",
                            "static_z",
                            "cyclic_x",
                            "cyclic_y",
                            "cyclic_z",
                        ):
                            row.extend(_anomaly_fields(getattr(acc, name)))
                else:
                    row.extend(["-"] * (27 if include_axis else 9))
            accuracy_result = getattr(report, "accuracy_result", None)
            row.extend(
                [
                    report.scene,
                    report.name,
                    report.hand,
                    primary_issue(
                        {
                            **{k: str(v) for k, v in zip(header, row)},
                            "准确度标定分类": _accuracy_mark_values(report)[0],
                            "准确度标定说明": _accuracy_mark_values(report)[1],
                        }
                    ),
                ]
            )
            row.extend(_accuracy_values(getattr(accuracy_result, "online", None), methods))
            row.extend(_accuracy_values(getattr(accuracy_result, "comp", None), methods))
            row.extend([*_accuracy_mark_values(report), _relative_path(report.file_path, base)])
            row_by_name = dict(zip(header, row))
            writer.writerow([row_by_name[column] for column in output_header])
        for item in items:
            item_path = Path(item.input)
            try:
                resolved_path = item_path.resolve()
            except OSError:
                resolved_path = item_path
            if resolved_path in report_paths:
                continue
            reason = _item_issue(item)
            status = getattr(item.status, "value", str(item.status))
            row_by_name = {
                column: ""
                for column in output_header
                if column not in {"文件名", "总异常(结果)", "主要异常项", "文件相对路径"}
            }
            row_by_name.update(
                {
                    "文件名": item_path.name,
                    "总异常(结果)": status,
                    "主要异常项": f"{'跳过' if status == 'SKIP' else '失败'}：{reason}",
                    "文件相对路径": _relative_path(item_path, base),
                }
            )
            writer.writerow([row_by_name.get(column, "") for column in output_header])


COMPACT_HEADER = [
    "文件名",
    "场景分类",
    "姓名",
    "手别",
    "文件相对路径",
    "芯片",
    "检查项",
    "状态",
    "通道",
    "异常数",
    "总数",
    "异常占比",
    "偏低占比",
    "偏高占比",
    "近0占比",
    "近满量程占比",
    "AGC变化次数",
    "AGC有效对数",
    "AGC变化占比",
    "金标范围异常数",
    "金标非零占比",
    "金标阶跃次数",
    "金标阶跃阈值",
    "金标最大阶跃变化",
    "金标最大阶跃时间",
    "金标最长静止帧",
    "金标静止帧阈值",
    "金标异常时间",
    "说明",
    "比较对象",
    "准确度指标",
    "准确度阈值",
]


def _format_compact_percent(value) -> str:
    """将精简报告中的比例统一格式化为两位小数百分比。"""
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return str(value)


def _save_compact_report(reports, output: Path, base: Path) -> None:
    """保存仅包含 WARNING/FAIL 检查项的通道长表。"""
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=COMPACT_HEADER)
        writer.writeheader()
        for report in reports:
            agc_metrics = {}
            for result in report.results:
                if result.name == "AGC调光":
                    agc_metrics = result.channel_metrics
                    break
            for result in report.results:
                if result.status not in {"WARNING", "FAIL"}:
                    continue
                metrics = result.channel_metrics or {"-": {}}
                for channel, metric in metrics.items():
                    agc_count = metric.get("change_count", "")
                    agc_total = metric.get("total_count", "")
                    agc_ratio = metric.get("change_ratio", "")
                    if not agc_count and channel != "-":
                        suffix = channel.lower().replace("rawdata", "").replace("ch", "")
                        for agc_name, agc_metric in agc_metrics.items():
                            agc_suffix = agc_name.lower().replace("agc_info_", "").replace("ch", "")
                            if agc_suffix == suffix:
                                agc_count = agc_metric.get("change_count", "")
                                agc_total = agc_metric.get("total_count", "")
                                agc_ratio = agc_metric.get("change_ratio", "")
                                break
                    writer.writerow(
                        {
                            "文件名": report.file_path.name,
                            "场景分类": report.scene,
                            "姓名": report.name,
                            "手别": report.hand,
                            "文件相对路径": _relative_path(report.file_path, base),
                            "芯片": report.chip,
                            "检查项": result.name,
                            "状态": result.status,
                            "通道": channel,
                            "异常数": metric.get("abnormal_count", ""),
                            "总数": metric.get("total_count", ""),
                            "异常占比": _format_compact_percent(
                                metric.get("abnormal_ratio", result.abnormal_ratio)
                            ),
                            "偏低占比": _format_compact_percent(metric.get("low_ratio", "")),
                            "偏高占比": _format_compact_percent(metric.get("high_ratio", "")),
                            "近0占比": _format_compact_percent(metric.get("near_zero_ratio", "")),
                            "近满量程占比": _format_compact_percent(
                                metric.get("near_full_ratio", "")
                            ),
                            "AGC变化次数": agc_count,
                            "AGC有效对数": agc_total,
                            "AGC变化占比": _format_compact_percent(agc_ratio),
                            "金标范围异常数": metric.get("range_abnormal_count", ""),
                            "金标非零占比": _format_compact_percent(
                                metric.get("nonzero_ratio", "")
                            ),
                            "金标阶跃次数": metric.get("step_count", ""),
                            "金标阶跃阈值": metric.get("step_threshold", ""),
                            "金标最大阶跃变化": metric.get("max_step_change", ""),
                            "金标最大阶跃时间": metric.get("max_step_time", ""),
                            "金标最长静止帧": metric.get("longest_static_frames", ""),
                            "金标静止帧阈值": metric.get("static_frame_threshold", ""),
                            "金标异常时间": metric.get("abnormal_times", ""),
                            "说明": "",
                            "比较对象": "",
                            "准确度指标": "",
                            "准确度阈值": "",
                        }
                    )
            accuracy = getattr(report, "accuracy_result", None)
            mark = getattr(accuracy, "matched_mark", None) if accuracy else None
            if mark:
                from health_tools.core.check_accuracy import accuracy_mark_value

                accuracy_result = cast(CheckAccuracyResult, accuracy)
                source, metric = mark.left.split(".", 1)
                values = getattr(accuracy_result, source, None) or {}
                metric_value = accuracy_mark_value(accuracy_result, mark)
                writer.writerow(
                    {
                        "文件名": report.file_path.name,
                        "场景分类": report.scene,
                        "姓名": report.name,
                        "手别": report.hand,
                        "文件相对路径": _relative_path(report.file_path, base),
                        "芯片": report.chip,
                        "检查项": "准确度标定",
                        "状态": "WARNING",
                        "通道": source,
                        "异常数": metric_value,
                        "总数": (values.get("samples", "") if values else ""),
                        "异常占比": _format_compact_percent(metric_value),
                        "说明": mark.label,
                        "比较对象": ("Online vs Comp" if mark.right else "Ref"),
                        "准确度指标": format_metric_name(metric),
                        "准确度阈值": mark.threshold,
                    }
                )


def _write_sort_list(path: Path, rows: List[List[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["文件名", "文件相对路径", "目标路径", "状态", "原因", "分类", "场景分类"])
        writer.writerows(rows)


def _sort_report(report: Path, output: Path) -> Dict[str, int]:
    with report.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise RequestValidationError(f"检查报告为空: {report}")
    required = {"文件名", "总异常(结果)", "文件相对路径"}
    missing = required - set(rows[0])
    if missing:
        raise RequestValidationError(f"检查报告缺少必要列: {', '.join(sorted(missing))}")
    records: Dict[str, List[List[str]]] = {"normal": [], "abnormal": []}
    stats: Dict[str, int] = {"skipped": 0}
    for row in rows:
        relative_text = row.get("文件相对路径", "").strip()
        file_name = row.get("文件名", "").strip()
        scene = row.get("场景分类", "default") or "default"
        category = _sort_category(row)
        bucket = "normal" if category == "normal" else "abnormal"
        if not relative_text:
            records[bucket].append([file_name, "", "", "跳过", "文件相对路径为空", category, scene])
            stats["skipped"] += 1
            continue
        relative = Path(relative_text)
        destination_root = (
            output / "normal" if category == "normal" else output / "abnormal" / category
        )
        destination = destination_root / relative
        if relative.is_absolute() or ".." in relative.parts:
            records[bucket].append(
                [
                    file_name,
                    relative_text,
                    "",
                    "跳过",
                    "文件相对路径非法",
                    category,
                    scene,
                ]
            )
            stats["skipped"] += 1
            continue
        source = report.parent / relative
        if not source.exists() or destination.exists():
            reason = "源文件不存在" if not source.exists() else "目标文件已存在"
            records[bucket].append(
                [
                    file_name,
                    relative_text,
                    str(destination),
                    "跳过",
                    reason,
                    category,
                    scene,
                ]
            )
            stats["skipped"] += 1
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        records[bucket].append(
            [
                file_name,
                relative_text,
                str(destination),
                "已移动",
                "",
                category,
                scene,
            ]
        )
        stats[category] = stats.get(category, 0) + 1
    _write_sort_list(output / "normal_files.csv", records["normal"])
    _write_sort_list(output / "abnormal_files.csv", records["abnormal"])
    return stats


def run_check(request: CheckRequest, *, context: Optional[ExecutionContext] = None) -> CheckResult:
    """检查 CSV 数据质量，或按既有报告分拣文件。"""
    from health_tools.core.checker import DataChecker, FileCheckReport
    from health_tools.rules.loader import RuleLoader
    from health_tools.utils.csv_handler import CSVHandler

    ctx = _context(context)
    if request.sort_report:
        if request.sort_output is None:
            raise RequestValidationError("分拣模式需要 sort_output")
        sort_report_path = request.report_path or Path.cwd() / "check_report.csv"
        _require_path(sort_report_path, "检查报告")
        ctx.check_cancelled("sort")
        ctx.emit(ProgressEvent("check", "sort", 0, 1, "分拣文件", str(sort_report_path)))
        counts = _sort_report(sort_report_path, request.sort_output)
        sort_artifacts = (
            request.sort_output / "normal_files.csv",
            request.sort_output / "abnormal_files.csv",
        )
        result = CheckResult(BatchResult("check", artifacts=sort_artifacts), sort_counts=counts)
        ctx.emit(ProgressEvent("check", "sort", 1, 1, "完成", str(sort_report_path)))
        return result
    if request.input_path is None:
        raise RequestValidationError("普通检查模式需要 input_path")
    target = _require_path(request.input_path)
    scene_pattern = _compile_scene_regex(request.scene_regex)
    base = target.parent if target.is_file() else target
    files = _discover_check_inputs(target)
    checks = (
        set(request.checks.split(","))
        if request.checks
        else {
            "range",
            "ipd",
            "frame",
            "center",
            "acc",
            "agc",
        }
    )
    unknown = checks - {"range", "ipd", "frame", "center", "acc", "agc", "ref"}
    if unknown:
        raise RequestValidationError(f"未知检查项: {', '.join(sorted(unknown))}")
    if request.workers < 1:
        raise RequestValidationError("workers 必须大于 0")
    if not math.isfinite(request.ref_sample_rate) or request.ref_sample_rate <= 0:
        raise RequestValidationError("ref_sample_rate 必须大于 0 且为有限数值")
    if not math.isfinite(request.ref_stale_seconds) or request.ref_stale_seconds <= 0:
        raise RequestValidationError("ref_stale_seconds 必须大于 0 且为有限数值")
    if not math.isfinite(request.ref_warning_seconds) or request.ref_warning_seconds <= 0:
        raise RequestValidationError("ref_warning_seconds 必须大于 0 且为有限数值")
    if not math.isfinite(request.ref_step_threshold) or request.ref_step_threshold < 0:
        raise RequestValidationError("ref_step_threshold 必须大于等于 0 且为有限数值")
    items: List[ItemResult] = []
    reports = []
    acc_reports = {}
    ipd_details = {}
    reference_details = {}

    def check_one(
        path: Path,
    ) -> Tuple[ItemResult, Optional[Any], Optional[Any], Optional[Any], Optional[Any]]:
        chip = request.chip_name or _detect_chip(path)
        if not chip:
            return (
                ItemResult(ItemStatus.SKIP, str(path), reason="无法识别芯片"),
                None,
                None,
                None,
                None,
            )
        try:
            chip_rule = _load_rule(RuleLoader.load_chip_rule, chip, "芯片")
            _, frame = CSVHandler(chip_rule).read(path)
            if frame.empty:
                return (
                    ItemResult(ItemStatus.SKIP, str(path), reason="空文件"),
                    None,
                    None,
                    None,
                    None,
                )
            checker = DataChecker(
                chip_rule, tolerance=request.tolerance, static_min=request.static_min
            )
            file_context = _FileCheckContext.create(path, chip, chip_rule, frame, checker)
            mismatch = _rule_mismatch(
                checker,
                file_context.frame,
                checks,
                request.timestamp_column,
                chip,
                request.checks is not None and "acc" in checks,
                request.ref_hr_column if (request.checks is None or "ref" in checks) else None,
                request.ref_spo2_column if (request.checks is None or "ref" in checks) else None,
            )
            if mismatch:
                return (
                    ItemResult(ItemStatus.SKIP, str(path), reason=mismatch),
                    None,
                    None,
                    None,
                    None,
                )
            relative_path = _relative_path(path, base)
            scene, name, hand = _scene_for_path(scene_pattern, relative_path)
            report = FileCheckReport(
                file_path=path,
                chip=chip,
                scene=scene,
                name=name,
                hand=hand,
            )
            # Keep the local name for report code readable while all column
            # resolution now goes through the file-scoped context.
            frame = file_context.frame
            if "range" in checks:
                report.results.append(checker.check_data_range(frame, request.range_ratio))
            if "frame" in checks:
                report.results.append(checker.check_frame_completeness(frame, request.frame_ratio))
            if "center" in checks:
                report.results.append(checker.check_data_centering(frame, request.center_ratio))
            if "agc" in checks:
                report.results.append(checker.check_agc_changes(frame))
            timestamp_result = None
            timestamp_intervals = None
            if request.timestamp_column:
                timestamp_intervals, timestamp_error = file_context.timestamp_analysis(
                    request.timestamp_column
                )
                timestamp_result = checker.check_timestamp_interval(
                    frame,
                    request.timestamp_column,
                    ratio_tolerance=request.timestamp_ratio,
                    ms_tolerance=request.timestamp_ms,
                    threshold_ratio=request.timestamp_fail_ratio,
                    expected_base_ms=request.timestamp_base_ms,
                    _intervals_ms=timestamp_intervals,
                    _parse_error=timestamp_error,
                )
                report.results.append(timestamp_result)
            ref_enabled = request.checks is None or "ref" in checks
            sample_positions = np.empty(0, dtype=np.int64)
            sampling_online = request.accuracy_online_column or "ALGO_RESULT0"
            sampling_rate = request.ref_sample_rate
            if timestamp_result is not None and timestamp_result.status == "FAIL":
                from health_tools.core.check_sampling import predict_sample_rate_from_timestamp

                predicted_rate = predict_sample_rate_from_timestamp(
                    frame,
                    timestamp_column=request.timestamp_column or "",
                    intervals_ms=timestamp_intervals,
                )
                if predicted_rate is not None:
                    sampling_rate = float(predicted_rate)
            if (
                ref_enabled and (request.ref_hr_column or request.ref_spo2_column)
            ) or request.accuracy_enabled:
                sample_positions = file_context.sample_positions(
                    sample_rate=sampling_rate, online_column=sampling_online
                )
            evidence_frame = None
            if ref_enabled and request.ref_hr_column:
                reference_frame = file_context.sample_frame(
                    positions=sample_positions,
                    sample_rate=sampling_rate,
                    timestamp_column=request.timestamp_column or "TimeStamp",
                    ref_column=request.ref_hr_column,
                    online_column=sampling_online,
                    comp_column=request.accuracy_comp_column,
                )
                report.results.append(
                    checker.check_reference_data(
                        reference_frame.rename(columns={"ref": request.ref_hr_column}),
                        request.ref_hr_column,
                        "hr",
                        1.0,
                        request.ref_stale_seconds,
                        request.ref_step_threshold,
                        request.ref_warning_seconds,
                    )
                )
            if ref_enabled and request.ref_spo2_column:
                reference_frame = file_context.sample_frame(
                    positions=sample_positions,
                    sample_rate=sampling_rate,
                    timestamp_column=request.timestamp_column or "TimeStamp",
                    ref_column=request.ref_spo2_column,
                    online_column=sampling_online,
                    comp_column=request.accuracy_comp_column,
                )
                report.results.append(
                    checker.check_reference_data(
                        reference_frame.rename(columns={"ref": request.ref_spo2_column}),
                        request.ref_spo2_column,
                        "spo2",
                        1.0,
                        request.ref_stale_seconds,
                        request.ref_step_threshold,
                        request.ref_warning_seconds,
                    )
                )
            if "ipd" in checks and chip.startswith("gh3036"):
                ipd_result = checker.check_ipd_conversion(frame, request.ipd_ratio)
                report.results.append(ipd_result)
                if ipd_result.failed:
                    ipd_detail = checker.build_ipd_detail(frame)
                else:
                    ipd_detail = None
            else:
                ipd_detail = None
            if "acc" in checks:
                acc = checker.check_acc_anomaly(frame, include_single_axis=request.acc_axis)
                acc.file_path = path
                report.results.append(checker.build_acc_result(acc, request.acc_ratio))
            else:
                acc = None
            if request.accuracy_enabled:
                from health_tools.core.check_accuracy import calculate_check_accuracy
                from health_tools.models.rules import CheckAccuracyRule

                accuracy_methods = _resolve_accuracy_methods(request)
                accuracy_frame = file_context.sample_frame(
                    positions=sample_positions,
                    sample_rate=sampling_rate,
                    timestamp_column=request.timestamp_column or "TimeStamp",
                    ref_column=request.accuracy_ref_column or "REF_RESULT0",
                    online_column=request.accuracy_online_column or "ALGO_RESULT0",
                    comp_column=request.accuracy_comp_column,
                )
                report.accuracy_result = calculate_check_accuracy(
                    accuracy_frame.rename(
                        columns={
                            "ref": request.accuracy_ref_column or "REF_RESULT0",
                            "online": request.accuracy_online_column or "ALGO_RESULT0",
                            "comp": request.accuracy_comp_column or "__comp__",
                        }
                    ),
                    CheckAccuracyRule(
                        enabled=True,
                        ref_column=request.accuracy_ref_column or "REF_RESULT0",
                        online_column=request.accuracy_online_column or "ALGO_RESULT0",
                        comp_column=request.accuracy_comp_column,
                        methods=tuple(accuracy_methods),
                        thresholds=tuple(dict(item) for item in request.accuracy_custom_thresholds),
                        inclusive=request.accuracy_inclusive,
                        marks=tuple(request.accuracy_marks),
                    ),
                )
                report.accuracy_methods = tuple(accuracy_methods)
            reference_abnormal = any(
                result.name in {"心率金标", "血氧金标"} and result.status in {"WARNING", "FAIL"}
                for result in report.results
            )
            if request.reference_detail_output is not None and reference_abnormal:
                evidence_frame = file_context.sample_frame(
                    positions=sample_positions,
                    sample_rate=sampling_rate,
                    timestamp_column=request.timestamp_column or "TimeStamp",
                    ref_column=request.accuracy_ref_column
                    or request.ref_hr_column
                    or request.ref_spo2_column
                    or "REF_RESULT0",
                    online_column=sampling_online,
                    comp_column=request.accuracy_comp_column,
                )
            return ItemResult(ItemStatus.OK, str(path)), report, acc, ipd_detail, evidence_frame
        except Exception as exc:
            return (
                ItemResult(
                    ItemStatus.FAIL,
                    str(path),
                    reason=classify_exception(exc, REASON_PROCESS_FAILED),
                    detail=format_exception_detail(exc),
                ),
                None,
                None,
                None,
                None,
            )

    from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait

    total = len(files)
    ctx.check_cancelled("files", _batch("check", items))
    ctx.emit(ProgressEvent("check", "files", 0, total, "开始"))

    # 限制同时在途的文件任务数量，避免大批量输入一次性创建数千个 Future。
    # 空输入也保留至少一个 worker/window，维持原有边界行为。
    effective_workers = min(request.workers, max(1, total), _MAX_FILE_WORKERS)
    window = max(1, effective_workers * 2)
    executor = ThreadPoolExecutor(max_workers=effective_workers)
    pending: Dict[Future, Tuple[int, Path]] = {}
    file_iter = enumerate(files)

    def submit_available() -> None:
        while len(pending) < window:
            try:
                index, path = next(file_iter)
            except StopIteration:
                break
            pending[executor.submit(check_one, path)] = (index, path)

    submit_available()
    completed_records: Dict[int, Tuple[Path, Any, Any, Any, Any, Any, bool]] = {}

    def completed_batch() -> BatchResult:
        completed_items = list(items)
        completed_items.extend(
            record[1] for _, record in sorted(completed_records.items()) if not record[-1]
        )
        return _batch("check", completed_items)

    try:
        completed = 0
        while pending:
            ctx.check_cancelled("files", completed_batch())
            done, _ = wait(tuple(pending), return_when=FIRST_COMPLETED)
            for future in done:
                index, path = pending.pop(future)
                item, report, acc, ipd_detail, evidence = future.result()
                ignored = _is_failed_check_report(item, path)
                completed += 1
                completed_records[index] = (
                    path,
                    item,
                    report,
                    acc,
                    ipd_detail,
                    evidence,
                    ignored,
                )
                message = "忽略check报告" if ignored else "完成"
                ctx.emit(ProgressEvent("check", "files", completed, total, message, str(path)))
            # 收集已完成任务后再补充窗口，保证待处理 Future 数量有界。
            ctx.check_cancelled("files", completed_batch())
            submit_available()
        ctx.check_cancelled("files", completed_batch())
    except BaseException:
        for future in pending:
            future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        raise
    else:
        executor.shutdown(wait=True)

    # 按输入顺序汇总，避免有界调度改变报告行及证据/明细文件顺序。
    for index in sorted(completed_records):
        path, item, report, acc, ipd_detail, evidence, ignored = completed_records[index]
        if ignored:
            continue
        items.append(item)
        if report is not None:
            reports.append(report)
        if acc is not None:
            acc_reports[path] = acc
        if ipd_detail is not None and not ipd_detail.empty:
            ipd_details[path] = ipd_detail
        if evidence is not None:
            reference_details[path] = evidence
    if not reports and not items:
        return CheckResult(_batch("check", items))
    report_path = request.output_path or (
        target.parent / "check_report.csv" if target.is_file() else target / "check_report.csv"
    )
    _save_report(reports, acc_reports, report_path, base, request.acc_axis, items)
    compact_report_path = _compact_report_path(report_path)
    _save_compact_report(reports, compact_report_path, base)
    artifacts = [report_path, compact_report_path]
    for path, frame in ipd_details.items():
        detail = report_path.parent / f"ipd_detail_{path.stem}.csv"
        frame.to_csv(detail, index=False, encoding="utf-8-sig")
        artifacts.append(detail)
    reference_detail_paths = []
    if request.reference_detail_output is not None:
        detail_root = Path(request.reference_detail_output)
        for source, frame in reference_details.items():
            destination = detail_root / _relative_path(source, base)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                raise RequestValidationError(f"金标证据文件已存在，不覆盖: {destination}")
            frame.to_csv(destination, index=False, encoding="utf-8-sig")
            reference_detail_paths.append(destination)
            artifacts.append(destination)
    return CheckResult(
        _batch("check", items, artifacts),
        report_path=report_path,
        compact_report_path=compact_report_path,
        reference_detail_paths=tuple(reference_detail_paths),
    )
