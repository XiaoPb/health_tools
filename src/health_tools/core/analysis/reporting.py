"""分析结果的 JSON、CSV、Markdown 和 PPT 输出。"""

from __future__ import annotations

import csv
import json
from importlib.resources import files
from pathlib import Path
from typing import Any, Dict, Iterable, List

import matplotlib.pyplot as plt
import numpy as np

from health_tools.core.analysis.models import AnalysisRecord

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False


def _accuracy_rows(records: List[AnalysisRecord]) -> List[Dict[str, Any]]:
    groups: Dict[str, List[AnalysisRecord]] = {"整体": records}
    for record in records:
        groups.setdefault(record.scene, []).append(record)
    labels = {
        "online": "Online vs Polar",
        "offline": "Offline vs Polar",
        "comp": "Comp vs Polar",
    }
    rows: List[Dict[str, Any]] = []
    for name, items in groups.items():
        comparison_items: Dict[str, List[Dict[str, Any]]] = {}
        for item in items:
            comparisons = item.metrics.get("comparisons")
            if isinstance(comparisons, dict):
                for comparison, metrics in comparisons.items():
                    if isinstance(metrics, dict) and metrics:
                        comparison_items.setdefault(str(comparison), []).append(metrics)
            elif item.metrics.get("samples") is not None:
                comparison_items.setdefault("online", []).append(item.metrics)
        names = ["online", "offline"]
        if comparison_items.get("comp"):
            names.append("comp")
        for comparison in names:
            metrics_list = comparison_items.get(comparison, [])
            samples = sum(int(metrics.get("samples") or 0) for metrics in metrics_list)
            row: Dict[str, Any] = {
                "comparison": labels[comparison],
                "scene": name,
                "files": len(metrics_list),
                "samples": samples,
                "available": samples > 0,
                "mae": None,
                "max_error": None,
                "within_5": None,
                "within_10": None,
                "within_15": None,
            }
            if samples:
                for metric in ("mae", "within_5", "within_10", "within_15"):
                    row[metric] = (
                        sum(
                            float(values.get(metric) or 0) * int(values.get("samples") or 0)
                            for values in metrics_list
                        )
                        / samples
                    )
                row["max_error"] = max(
                    float(values.get("max_error") or 0) for values in metrics_list
                )
            rows.append(row)
    return rows


def _cause_counts(records: List[AnalysisRecord]) -> List[Dict[str, Any]]:
    counts: Dict[tuple, int] = {}
    labels = {"raw": "原始数据", "reference": "参考数据", "algorithm": "算法性能边界"}
    for record in records:
        if not record.abnormal:
            continue
        cause = record.cause or {}
        origin = str(cause.get("origin", "unknown"))
        title = str(cause.get("title") or record.conclusion)
        key = (labels.get(origin, "未确定"), title)
        counts[key] = counts.get(key, 0) + 1
    return [
        {"category": category, "cause": cause, "files": count}
        for (category, cause), count in sorted(counts.items())
    ]


def _plain(record: AnalysisRecord) -> Dict[str, Any]:
    return {
        "file": record.file,
        "source": record.source,
        "analysis_type": record.analysis_type,
        "scene": record.scene,
        "focused": record.focused,
        "features": record.features,
        "metrics": record.metrics,
        "segments": [segment.__dict__ for segment in record.segments],
        "psd": record.psd,
        "cause": record.cause,
        "conclusion": record.conclusion,
        "confidence": record.confidence,
        "notes": record.notes,
        "figure": record.figure,
    }


def write_evidence_figure(record: AnalysisRecord, output: Path):
    output.parent.mkdir(parents=True, exist_ok=True)
    interval = np.asarray(record.plot_data.get("sample_interval", []), dtype=float)
    interval_time = np.asarray(record.plot_data.get("interval_time", []), dtype=float)
    if not len(interval) or not len(interval_time):
        return None
    fig, axis = plt.subplots(1, 1, figsize=(14, 5))
    axis.plot(interval_time, interval, color="#ef5350", linewidth=0.8)
    axis.axhline(np.nanmedian(interval), color="#212121", linestyle="--", label="中位间隔")
    axis.set_title(f"{record.file} | 采样间隔异常")
    axis.set_ylabel("采样间隔 (s)")
    axis.set_xlabel("时间 (s)")
    axis.legend(loc="upper right")
    axis.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(output, dpi=150)
    plt.close(fig)
    record.figure = str(output)
    return output


def write_structured(records: Iterable[AnalysisRecord], output_dir: Path) -> List[Path]:
    records = list(records)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = output_dir / "analysis_summary.json"
    summary.write_text(
        json.dumps([_plain(record) for record in records], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    detail = output_dir / "file_diagnosis.csv"
    with detail.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "file",
                "scene",
                "focused",
                "conclusion",
                "confidence",
                "cause",
                "evidence",
                "actions",
                "mae",
                "max_error",
                "error_ratio",
                "within_5",
                "within_10",
                "within_15",
            ],
        )
        writer.writeheader()
        for record in records:
            cause = record.cause or {}
            writer.writerow(
                {
                    "file": record.file,
                    "scene": record.scene,
                    "focused": record.focused,
                    "conclusion": record.conclusion,
                    "confidence": round(record.confidence, 3),
                    "cause": cause.get("title", ""),
                    "evidence": record.notes[0] if record.notes else "",
                    "actions": "；".join(cause.get("actions", [])),
                    "mae": record.metrics.get("mae", ""),
                    "max_error": record.metrics.get("max_error", ""),
                    "error_ratio": record.metrics.get("error_ratio", ""),
                    "within_5": record.metrics.get("within_5", ""),
                    "within_10": record.metrics.get("within_10", ""),
                    "within_15": record.metrics.get("within_15", ""),
                }
            )
    segments = output_dir / "segment_diagnosis.csv"
    with segments.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["file", "start_s", "end_s", "samples", "mean_error", "max_error"],
        )
        writer.writeheader()
        for record in records:
            for segment in record.segments:
                writer.writerow({"file": record.file, **segment.__dict__})
    return [summary, detail, segments]


def write_markdown(records: Iterable[AnalysisRecord], output: Path) -> Path:
    records = list(records)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# PPG 数据分析报告", "", f"文件数：{len(records)}", ""]
    counts: Dict[str, int] = {}
    for record in records:
        counts[record.conclusion] = counts.get(record.conclusion, 0) + 1
    lines.extend(
        ["## 批次结论", "", "；".join(f"{key}: {value}" for key, value in counts.items()), ""]
    )
    lines.extend(
        [
            "## 整体准确度对比",
            "",
            "| 对比对象 | 场景 | 文件数 | 样本数 | MAE | 最大误差 | ±5 bpm | ±10 bpm | ±15 bpm |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in _accuracy_rows(records):
        if row["available"]:
            values = (
                f"{row['mae']:.2f}",
                f"{row['max_error']:.2f}",
                f"{row['within_5']:.1%}",
                f"{row['within_10']:.1%}",
                f"{row['within_15']:.1%}",
            )
            files = str(row["files"])
            samples = str(row["samples"])
        else:
            files, samples = "0", "-"
            values = ("未执行", "-", "-", "-", "-")
        lines.append(
            f"| {row['comparison']} | {row['scene']} | {files} | {samples} | "
            + " | ".join(values)
            + " |"
        )
    lines.extend(
        [
            "",
            "## 异常数据归类",
            "",
            "| 来源 | 具体原因 | 文件数 |",
            "|---|---|---:|",
        ]
    )
    cause_rows = _cause_counts(records)
    if cause_rows:
        for row in cause_rows:
            lines.append(f"| {row['category']} | {row['cause']} | {row['files']} |")
    else:
        lines.append("| - | 未发现异常数据 | 0 |")
    lines.append("")
    for record in records:
        lines.extend(
            [
                f"## {record.file}",
                "",
                f"- 场景：{record.scene}",
                f"- 结论：{record.conclusion}",
                f"- 置信度：{record.confidence:.0%}",
            ]
        )
        if record.cause:
            lines.append(f"- 可能原因：{record.cause.get('title', '')}")
        if record.notes:
            lines.append(f"- 证据：{record.notes[0]}")
        actions = (record.cause or {}).get("actions", [])
        if actions:
            lines.append(f"- 原始数据措施：{'；'.join(actions)}")
        if record.figure:
            rel = Path(record.figure).relative_to(output.parent).as_posix()
            lines.extend(["", f"![证据图]({rel})"])
        lines.append("")
    output.write_text("\n".join(lines), encoding="utf-8")
    return output


def _duplicate_slide(prs, source):
    return _add_slide_before_ending(prs, source.slide_layout)


def _add_slide_before_ending(prs, layout):
    slide = prs.slides.add_slide(layout)
    slide_id = prs.slides._sldIdLst[-1]
    prs.slides._sldIdLst.remove(slide_id)
    prs.slides._sldIdLst.insert(len(prs.slides._sldIdLst) - 1, slide_id)
    return slide


def _text_shapes(slide):
    return [shape for shape in slide.shapes if getattr(shape, "has_text_frame", False)]


def _set_text(shape, text: str) -> None:
    shape.text_frame.clear()
    paragraph = shape.text_frame.paragraphs[0]
    paragraph.text = text


def _replace_text_preserving_style(shape, text: str) -> None:
    paragraphs = shape.text_frame.paragraphs
    if paragraphs and paragraphs[0].runs:
        paragraphs[0].runs[0].text = text
        for run in paragraphs[0].runs[1:]:
            run.text = ""
        for paragraph in paragraphs[1:]:
            for run in paragraph.runs:
                run.text = ""
    else:
        _set_text(shape, text)


def _placeholder(slide, placeholder_type):
    return next(
        (
            shape
            for shape in slide.shapes
            if shape.is_placeholder and shape.placeholder_format.type == placeholder_type
        ),
        None,
    )


def _add_picture(slide, placeholder, image_path: str) -> None:
    from PIL import Image

    left, top, width, height = (
        placeholder.left,
        placeholder.top,
        placeholder.width,
        placeholder.height,
    )
    placeholder._element.getparent().remove(placeholder._element)
    with Image.open(image_path) as image:
        image_ratio = image.width / image.height
    area_ratio = width / height
    if image_ratio >= area_ratio:
        picture = slide.shapes.add_picture(image_path, left, top, width=width)
        picture.top = top + (height - picture.height) // 2
    else:
        picture = slide.shapes.add_picture(image_path, left, top, height=height)
        picture.left = left + (width - picture.width) // 2


def _populate_content(slide, title_text: str, body_text: str, figure: str = "") -> None:
    from pptx.enum.shapes import PP_PLACEHOLDER

    title = _placeholder(slide, PP_PLACEHOLDER.TITLE)
    body = _placeholder(slide, PP_PLACEHOLDER.BODY)
    content = _placeholder(slide, PP_PLACEHOLDER.OBJECT)
    if title:
        _set_text(title, title_text)
    if body:
        _set_text(body, body_text)
    if content:
        if figure:
            _add_picture(slide, content, figure)
        else:
            content._element.getparent().remove(content._element)


def _populate_summary(slide, records: List[AnalysisRecord]) -> str:
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import PP_PLACEHOLDER
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Inches, Pt

    causes = _cause_counts(records)
    body_lines = [f"{row['category']}：{row['cause']}（{row['files']}）" for row in causes] or [
        "未发现异常数据"
    ]
    title = _placeholder(slide, PP_PLACEHOLDER.TITLE)
    body = _placeholder(slide, PP_PLACEHOLDER.BODY)
    content = _placeholder(slide, PP_PLACEHOLDER.OBJECT)
    if title:
        _set_text(title, "批次分析结论")
    if body:
        _set_text(body, "异常数据归类\n" + "\n".join(body_lines))
    if content:
        left, top, width = content.left, content.top, content.width
        content._element.getparent().remove(content._element)
        row_height = Inches(0.42)
        cause_rows = causes or [{"category": "-", "cause": "未发现异常数据", "files": 0}]
        table_height = row_height * (len(cause_rows) + 1)
        table = slide.shapes.add_table(len(cause_rows) + 1, 3, left, top, width, table_height).table
        column_ratios = (0.22, 0.63, 0.15)
        for column, ratio in zip(table.columns, column_ratios):
            column.width = int(width * ratio)
        for row in table.rows:
            row.height = row_height
        headers = ["来源", "具体原因", "文件数"]
        for column, header in enumerate(headers):
            cell = table.cell(0, column)
            cell.text = header
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.margin_left = Inches(0.04)
            cell.margin_right = Inches(0.04)
            cell.margin_top = Inches(0.02)
            cell.margin_bottom = Inches(0.02)
            cell.fill.solid()
            cell.fill.fore_color.rgb = RGBColor(13, 110, 253)
            for paragraph in cell.text_frame.paragraphs:
                paragraph.alignment = PP_ALIGN.CENTER
                for run in paragraph.runs:
                    run.font.color.rgb = RGBColor(255, 255, 255)
                    run.font.bold = True
                    run.font.size = Pt(11)
        for row_index, row in enumerate(cause_rows, 1):
            values = [row["category"], row["cause"], str(row["files"])]
            for column, value in enumerate(values):
                cell = table.cell(row_index, column)
                cell.text = value
                cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                cell.margin_left = Inches(0.04)
                cell.margin_right = Inches(0.04)
                cell.margin_top = Inches(0.02)
                cell.margin_bottom = Inches(0.02)
                if row_index % 2 == 0:
                    cell.fill.solid()
                    cell.fill.fore_color.rgb = RGBColor(238, 246, 255)
                for paragraph in cell.text_frame.paragraphs:
                    paragraph.alignment = PP_ALIGN.CENTER
                    for run in paragraph.runs:
                        run.font.name = "微软雅黑"
                        run.font.size = Pt(11)
    return "\n".join(body_lines)


def _populate_accuracy(slide, records: List[AnalysisRecord]) -> None:
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import PP_PLACEHOLDER
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Inches, Pt

    title = _placeholder(slide, PP_PLACEHOLDER.TITLE)
    content = _placeholder(slide, PP_PLACEHOLDER.OBJECT)
    body = _placeholder(slide, PP_PLACEHOLDER.BODY)
    if title:
        _set_text(title, "整体准确度对比")
    if body:
        _set_text(body, "±5 / ±10 / ±15 bpm 为绝对误差不超过对应阈值的有效样本占比。")
    if not content:
        return
    rows = _accuracy_rows(records)
    left, top, width = content.left, content.top, content.width
    content._element.getparent().remove(content._element)
    row_height = Inches(0.46)
    table = slide.shapes.add_table(
        len(rows) + 1,
        9,
        left,
        top,
        width,
        row_height * (len(rows) + 1),
    ).table
    column_ratios = (0.20, 0.11, 0.08, 0.10, 0.10, 0.11, 0.10, 0.10, 0.10)
    for column, ratio in zip(table.columns, column_ratios):
        column.width = int(width * ratio)
    for row in table.rows:
        row.height = row_height
    headers = [
        "对比对象",
        "场景",
        "文件数",
        "样本数",
        "MAE",
        "最大误差",
        "±5 bpm",
        "±10 bpm",
        "±15 bpm",
    ]
    for column, header in enumerate(headers):
        cell = table.cell(0, column)
        cell.text = header
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        cell.margin_left = Inches(0.03)
        cell.margin_right = Inches(0.03)
        cell.margin_top = Inches(0.02)
        cell.margin_bottom = Inches(0.02)
        cell.fill.solid()
        cell.fill.fore_color.rgb = RGBColor(13, 110, 253)
        for paragraph in cell.text_frame.paragraphs:
            paragraph.alignment = PP_ALIGN.CENTER
            for run in paragraph.runs:
                run.font.color.rgb = RGBColor(255, 255, 255)
                run.font.bold = True
                run.font.size = Pt(10)
    for row_index, row in enumerate(rows, 1):
        if row["available"]:
            values = [
                row["comparison"],
                row["scene"],
                str(row["files"]),
                str(row["samples"]),
                f"{row['mae']:.2f}",
                f"{row['max_error']:.2f}",
                f"{row['within_5']:.1%}",
                f"{row['within_10']:.1%}",
                f"{row['within_15']:.1%}",
            ]
        else:
            values = [row["comparison"], row["scene"], "0", "-", "未执行", "-", "-", "-", "-"]
        for column, value in enumerate(values):
            cell = table.cell(row_index, column)
            cell.text = value
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.margin_left = Inches(0.03)
            cell.margin_right = Inches(0.03)
            cell.margin_top = Inches(0.02)
            cell.margin_bottom = Inches(0.02)
            if row_index % 2 == 0:
                cell.fill.solid()
                cell.fill.fore_color.rgb = RGBColor(238, 246, 255)
            for paragraph in cell.text_frame.paragraphs:
                paragraph.alignment = PP_ALIGN.CENTER
                for run in paragraph.runs:
                    run.font.name = "微软雅黑"
                    run.font.size = Pt(10.5)


def write_ppt(records: Iterable[AnalysisRecord], output: Path) -> Path:
    try:
        from pptx import Presentation
        from pptx.enum.shapes import PP_PLACEHOLDER
    except ImportError as exc:
        raise RuntimeError("生成 PPT 需要安装 python-pptx") from exc
    template = Path(files("health_tools") / "templates" / "analysis_report.pptx")
    prs = Presentation(str(template))
    records = list(records)
    cover = prs.slides[0]
    content = prs.slides[1]
    ending = prs.slides[-1]
    for shape in _text_shapes(cover):
        if shape.is_placeholder and shape.placeholder_format.type == PP_PLACEHOLDER.TITLE:
            _set_text(shape, "PPG 数据分析报告")
        elif shape.is_placeholder:
            _set_text(shape, "原始数据、准确度与证据归因")
    for shape in _text_shapes(ending):
        if "THANK" in shape.text.upper():
            _replace_text_preserving_style(shape, "分析完成")
    counts: Dict[str, int] = {}
    for record in records:
        counts[record.conclusion] = counts.get(record.conclusion, 0) + 1
    summary_text = "\n".join(f"{name}：{count} 个文件" for name, count in counts.items())
    cause_summary = _populate_summary(content, records)
    accuracy_slide = _add_slide_before_ending(prs, prs.slide_layouts[5])
    _populate_accuracy(accuracy_slide, records)
    detail_records = [
        record
        for record in records
        if record.abnormal
        or record.focused
        or (record.conclusion == "证据不足" and bool(record.figure))
    ]
    for record in detail_records:
        slide = _duplicate_slide(prs, content)
        cause = (record.cause or {}).get("title", "无")
        action = "；".join((record.cause or {}).get("actions", [])) or "无"
        evidence = record.notes[0] if record.notes else "无"
        ppt_evidence = evidence.replace("；", "\n")
        body_text = (
            f"场景：{record.scene}\n结论：{record.conclusion}\n"
            f"置信度：{record.confidence:.0%}\n原因：{cause}\n"
            f"证据：{ppt_evidence}\n原始数据措施：{action}"
        )
        _populate_content(slide, record.file, body_text, record.figure or "")
    conclusion_slide = _duplicate_slide(prs, content)
    _populate_content(
        conclusion_slide,
        "综合结论",
        summary_text + "\n\n" + cause_summary + "\n\n算法原因仅说明可能机制，不包含算法优化方向。",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(output))
    return output
