"""金标检查参数入口测试。"""

from pathlib import Path

from click.testing import CliRunner

from health_tools.api.models import BatchResult, CheckRequest, CheckResult
from health_tools.commands.check import check_cmd


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
