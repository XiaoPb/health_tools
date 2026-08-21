"""数据质量检查公共 API。"""

from __future__ import annotations

import csv
import math
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from health_tools.api.context import ExecutionContext
from health_tools.api.errors import RequestValidationError
from health_tools.api.models import (
    BatchResult,
    CheckRequest,
    CheckResult,
    ItemResult,
    ItemStatus,
    ProgressEvent,
)
from health_tools.api.operations import _batch, _context, _load_rule, _require_path
from health_tools.utils.errors import REASON_PROCESS_FAILED, classify_exception

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
    ("Ipd转换(结果)", "FAIL", "ipd", "Ipd异常"),
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
    return label or ("其他异常" if row.get("总异常(结果)", "").strip().upper() == "FAIL" else "")


def _safe_category_name(check_name: str) -> str:
    """将扩展检查项名称转换为单个安全目录名。"""
    name = check_name.replace("\\", "/").split("/")[-1]
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return name or "total_fail"


def _fallback_check_category(row: Dict[str, str]) -> str:
    """识别低优先级检查项，未知项保留检查名称作为独立目录。"""
    for column, value in row.items():
        if not column.endswith("(结果)") or column == "总异常(结果)":
            continue
        if (value or "").strip().upper() != "FAIL":
            continue
        check_name = column[: -len("(结果)")]
        return TRAILING_CHECK_CATEGORIES.get(check_name, _safe_category_name(check_name))
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
    data_columns = [column for column in checker._get_data_columns() if column in frame.columns]
    frame_column = checker._resolve_frame_column(frame)
    if ({"range", "center"} & checks) and not data_columns:
        missing.append("数据列")
    if "frame" in checks and not frame_column:
        missing.append("帧号列")
    if "ipd" in checks and chip.startswith("gh3036"):
        ipd_columns = [column for column in checker._get_ipd_columns() if column in frame.columns]
        if not ipd_columns or not data_columns:
            missing.append("Ipd/Rawdata列")
    if require_acc and not checker._resolve_acc_columns(frame):
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


def _scene_for_path(compiled, relative_path: str) -> str:
    if compiled is None:
        return "default"
    match = compiled.search(relative_path)
    if not match:
        return "default"
    return match.group("scene") or "default"


def _anomaly_fields(anomaly) -> List[object]:
    if anomaly.count <= 0:
        return [0, "-", "-"]
    return [
        anomaly.count,
        anomaly.max_duration,
        ",".join(str(value) for value in anomaly.frames[:10]),
    ]


def _save_report(reports, acc_reports, output: Path, base: Path, include_axis: bool) -> None:
    check_names = []
    for report in reports:
        for result in report.results:
            if result.name not in check_names:
                check_names.append(result.name)
    header = ["文件名", "芯片", "总异常(结果)"]
    for name in check_names:
        header.extend([f"{name}(结果)", f"{name}(说明)"])
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
    header.extend(["场景分类", "文件相对路径"])
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for report in reports:
            row: List[object] = [report.file_path.name, report.chip, report.total_status]
            result_map = {result.name: result for result in report.results}
            for name in check_names:
                result = result_map.get(name)
                row.extend([result.status, result.summary] if result else ["-", "-"])
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
            row.extend([report.scene, _relative_path(report.file_path, base)])
            writer.writerow(row)


COMPACT_HEADER = [
    "文件名",
    "场景分类",
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
    "金标最长静止帧",
    "金标静止帧阈值",
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
                            "金标最长静止帧": metric.get("longest_static_frames", ""),
                            "金标静止帧阈值": metric.get("static_frame_threshold", ""),
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
    files = (
        [target]
        if target.is_file()
        else sorted(path for path in target.rglob("*.csv") if path.name != "check_report.csv")
    )
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
    if not math.isfinite(request.ref_step_threshold) or request.ref_step_threshold < 0:
        raise RequestValidationError("ref_step_threshold 必须大于等于 0 且为有限数值")
    items: List[ItemResult] = []
    reports = []
    acc_reports = {}
    ipd_details = {}

    def check_one(
        path: Path,
    ) -> Tuple[ItemResult, Optional[Any], Optional[Any], Optional[Any]]:
        chip = request.chip_name or _detect_chip(path)
        if not chip:
            return ItemResult(ItemStatus.SKIP, str(path), reason="无法识别芯片"), None, None, None
        try:
            chip_rule = _load_rule(RuleLoader.load_chip_rule, chip, "芯片")
            _, frame = CSVHandler(chip_rule).read(path)
            if frame.empty:
                return ItemResult(ItemStatus.SKIP, str(path), reason="空文件"), None, None, None
            checker = DataChecker(
                chip_rule, tolerance=request.tolerance, static_min=request.static_min
            )
            mismatch = _rule_mismatch(
                checker,
                frame,
                checks,
                request.timestamp_column,
                chip,
                request.checks is not None and "acc" in checks,
                request.ref_hr_column if (request.checks is None or "ref" in checks) else None,
                request.ref_spo2_column if (request.checks is None or "ref" in checks) else None,
            )
            if mismatch:
                return ItemResult(ItemStatus.SKIP, str(path), reason=mismatch), None, None, None
            relative_path = _relative_path(path, base)
            report = FileCheckReport(
                file_path=path,
                chip=chip,
                scene=_scene_for_path(scene_pattern, relative_path),
            )
            if "range" in checks:
                report.results.append(checker.check_data_range(frame, request.range_ratio))
            if "frame" in checks:
                report.results.append(checker.check_frame_completeness(frame, request.frame_ratio))
            if "center" in checks:
                report.results.append(checker.check_data_centering(frame, request.center_ratio))
            if "agc" in checks:
                report.results.append(checker.check_agc_changes(frame))
            if request.timestamp_column:
                report.results.append(
                    checker.check_timestamp_interval(
                        frame,
                        request.timestamp_column,
                        ratio_tolerance=request.timestamp_ratio,
                        ms_tolerance=request.timestamp_ms,
                        threshold_ratio=request.timestamp_fail_ratio,
                        expected_base_ms=request.timestamp_base_ms,
                    )
                )
            ref_enabled = request.checks is None or "ref" in checks
            if ref_enabled and request.ref_hr_column:
                report.results.append(
                    checker.check_reference_data(
                        frame,
                        request.ref_hr_column,
                        "hr",
                        request.ref_sample_rate,
                        request.ref_stale_seconds,
                        request.ref_step_threshold,
                    )
                )
            if ref_enabled and request.ref_spo2_column:
                report.results.append(
                    checker.check_reference_data(
                        frame,
                        request.ref_spo2_column,
                        "spo2",
                        request.ref_sample_rate,
                        request.ref_stale_seconds,
                        request.ref_step_threshold,
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

                report.accuracy_result = calculate_check_accuracy(
                    frame,
                    CheckAccuracyRule(
                        enabled=True,
                        ref_column=request.accuracy_ref_column or "REF_RESULT0",
                        online_column=request.accuracy_online_column or "ALGO_RESULT0",
                        comp_column=request.accuracy_comp_column,
                        methods=tuple(request.accuracy_methods),
                        thresholds=tuple(request.accuracy_custom_thresholds),
                        inclusive=request.accuracy_inclusive,
                        marks=tuple(request.accuracy_marks),
                    ),
                )
            return ItemResult(ItemStatus.OK, str(path)), report, acc, ipd_detail
        except Exception as exc:
            return (
                ItemResult(
                    ItemStatus.FAIL,
                    str(path),
                    reason=classify_exception(exc, REASON_PROCESS_FAILED),
                    detail=str(exc),
                ),
                None,
                None,
                None,
            )

    from concurrent.futures import ThreadPoolExecutor, as_completed

    total = len(files)
    ctx.check_cancelled("files", _batch("check", items))
    ctx.emit(ProgressEvent("check", "files", 0, total, "开始"))
    executor = ThreadPoolExecutor(max_workers=request.workers)
    futures = {executor.submit(check_one, path): path for path in files}
    try:
        for completed, future in enumerate(as_completed(futures), 1):
            ctx.check_cancelled("files", _batch("check", items))
            path = futures[future]
            item, report, acc, ipd_detail = future.result()
            items.append(item)
            if report is not None:
                reports.append(report)
            if acc is not None:
                acc_reports[path] = acc
            if ipd_detail is not None and not ipd_detail.empty:
                ipd_details[path] = ipd_detail
            ctx.emit(ProgressEvent("check", "files", completed, total, "完成", str(path)))
        ctx.check_cancelled("files", _batch("check", items))
    except BaseException:
        for future in futures:
            future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        raise
    else:
        executor.shutdown(wait=True)
    if not reports:
        return CheckResult(_batch("check", items))
    report_path = request.output_path or (
        target.parent / "check_report.csv" if target.is_file() else target / "check_report.csv"
    )
    _save_report(reports, acc_reports, report_path, base, request.acc_axis)
    compact_report_path = report_path.parent / "check_report_compact.csv"
    _save_compact_report(reports, compact_report_path, base)
    artifacts = [report_path, compact_report_path]
    for path, frame in ipd_details.items():
        detail = report_path.parent / f"ipd_detail_{path.stem}.csv"
        frame.to_csv(detail, index=False, encoding="utf-8-sig")
        artifacts.append(detail)
    return CheckResult(
        _batch("check", items, artifacts),
        report_path=report_path,
        compact_report_path=compact_report_path,
    )
