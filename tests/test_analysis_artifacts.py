from pathlib import Path

import pytest

from health_tools.core.analysis.artifacts import ArtifactAmbiguityError, ArtifactIndex


def test_index_matches_selected_csv_to_existing_png_by_relative_stem(tmp_path: Path):
    csv_file = tmp_path / "fail_category" / "dynamic" / "sample.csv"
    png_file = tmp_path / "run" / "dynamic" / "sample.png"
    csv_file.parent.mkdir(parents=True)
    png_file.parent.mkdir(parents=True)
    csv_file.write_text("A\n1\n", encoding="utf-8")
    png_file.write_bytes(b"png")
    index = ArtifactIndex.build([csv_file], [tmp_path / "run"])
    assert index.figure_for("dynamic/sample.csv") == png_file


def test_fallback_png_matching_preserves_relative_directory_for_duplicate_stems(tmp_path: Path):
    source = tmp_path / "data"
    first_csv = source / "a" / "same.csv"
    second_csv = source / "b" / "same.csv"
    first_csv.parent.mkdir(parents=True)
    second_csv.parent.mkdir(parents=True)
    first_csv.write_text("A\n1\n", encoding="utf-8")
    second_csv.write_text("A\n2\n", encoding="utf-8")

    figures = tmp_path / "figures"
    first_png = figures / "a" / "same_time.png"
    second_png = figures / "b" / "same_time.png"
    first_png.parent.mkdir(parents=True)
    second_png.parent.mkdir(parents=True)
    first_png.write_bytes(b"png")
    second_png.write_bytes(b"png")

    index = ArtifactIndex.build([first_csv, second_csv], [figures])

    assert index.figures_for("a/same.csv") == (first_png,)
    assert index.figures_for("b/same.csv") == (second_png,)


def test_index_ranks_time_before_psd_and_keeps_secondary(tmp_path: Path):
    csv_file = tmp_path / "sample.csv"
    csv_file.write_text("A\n1\n", encoding="utf-8")
    figure_dir = tmp_path / "figures"
    figure_dir.mkdir()
    for name in ("sample_psd.png", "sample_time.png", "sample_evidence.png"):
        (figure_dir / name).write_bytes(b"png")
    index = ArtifactIndex.build([csv_file], [figure_dir])
    assert index.figures_for("sample.csv")[0].name == "sample_time.png"
    assert len(index.figures_for("sample.csv")) == 3


def test_report_is_authoritative_and_keeps_missing_rows(tmp_path: Path):
    source = tmp_path / "data"
    csv_file = source / "a" / "one.csv"
    csv_file.parent.mkdir(parents=True)
    csv_file.write_text("Ipd0,Ipd1\n1,2\n", encoding="utf-8")
    report = source / "check_report.csv"
    import pandas as pd

    pd.DataFrame(
        {
            "文件相对路径": ["a/one.csv", "b/missing.csv"],
            "总异常(结果)": ["FAIL", "FAIL"],
        }
    ).to_csv(report, index=False, encoding="utf-8-sig")

    index = ArtifactIndex.build(source.rglob("*.csv"), check_report=report)

    assert list(index.items) == ["a/one.csv", "b/missing.csv"]
    assert index.items["a/one.csv"].status == "OK"
    assert index.items["a/one.csv"].csv_path == csv_file
    assert index.items["b/missing.csv"].status == "SKIP"
    assert index.items["b/missing.csv"].reason == "文件不存在"


def test_report_relative_path_wins_over_duplicate_file_names(tmp_path: Path):
    source = tmp_path / "data"
    first = source / "a" / "same.csv"
    second = source / "b" / "same.csv"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text("Ipd0,Ipd1\n1,2\n", encoding="utf-8")
    second.write_text("Ipd0,Ipd1\n3,4\n", encoding="utf-8")
    report = source / "check_report.csv"
    import pandas as pd

    pd.DataFrame(
        {
            "文件相对路径": ["b/same.csv"],
            "总异常(结果)": ["FAIL"],
        }
    ).to_csv(report, index=False, encoding="utf-8-sig")

    index = ArtifactIndex.build(source.rglob("*.csv"), check_report=report)

    assert list(index.items) == ["b/same.csv"]
    assert index.items["b/same.csv"].csv_path == second


def test_report_relative_csv_path_prefers_input_file_over_same_cwd_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "data"
    input_csv = source / "same.csv"
    input_csv.parent.mkdir(parents=True)
    input_csv.write_text("Ipd0,Ipd1\n1,2\n", encoding="utf-8")
    cwd_csv = tmp_path / "same.csv"
    cwd_csv.write_text("Ipd0,Ipd1\n9,9\n", encoding="utf-8")
    report = tmp_path / "reports" / "check_report.csv"
    report.parent.mkdir()
    import pandas as pd

    pd.DataFrame({"文件相对路径": ["same.csv"], "总异常(结果)": ["FAIL"]}).to_csv(
        report, index=False, encoding="utf-8-sig"
    )
    monkeypatch.chdir(tmp_path)

    index = ArtifactIndex.build([input_csv], check_report=report)

    assert index.items["same.csv"].csv_path == input_csv


def test_report_rejects_ambiguous_duplicate_file_name(tmp_path: Path):
    source = tmp_path / "data"
    first = source / "a" / "same.csv"
    second = source / "b" / "same.csv"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text("Ipd0,Ipd1\n1,2\n", encoding="utf-8")
    second.write_text("Ipd0,Ipd1\n3,4\n", encoding="utf-8")
    report = source / "check_report.csv"
    import pandas as pd

    pd.DataFrame(
        {
            "文件名": ["same.csv"],
            "总异常(结果)": ["FAIL"],
        }
    ).to_csv(report, index=False, encoding="utf-8-sig")

    with pytest.raises(ArtifactAmbiguityError, match="same.csv"):
        ArtifactIndex.build(source.rglob("*.csv"), check_report=report)


def test_item_for_uses_unique_stem_after_relative_and_file_name(tmp_path: Path):
    source = tmp_path / "data"
    csv_file = source / "a" / "sample.csv"
    csv_file.parent.mkdir(parents=True)
    csv_file.write_text("Ipd0,Ipd1\n1,2\n", encoding="utf-8")

    index = ArtifactIndex.build([csv_file])

    assert index.item_for("sample") == index.items["sample.csv"]


def test_item_for_rejects_ambiguous_unique_stem(tmp_path: Path):
    source = tmp_path / "data"
    first = source / "a" / "same.csv"
    second = source / "b" / "same.csv"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text("Ipd0,Ipd1\n1,2\n", encoding="utf-8")
    second.write_text("Ipd0,Ipd1\n3,4\n", encoding="utf-8")

    index = ArtifactIndex.build([first, second])

    with pytest.raises(ArtifactAmbiguityError, match="same"):
        index.item_for("same")
