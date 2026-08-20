from pathlib import Path

import pytest

from health_tools.api import AnalyzeRequest, RequestValidationError
from health_tools.api.analysis_operation import _fast_report_records
from health_tools.core.analysis.reporting import write_ppt


def test_fast_report_matches_prefixed_pngs_and_writes_manifest(tmp_path: Path):
    check = tmp_path / "check_report.csv"
    check.write_text("文件名,结果\nscene/sample.csv,FAIL\n", encoding="utf-8-sig")
    figures = tmp_path / "figures"
    figures.mkdir()
    (figures / "0001_scene_sample.csv.png").write_bytes(b"png")
    (figures / "0002_scene_sample.csv_time.png").write_bytes(b"png")

    records, manifest = _fast_report_records(check, (figures,), tmp_path / "out")

    assert len(records) == 1
    assert records[0].file == "scene/sample.csv"
    assert records[0].figure and records[0].secondary_figure
    assert manifest.exists()
    assert "scene/sample.csv" in manifest.read_text(encoding="utf-8")


def test_fast_report_skips_ambiguous_basename(tmp_path: Path):
    check = tmp_path / "check_report.csv"
    check.write_text("file,result\nsample.csv,FAIL\n", encoding="utf-8")
    first = tmp_path / "one"
    second = tmp_path / "two"
    first.mkdir()
    second.mkdir()
    (first / "sample.csv.png").write_bytes(b"png")
    (second / "sample.csv.png").write_bytes(b"png")

    records, manifest = _fast_report_records(check, (first, second), tmp_path / "out")

    assert records[0].figure is None
    assert "歧义" in manifest.read_text(encoding="utf-8")


def test_fast_ppt_contains_only_check_body_and_images(tmp_path: Path):
    pytest.importorskip("pptx")
    from PIL import Image
    from pptx import Presentation

    primary = tmp_path / "sample.csv.png"
    secondary = tmp_path / "sample.csv_time.png"
    Image.new("RGB", (320, 180), "white").save(primary)
    Image.new("RGB", (320, 100), "gray").save(secondary)
    from health_tools.core.analysis.models import AnalysisRecord

    output = write_ppt(
        [
            AnalysisRecord(
                file="sample.csv",
                source="sample.csv",
                analysis_type="hr",
                figure=str(primary),
                secondary_figure=str(secondary),
                warnings=["check: FAIL"],
            )
        ],
        tmp_path / "report.pptx",
        fast_mode=True,
    )
    deck = Presentation(str(output))
    text = "\n".join(
        shape.text for slide in deck.slides for shape in slide.shapes if hasattr(shape, "text")
    )
    assert "sample.csv" in text
    assert "整体准确度对比" not in text
    detail = next(
        slide
        for slide in deck.slides
        if any(shape.text == "sample.csv" for shape in slide.shapes if hasattr(shape, "text"))
    )
    assert sum(1 for shape in detail.shapes if shape.shape_type == 13) == 2


def test_fast_request_requires_check_and_figures(tmp_path: Path):
    from health_tools.api.analysis_operation import _validate

    with pytest.raises(RequestValidationError, match="fast-report"):
        _validate(AnalyzeRequest(tmp_path, tmp_path / "out", fast_report=True))
