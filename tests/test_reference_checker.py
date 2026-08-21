"""金标检查参数入口测试。"""

from pathlib import Path

import pandas as pd
from click.testing import CliRunner

from health_tools.api.check_operation import _compact_report_path, _save_compact_report
from health_tools.api.models import BatchResult, CheckRequest, CheckResult
from health_tools.commands.check import check_cmd
from health_tools.core.checker import DataChecker, FileCheckReport
from health_tools.models.rules import ChipRule


def _checker():
    return DataChecker(ChipRule(chip="gh3036", csv={}, columns=[]))


def test_compact_report_path_follows_full_report_name(tmp_path):
    assert _compact_report_path(tmp_path / "custom.csv") == tmp_path / "custom_compact.csv"
    assert _compact_report_path(tmp_path / "report") == tmp_path / "report_compact"


def test_reference_range_and_nonzero_ratio():
    result = _checker().check_reference_data(
        pd.DataFrame({"REF_HR": [30] * 70 + [0] * 30}), "REF_HR", "hr"
    )
    assert result.status == "PASS"
    result = _checker().check_reference_data(
        pd.DataFrame({"REF_HR": [29, 241] + [0] * 98}), "REF_HR", "hr"
    )
    assert result.status == "FAIL"


def test_reference_step_and_static_are_independent():
    result = _checker().check_reference_data(
        pd.DataFrame({"REF_SPO2": [80] * 125 + [81] * 10}),
        "REF_SPO2",
        "spo2",
    )
    assert result.status == "PASS"
    result = _checker().check_reference_data(
        pd.DataFrame({"REF_SPO2": [80] * 126 + [81] * 10}),
        "REF_SPO2",
        "spo2",
    )
    assert result.status == "FAIL"
    result = _checker().check_reference_data(
        pd.DataFrame({"REF_SPO2": [80, 89, 90]}), "REF_SPO2", "spo2"
    )
    assert result.status == "FAIL"


def test_reference_step_threshold_is_configurable():
    result = _checker().check_reference_data(
        pd.DataFrame({"REF_HR": [80, 86, 87]}), "REF_HR", "hr", step_threshold=5
    )
    assert result.status == "FAIL"
    result = _checker().check_reference_data(
        pd.DataFrame({"REF_HR": [80, 86, 87]}), "REF_HR", "hr", step_threshold=6
    )
    assert result.status == "PASS"


def test_reference_metrics_include_max_step_and_abnormal_times():
    result = _checker().check_reference_data(
        pd.DataFrame({"time": [1000, 2000, 3000], "REF_HR": [80, 100, 100]}),
        "REF_HR",
        "hr",
        step_threshold=15,
    )
    metric = result.channel_metrics["REF_HR"]
    assert metric["max_step_change"] == 20
    assert metric["max_step_time"] == "2000"
    assert "阶跃@2000" in metric["abnormal_times"]


def test_reference_abnormal_time_does_not_use_scientific_notation():
    result = _checker().check_reference_data(
        pd.DataFrame(
            {
                "time": [2441420, 2442420, 2443420, 2444420],
                "REF_HR": [80, 80, 80, 81],
            }
        ),
        "REF_HR",
        "hr",
        sample_rate=1,
        stale_seconds=1.5,
    )
    assert result.channel_metrics["REF_HR"]["abnormal_times"] == "静止@2441420"


def test_reference_static_duration_prefers_timestamp_span():
    frame = pd.DataFrame(
        {
            "time": [0, 250, 500, 750, 1000, 1250],
            "REF_HR": [80, 80, 80, 80, 80, 81],
        }
    )
    result = _checker().check_reference_data(frame, "REF_HR", "hr", sample_rate=1, stale_seconds=2)
    assert result.status == "PASS"
    assert result.channel_metrics["REF_HR"]["longest_static_seconds"] == 1.0


def test_compact_report_contains_reference_metrics(tmp_path):
    result = _checker().check_reference_data(
        pd.DataFrame({"REF_HR": [80] * 126 + [90]}),
        "REF_HR",
        "hr",
    )
    report = FileCheckReport(tmp_path / "sample.csv", "gh3036", results=[result])
    output = tmp_path / "check_report_compact.csv"
    _save_compact_report([report], output, tmp_path)
    text = output.read_text(encoding="utf-8-sig")
    assert "金标非零占比" in text
    assert "金标阶跃次数" in text
    assert "金标最长静止帧" in text


def test_check_request_keeps_reference_options():
    request = CheckRequest(
        input_path=Path("data.csv"),
        ref_hr_column="REF_HR",
        ref_spo2_column="REF_SPO2",
        ref_sample_rate=50,
        ref_stale_seconds=3,
        ref_step_threshold=6,
    )

    assert request.ref_hr_column == "REF_HR"
    assert request.ref_spo2_column == "REF_SPO2"
    assert request.ref_sample_rate == 50
    assert request.ref_stale_seconds == 3
    assert request.ref_step_threshold == 6


def test_check_request_reference_defaults():
    request = CheckRequest(input_path=Path("data.csv"))

    assert request.ref_hr_column is None
    assert request.ref_spo2_column is None
    assert request.ref_sample_rate == 25.0
    assert request.ref_stale_seconds == 5.0
    assert request.ref_step_threshold == 8.0


def test_check_help_lists_reference_options():
    result = CliRunner().invoke(check_cmd, ["--help"])

    assert result.exit_code == 0
    assert "--ref-hr-column" in result.output
    assert "--ref-spo2-column" in result.output
    assert "--ref-sample-rate" in result.output
    assert "--ref-stale-seconds" in result.output
    assert "--ref-step-threshold" in result.output


def test_check_rejects_invalid_reference_numeric_options():
    runner = CliRunner()

    for option, value in (
        ("--ref-sample-rate", "0"),
        ("--ref-stale-seconds", "0"),
        ("--ref-step-threshold", "-1"),
    ):
        result = runner.invoke(check_cmd, [option, value])
        assert result.exit_code == 2
        assert option in result.output


def test_run_check_rejects_invalid_reference_numeric_options(tmp_path):
    from health_tools.api import run_check
    from health_tools.api.errors import RequestValidationError

    for values in (
        {"ref_sample_rate": 0},
        {"ref_stale_seconds": 0},
        {"ref_step_threshold": -1},
    ):
        request = CheckRequest(input_path=tmp_path, **values)
        try:
            run_check(request)
        except RequestValidationError:
            continue
        raise AssertionError(f"expected validation error for {values}")


def test_check_passes_reference_options_to_request(monkeypatch, tmp_path):
    captured = {}

    def fake_run_check(request, *, context=None):
        captured["request"] = request
        return CheckResult(BatchResult("check"))

    monkeypatch.setattr("health_tools.api.run_check", fake_run_check)
    result = CliRunner().invoke(
        check_cmd,
        [
            "--sort",
            "--sort-output",
            str(tmp_path / "sorted"),
            "--ref-hr-column",
            "REF_HR",
            "--ref-spo2-column",
            "REF_SPO2",
            "--ref-sample-rate",
            "50",
            "--ref-stale-seconds",
            "3",
            "--ref-step-threshold",
            "6",
        ],
    )

    assert result.exit_code == 0, result.output
    request = captured["request"]
    assert request.ref_hr_column == "REF_HR"
    assert request.ref_spo2_column == "REF_SPO2"
    assert request.ref_sample_rate == 50.0
    assert request.ref_stale_seconds == 3.0
    assert request.ref_step_threshold == 6.0
