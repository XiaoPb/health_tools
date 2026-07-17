from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from health_tools.api import AnalyzeRequest, RequestValidationError, run_analyze
from health_tools.api.context import ExecutionContext
from health_tools.api.models import BatchResult, ItemResult, ItemStatus, OfflineResult
from health_tools.api.analysis_operation import (
    _apply_check_results,
    _apply_evaluate_results,
    _escalate,
    _generate_psd_plots,
    _generate_raw_plots,
)
from health_tools.core.analysis.conditions import matches
from health_tools.core.analysis.diagnosis import diagnose
from health_tools.core.analysis.models import AnalysisRecord
from health_tools.core.analysis.psd import analyze_psd_directory
from health_tools.core.analysis.raw import analyze_raw_file
from health_tools.core.analysis.reporting import write_ppt
from health_tools.models.rules import AnalysisRule
from health_tools.rules.loader import RuleLoader


CUSTOM_RULE = """version: '1.0'
type: other
columns:
  reference: REF
  prediction: PRED
  timestamp: time
  ppg_patterns: ['^PPG$']
  acc: [ACCX, ACCY, ACCZ]
detectors: [integrity, raw_signal, reference, accuracy, motion, hr_psd]
sampling: {sample_rate: 10}
thresholds:
  missing_ratio: 0.01
  flat_ratio: 0.98
  saturation_ratio: 0.01
  baseline_drift_ratio: 2
  motion_rms: 0.1
  error: 5
  ref_min: 30
  ref_max: 220
  jump_per_second: 20
causes:
  - id: reference_invalid
    title: reference invalid
    origin: reference
    priority: 100
    when: {feature: reference_valid, op: eq, value: false}
  - id: algorithm_error
    title: algorithm output abnormal
    origin: algorithm
    priority: 50
    when: {feature: algorithm_abnormal, op: eq, value: true}
"""


def _write_csv(path: Path, error: float = 0.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 100
    time = np.arange(count) / 10
    frame = pd.DataFrame(
        {
            "time": time,
            "FRAME_ID": np.arange(count),
            "ACCX": np.sin(time) * 0.01,
            "ACCY": np.zeros(count),
            "ACCZ": np.ones(count),
            "PPG": 1000 + np.sin(2 * np.pi * time) * 50,
            "REF": np.full(count, 80.0),
            "PRED": np.full(count, 80.0 + error),
        }
    )
    frame.to_csv(path, index=False)


def test_structured_conditions_do_not_evaluate_expressions():
    features = {"value": 5, "flag": True}

    assert matches({"all": [{"feature": "value", "op": "ge", "value": 5}]}, features)
    assert not matches({"feature": "__import__('os')", "op": "eq", "value": True}, features)


def test_algorithm_cause_requires_clean_raw_and_valid_reference():
    rule = AnalysisRule(
        type="other",
        causes=[
            {
                "id": "algorithm",
                "title": "algorithm abnormal",
                "origin": "algorithm",
                "priority": 1,
                "when": {"feature": "algorithm_abnormal", "op": "eq", "value": True},
            }
        ],
    )

    blocked = diagnose(
        {"raw_valid": False, "reference_valid": True, "algorithm_abnormal": True}, rule
    )
    confirmed = diagnose(
        {"raw_valid": True, "reference_valid": True, "algorithm_abnormal": True}, rule
    )

    assert blocked["conclusion"] == "证据不足"
    assert confirmed["conclusion"] == "算法性能极限"
    assert confirmed["actions"] == []


def test_run_analyze_generates_structured_and_markdown_reports(tmp_path: Path):
    source = tmp_path / "input.csv"
    rule = tmp_path / "analysis" / "custom.yaml"
    rule.parent.mkdir()
    rule.write_text(CUSTOM_RULE, encoding="utf-8")
    _write_csv(source)

    result = run_analyze(
        AnalyzeRequest(
            source,
            tmp_path / "out",
            analysis_type="other",
            rule_file=str(rule),
            report="markdown",
            allow_offline=False,
        )
    )

    assert result.summary_path and result.summary_path.exists()
    file_detail = tmp_path / "out" / "file_diagnosis.csv"
    assert file_detail.exists()
    assert {"within_5", "within_10", "within_15"}.issubset(pd.read_csv(file_detail).columns)
    assert (tmp_path / "out" / "segment_diagnosis.csv").exists()
    report = (tmp_path / "out" / "analysis_report.md").read_text(encoding="utf-8")
    assert "未发现异常" in report
    assert "整体准确度对比" in report
    assert "Online vs Polar" in report
    assert "Offline vs Polar" in report
    assert "±5 bpm" in report
    assert "±10 bpm" in report
    assert "±15 bpm" in report
    assert "异常数据归类" in report
    assert "算法优化" not in report


@pytest.mark.parametrize(
    ("status", "expected_conclusion"),
    [("FAIL", "原始数据问题"), ("WARNING", "未发现异常")],
)
def test_check_report_changes_diagnosis_only_for_failures(
    tmp_path: Path, status: str, expected_conclusion: str
):
    report = tmp_path / "check_report.csv"
    pd.DataFrame(
        [
            {
                "文件名": "sample.csv",
                "文件相对路径": "dynamic/sample.csv",
                "总异常(结果)": "FAIL" if status == "FAIL" else "PASS",
                "帧完整性(结果)": status,
            }
        ]
    ).to_csv(report, index=False, encoding="utf-8-sig")
    record = AnalysisRecord(
        file="dynamic/sample.csv",
        source=str(tmp_path / "sample.csv"),
        analysis_type="hr",
        features={
            "data_complete": True,
            "raw_valid": True,
            "reference_valid": True,
            "algorithm_abnormal": False,
        },
    )

    _apply_check_results([record], report, RuleLoader.load_analysis_rule("analysis_hr.yaml"))

    assert record.conclusion == expected_conclusion
    assert record.features["check_failures"] == (["帧完整性"] if status == "FAIL" else [])


def test_acc_check_evidence_includes_description_and_positions(tmp_path: Path):
    report = tmp_path / "check_report.csv"
    pd.DataFrame(
        [
            {
                "文件名": "sample.csv",
                "文件相对路径": "sample.csv",
                "总异常(结果)": "FAIL",
                "ACC异常(结果)": "FAIL",
                "ACC异常(说明)": "检测到ACC异常帧 16/100 (16.0%)",
                "ACC静止XYZ次数": 16,
                "ACC静止XYZ最长帧": 11,
                "ACC静止XYZ前10帧": "40,52,61,70",
            }
        ]
    ).to_csv(report, index=False, encoding="utf-8-sig")
    record = AnalysisRecord(
        file="sample.csv",
        source=str(tmp_path / "sample.csv"),
        analysis_type="hr",
        features={
            "data_complete": True,
            "raw_valid": True,
            "reference_valid": True,
            "algorithm_abnormal": False,
        },
    )

    _apply_check_results([record], report, RuleLoader.load_analysis_rule("analysis_hr.yaml"))
    evaluate = tmp_path / "file_details.csv"
    pd.DataFrame([{"file": "sample.csv", "mae": 3.0, "samples": 100}]).to_csv(evaluate, index=False)
    _apply_evaluate_results([record], evaluate, RuleLoader.load_analysis_rule("analysis_hr.yaml"))

    assert record.cause and record.cause["id"] == "acc_invalid"
    assert record.cause["title"] == "check 检测到 ACC 静止异常"
    assert "检测到ACC异常帧 16/100" in record.notes[0]
    assert "静止最长连续帧=11" in record.notes[0]
    assert "静止异常帧位置(前10)=40，52，61，70" in record.notes[0]


def test_spo2_raw_evidence_uses_plot_ac(monkeypatch, tmp_path: Path):
    source = tmp_path / "sample.csv"
    source.write_text("value\n1\n", encoding="utf-8")
    image = tmp_path / "ac.png"
    image.write_bytes(b"png")
    requests = []

    def fake_run_plot(request, *, context=None):
        requests.append(request)
        return BatchResult(
            "plot",
            (ItemResult(ItemStatus.OK, str(source), str(image)),),
            (image,),
        )

    monkeypatch.setattr("health_tools.api.file_operations.run_plot", fake_run_plot)
    record = AnalysisRecord(
        file="sample.csv",
        source=str(source),
        analysis_type="spo2",
        focused=True,
        features={"ppg_columns": ["Ipd0", "Ipd1"], "sample_rate": 25},
    )

    _generate_raw_plots(
        AnalyzeRequest(source, tmp_path / "out", analysis_type="spo2"),
        [record],
        "gh3036",
        tmp_path / "figures",
        RuleLoader.load_analysis_rule("analysis_spo2.yaml"),
        ExecutionContext(),
    )

    assert requests[0].plot_type == "ac"
    assert requests[0].channels == "Ipd0,Ipd1"
    assert record.figure == str(image)


def test_spo2_rejects_excessive_motion_even_when_accuracy_is_normal(tmp_path: Path):
    source = tmp_path / "spo2.csv"
    count = 100
    time = np.arange(count) / 25
    pd.DataFrame(
        {
            "TimeStamp": time,
            "FRAME_ID": np.arange(count),
            "ACCX": np.sin(2 * np.pi * time * 2) * 2,
            "ACCY": np.zeros(count),
            "ACCZ": np.ones(count),
            "Ipd0": 1000 + np.sin(2 * np.pi * time) * 50,
            "Ipd1": 900 + np.sin(2 * np.pi * time) * 45,
            "REF_RESULT5": np.full(count, 98.0),
            "ALGO_RESULT5": np.full(count, 98.0),
        }
    ).to_csv(source, index=False)
    rule = RuleLoader.load_analysis_rule("analysis_spo2.yaml")

    result, _, _ = analyze_raw_file(source, rule, "spo2")
    decision = diagnose({**result["features"], **result["metrics"]}, rule)

    assert result["features"]["motion_excessive"] is True
    assert decision["cause"]["id"] == "motion_excessive"
    assert decision["conclusion"] == "原始数据问题"
    assert "静止" in decision["cause"]["title"]


def test_dynamic_scene_does_not_use_pi(tmp_path: Path):
    source = tmp_path / "sample.csv"
    _write_csv(source)
    rule = AnalysisRule(
        columns={
            "reference": "REF",
            "prediction": "PRED",
            "timestamp": "time",
            "ppg_patterns": ["^PPG$"],
            "acc": ["ACCX", "ACCY", "ACCZ"],
        },
        sampling={"sample_rate": 10},
        thresholds={"pi_low": 0.5},
    )

    static, _, _ = analyze_raw_file(
        source,
        rule,
        "hr",
        ref_column="REF",
        pred_column="PRED",
        timestamp_column="time",
        scene_override="static",
    )
    dynamic, _, _ = analyze_raw_file(
        source,
        rule,
        "hr",
        ref_column="REF",
        pred_column="PRED",
        timestamp_column="time",
        scene_override="dynamic",
    )

    assert static["features"]["pi"] is not None
    assert dynamic["features"]["pi"] is None
    assert dynamic["features"]["pi_low"] is False


def test_spo2_offline_directory_does_not_enable_hr_psd(tmp_path: Path):
    source = tmp_path / "offline"
    source.mkdir()
    (source / "sample_result.vshb").write_text(
        "second,polar,algo_hr,comp_hr,fw_hr\n1,98,98,0,98\n",
        encoding="utf-8",
    )

    with pytest.raises(RequestValidationError, match="未启用 hr_psd"):
        run_analyze(
            AnalyzeRequest(
                source,
                tmp_path / "out",
                analysis_type="spo2",
                report="markdown",
                allow_offline=False,
            )
        )


def test_psd_evidence_is_generated_by_plot_command(monkeypatch, tmp_path: Path):
    source = tmp_path / "offline"
    source.mkdir()
    (source / "sample_result.vshb").write_text(
        "second,polar,algo_hr,comp_hr,fw_hr\n1,100,100,0,100\n",
        encoding="utf-8",
    )
    image = tmp_path / "sample.png"
    image.write_bytes(b"png")
    requests = []

    def fake_run_plot(request, *, context=None):
        requests.append(request)
        return BatchResult(
            "plot",
            (ItemResult(ItemStatus.OK, str(source), str(image)),),
            (image,),
        )

    monkeypatch.setattr("health_tools.api.file_operations.run_plot", fake_run_plot)
    record = AnalysisRecord(
        file="sample.csv",
        source=str(source / "sample_result.vshb"),
        analysis_type="hr",
        psd={"available": True},
        conclusion="证据不足",
    )

    _generate_psd_plots(source, [record], tmp_path / "figures", ExecutionContext())

    assert requests[0].plot_type == "psd"
    assert record.figure == str(image)


def test_evidence_insufficient_offline_result_still_links_psd_plot(monkeypatch, tmp_path: Path):
    source = tmp_path / "offline"
    source.mkdir()
    (source / "sample_result.vshb").write_text(
        "second,polar,algo_hr,comp_hr,fw_hr\n1,100,100,0,100\n",
        encoding="utf-8",
    )
    rule = tmp_path / "analysis" / "custom.yaml"
    rule.parent.mkdir()
    rule.write_text(CUSTOM_RULE, encoding="utf-8")
    image = tmp_path / "out" / "figures" / "psd" / "sample.png"
    requests = []

    def fake_run_plot(request, *, context=None):
        requests.append(request)
        image.parent.mkdir(parents=True, exist_ok=True)
        image.write_bytes(b"png")
        return BatchResult(
            "plot",
            (ItemResult(ItemStatus.OK, str(source), str(image)),),
            (image,),
        )

    monkeypatch.setattr("health_tools.api.file_operations.run_plot", fake_run_plot)

    result = run_analyze(
        AnalyzeRequest(
            source,
            tmp_path / "out",
            analysis_type="other",
            rule_file=str(rule),
            report="markdown",
            allow_offline=False,
        )
    )

    report = result.reports[0].read_text(encoding="utf-8")
    assert result.conclusion_counts["证据不足"] == 1
    assert requests[0].plot_type == "psd"
    assert "figures/psd/sample.png" in report


@pytest.mark.parametrize("version", [None, "specified-version"])
def test_offline_escalation_uses_copy_and_requested_version(
    monkeypatch, tmp_path: Path, version: str
):
    root = tmp_path / "input"
    source = root / "dynamic" / "sample.csv"
    source.parent.mkdir(parents=True)
    source.write_text("value\n1\n", encoding="utf-8")
    requests = []

    def fake_run_offline(request, *, context=None):
        requests.append(request)
        request.output_path.mkdir(parents=True, exist_ok=True)
        return OfflineResult(BatchResult("offline"), output_dir=request.output_path)

    monkeypatch.setattr("health_tools.api.offline_operation.run_offline", fake_run_offline)
    record = AnalysisRecord(
        file="dynamic/sample.csv",
        source=str(source),
        analysis_type="hr",
        focused=True,
    )
    request = AnalyzeRequest(
        root,
        tmp_path / "out",
        offline_version=version,
    )

    escalated = _escalate(
        request,
        [record],
        root,
        "gh3036",
        RuleLoader.load_analysis_rule("analysis_hr.yaml"),
        tmp_path / "stages",
        ExecutionContext(),
    )

    copied = tmp_path / "stages" / "offline_input" / "dynamic" / "sample.csv"
    assert escalated == [source]
    assert copied.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    assert source.exists()
    assert requests[0].input_path == tmp_path / "stages" / "offline_input"
    assert requests[0].ver == version


def test_no_offline_records_reason_for_evidence_insufficient(tmp_path: Path):
    source = tmp_path / "sample.csv"
    source.write_text("value\n1\n", encoding="utf-8")
    record = AnalysisRecord(
        file="sample.csv",
        source=str(source),
        analysis_type="hr",
        conclusion="证据不足",
        notes=["缺少关键证据"],
    )

    escalated = _escalate(
        AnalyzeRequest(source, tmp_path / "out", allow_offline=False),
        [record],
        tmp_path,
        "gh3036",
        RuleLoader.load_analysis_rule("analysis_hr.yaml"),
        tmp_path / "stages",
        ExecutionContext(),
    )

    assert escalated == []
    assert record.notes[-1] == "已通过 --no-offline 禁用离线 PSD 分析"


def test_focus_supports_directory_glob_and_requires_match(tmp_path: Path):
    source = tmp_path / "data"
    _write_csv(source / "dynamic" / "selected.csv")
    _write_csv(source / "static" / "normal.csv")
    rule = tmp_path / "analysis" / "custom.yaml"
    rule.parent.mkdir()
    rule.write_text(CUSTOM_RULE, encoding="utf-8")

    result = run_analyze(
        AnalyzeRequest(
            source,
            tmp_path / "out",
            analysis_type="other",
            rule_file=str(rule),
            focus=("dynamic/*.csv",),
            report="markdown",
            allow_offline=False,
        )
    )

    focused = [item for item in result.batch.items if "selected.csv" in item.input]
    assert len(focused) == 1
    with pytest.raises(RequestValidationError, match="未匹配"):
        run_analyze(
            AnalyzeRequest(
                source,
                tmp_path / "other-out",
                analysis_type="other",
                rule_file=str(rule),
                focus=("missing/**/*.csv",),
                report="markdown",
                allow_offline=False,
            )
        )


def _write_locked_psd(result_dir: Path) -> None:
    result_dir.mkdir(parents=True)
    count = 20
    bins = 128
    peak = 50
    ppg = np.ones((count, bins)) * 0.1
    acc = np.ones((count, bins)) * 0.1
    ppg[:, peak] = 10
    acc[:, peak] = 10
    np.savetxt(result_dir / "sample0.prepsd", ppg, delimiter=",")
    np.savetxt(result_dir / "sample.accrmspsd", acc, delimiter=",")
    pd.DataFrame(
        {
            "second": np.arange(count),
            "polar": np.full(count, 100),
            "algo_hr": np.full(count, 130),
            "fw_hr": np.full(count, 130),
        }
    ).to_csv(result_dir / "sample_result.vshb", index=False)


def test_existing_psd_detects_frequency_lock(tmp_path: Path):
    source = tmp_path / "result"
    _write_locked_psd(source)

    result = run_analyze(
        AnalyzeRequest(source, tmp_path / "out", report="markdown", allow_offline=False)
    )

    assert result.conclusion_counts["算法性能极限"] == 1
    report = result.reports[0].read_text(encoding="utf-8")
    assert "Online vs Polar" in report
    assert "Offline vs Polar" in report
    assert "Comp vs Polar" not in report
    details = analyze_psd_directory(
        source, AnalysisRule(thresholds={"psd_clarity": 3, "psd_lock_hz": 0.2})
    )
    assert details["sample.csv"]["psd_locked"] is True


def test_existing_psd_includes_comp_comparison_when_nonzero(tmp_path: Path):
    source = tmp_path / "result"
    _write_locked_psd(source)
    vshb = source / "sample_result.vshb"
    frame = pd.read_csv(vshb)
    frame["comp_hr"] = 110
    frame.to_csv(vshb, index=False)

    result = run_analyze(
        AnalyzeRequest(source, tmp_path / "out", report="markdown", allow_offline=False)
    )

    report = result.reports[0].read_text(encoding="utf-8")
    assert "Comp vs Polar" in report


def test_vshb_accuracy_remains_available_when_psd_files_are_missing(tmp_path: Path):
    source = tmp_path / "result"
    source.mkdir()
    (source / "sample_result.vshb").write_text(
        "second,polar,algo_hr,comp_hr,fw_hr\n" "1,100,104,0,103\n" "2,100,112,0,108\n",
        encoding="utf-8",
    )

    details = analyze_psd_directory(source, RuleLoader.load_analysis_rule("analysis_hr.yaml"))

    sample = details["sample.csv"]
    assert sample["available"] is False
    assert sample["comparisons"]["online"]["mae"] == 5.5
    assert sample["comparisons"]["offline"]["mae"] == 8.0
    assert "comp" not in sample["comparisons"]


def test_ppt_report_uses_packaged_template(tmp_path: Path):
    pytest.importorskip("pptx")
    source = tmp_path / "input.csv"
    rule = tmp_path / "analysis" / "custom.yaml"
    rule.parent.mkdir()
    rule.write_text(CUSTOM_RULE, encoding="utf-8")
    _write_csv(source, error=10)

    result = run_analyze(
        AnalyzeRequest(
            source,
            tmp_path / "out",
            analysis_type="other",
            rule_file=str(rule),
            report="pptx",
            allow_offline=False,
        )
    )

    from pptx import Presentation

    deck = Presentation(str(result.reports[0]))
    assert len(deck.slides) >= 4
    text = "\n".join(
        shape.text for slide in deck.slides for shape in slide.shapes if hasattr(shape, "text")
    )
    table_text = "\n".join(
        cell.text
        for slide in deck.slides
        for shape in slide.shapes
        if shape.has_table
        for row in shape.table.rows
        for cell in row.cells
    )
    assert "PPG 数据分析报告" in text
    assert "整体" in table_text
    assert "Online vs Polar" in table_text
    assert "Offline vs Polar" in table_text
    assert "±5 bpm" in table_text
    assert "±10 bpm" in table_text
    assert "±15 bpm" in table_text
    assert "异常数据归类" in text
    assert "分析完成" in text


def test_ppt_summary_table_is_compact_and_centered(tmp_path: Path):
    pytest.importorskip("pptx")
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Inches

    output = write_ppt(
        [
            AnalysisRecord(
                file="sample.csv",
                source="sample.csv",
                analysis_type="hr",
                scene="dynamic",
                metrics={"samples": 100, "mae": 3.2, "max_error": 12, "error_ratio": 0.1},
                conclusion="未发现异常",
            )
        ],
        tmp_path / "report.pptx",
    )

    from pptx import Presentation

    deck = Presentation(str(output))
    tables = [
        shape.table for slide in list(deck.slides)[1:3] for shape in slide.shapes if shape.has_table
    ]
    assert len(tables) == 2
    for table in tables:
        assert all(row.height <= Inches(0.5) for row in table.rows)
        for row in table.rows:
            for cell in row.cells:
                assert cell.vertical_anchor == MSO_ANCHOR.MIDDLE
                assert cell.text_frame.paragraphs[0].alignment == PP_ALIGN.CENTER


def test_ppt_includes_psd_page_for_evidence_insufficient(tmp_path: Path):
    pytest.importorskip("pptx")
    from PIL import Image
    from pptx import Presentation

    figure = tmp_path / "sample.png"
    Image.new("RGB", (320, 180), "white").save(figure)
    output = write_ppt(
        [
            AnalysisRecord(
                file="sample.csv",
                source="sample_result.vshb",
                analysis_type="hr",
                conclusion="证据不足",
                notes=["PSD 证据不足"],
                figure=str(figure),
            )
        ],
        tmp_path / "report.pptx",
    )

    deck = Presentation(str(output))
    assert any(shape.shape_type == 13 for slide in deck.slides for shape in slide.shapes)
    assert any(
        getattr(shape, "text", "") == "sample.csv"
        for slide in deck.slides
        for shape in slide.shapes
    )
