import csv
from pathlib import Path

from health_tools.api.analysis_operation import _build_classification_manifest, run_check_stage
from health_tools.api.models import AnalyzeRequest, CheckResult, BatchResult


def test_classification_manifest_copies_files_without_moving(tmp_path: Path):
    source = tmp_path / "input"
    source.mkdir()
    normal = source / "normal.csv"
    centered = source / "centered.csv"
    normal.write_text("normal", encoding="utf-8")
    centered.write_text("center", encoding="utf-8")
    report = source / "check_report.csv"
    with report.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["文件名", "总异常(结果)", "数据居中(结果)", "文件相对路径"])
        writer.writerow([normal.name, "PASS", "PASS", normal.name])
        writer.writerow([centered.name, "FAIL", "FAIL", centered.name])

    manifest, manifest_json, copied = _build_classification_manifest(report, tmp_path / "out")

    assert manifest.exists() and manifest_json.exists()
    assert normal.exists() and centered.exists()
    assert (tmp_path / "out" / "classified" / "normal" / normal.name).exists()
    assert (tmp_path / "out" / "classified" / "centered" / centered.name).exists()
    assert len(copied) == 2


def test_run_check_stage_uses_default_timestamp_baseline(tmp_path: Path, monkeypatch):
    captured = {}

    def fake_run_check(request, *, context=None):
        captured["request"] = request
        report = tmp_path / "check_report.csv"
        report.write_text("文件名\n", encoding="utf-8")
        return CheckResult(BatchResult("check"), report_path=report)

    monkeypatch.setattr("health_tools.api.check_operation.run_check", fake_run_check)
    request = AnalyzeRequest(input_path=tmp_path, output_path=tmp_path / "out")
    result = run_check_stage(request, tmp_path, "gh3036", tmp_path / "out", None)

    assert result is not None
    assert captured["request"].timestamp_column == "TimeStamp"
    assert captured["request"].timestamp_base_ms == 40.0
