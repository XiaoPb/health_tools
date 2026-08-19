from pathlib import Path

from health_tools.core.analysis.artifacts import ArtifactIndex


def test_index_matches_selected_csv_to_existing_png_by_relative_stem(tmp_path: Path):
    csv_file = tmp_path / "fail_category" / "dynamic" / "sample.csv"
    png_file = tmp_path / "run" / "dynamic" / "sample.png"
    csv_file.parent.mkdir(parents=True)
    png_file.parent.mkdir(parents=True)
    csv_file.write_text("A\n1\n", encoding="utf-8")
    png_file.write_bytes(b"png")
    index = ArtifactIndex.build([csv_file], [tmp_path / "run"])
    assert index.figure_for("dynamic/sample.csv") == png_file


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
