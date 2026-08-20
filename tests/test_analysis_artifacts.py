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


def test_fallback_png_matching_keeps_root_csv_scoped_to_root_figures(tmp_path: Path):
    source = tmp_path / "data"
    root_csv = source / "same.csv"
    nested_csv = source / "a" / "same.csv"
    nested_csv.parent.mkdir(parents=True)
    root_csv.write_text("A\n1\n", encoding="utf-8")
    nested_csv.write_text("A\n2\n", encoding="utf-8")

    figures = tmp_path / "figures"
    root_png = figures / "same_time.png"
    nested_png = figures / "a" / "same_time.png"
    nested_png.parent.mkdir(parents=True)
    root_png.write_bytes(b"png")
    nested_png.write_bytes(b"png")

    index = ArtifactIndex.build([root_csv, nested_csv], [figures])

    assert index.figures_for("same.csv") == (root_png,)
    assert index.figures_for("a/same.csv") == (nested_png,)


def test_parent_directory_fallback_requires_unique_csv_stem(tmp_path: Path):
    source = tmp_path / "data"
    root_csv = source / "same.csv"
    nested_csv = source / "data" / "same.csv"
    nested_csv.parent.mkdir(parents=True)
    root_csv.write_text("A\n1\n", encoding="utf-8")
    nested_csv.write_text("A\n2\n", encoding="utf-8")

    figures = tmp_path / "figures"
    nested_png = figures / "data" / "same_time.png"
    nested_png.parent.mkdir(parents=True)
    nested_png.write_bytes(b"png")

    index = ArtifactIndex.build([root_csv, nested_csv], [figures])

    assert index.figures_for("same.csv") == ()
    assert index.figures_for("data/same.csv") == (nested_png,)


def test_unique_csv_stem_uses_parent_fallback_when_root_has_unrelated_png(tmp_path: Path):
    csv_file = tmp_path / "input" / "dynamic" / "sample.csv"
    csv_file.parent.mkdir(parents=True)
    csv_file.write_text("A\n1\n", encoding="utf-8")

    figures = tmp_path / "figures"
    png_file = figures / "dynamic" / "sample_time.png"
    png_file.parent.mkdir(parents=True)
    png_file.write_bytes(b"png")
    (figures / "other_time.png").write_bytes(b"png")

    index = ArtifactIndex.build([csv_file], [figures])

    assert index.figures_for("sample.csv") == (png_file,)


def test_unique_csv_stems_use_flat_global_figure_fallback(tmp_path: Path):
    source = tmp_path / "data"
    first_csv = source / "a" / "one.csv"
    second_csv = source / "b" / "two.csv"
    first_csv.parent.mkdir(parents=True)
    second_csv.parent.mkdir(parents=True)
    first_csv.write_text("A\n1\n", encoding="utf-8")
    second_csv.write_text("A\n2\n", encoding="utf-8")

    figures = tmp_path / "figures"
    figures.mkdir()
    first_png = figures / "one_time.png"
    second_png = figures / "two_time.png"
    first_png.write_bytes(b"png")
    second_png.write_bytes(b"png")

    index = ArtifactIndex.build([first_csv, second_csv], [figures])

    assert index.figures_for("a/one.csv") == (first_png,)
    assert index.figures_for("b/two.csv") == (second_png,)


def test_unique_csv_stem_uses_global_fallback_for_deeper_figure_path(tmp_path: Path):
    csv_file = tmp_path / "outer" / "inner" / "one.csv"
    csv_file.parent.mkdir(parents=True)
    csv_file.write_text("A\n1\n", encoding="utf-8")

    figures = tmp_path / "figures"
    png_file = figures / "outer" / "inner" / "one_time.png"
    png_file.parent.mkdir(parents=True)
    png_file.write_bytes(b"png")

    index = ArtifactIndex.build([csv_file], [figures])

    assert index.figures_for("one.csv") == (png_file,)


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


def test_report_relative_csv_path_prefers_input_over_same_report_directory_name(
    tmp_path: Path,
):
    input_csv = tmp_path / "input" / "same.csv"
    input_csv.parent.mkdir()
    input_csv.write_text("Ipd0,Ipd1\n1,2\n", encoding="utf-8")
    report = tmp_path / "reports" / "check_report.csv"
    report.parent.mkdir()
    report_csv = report.parent / "same.csv"
    report_csv.write_text("Ipd0,Ipd1\n9,9\n", encoding="utf-8")
    import pandas as pd

    pd.DataFrame({"文件相对路径": ["same.csv"], "总异常(结果)": ["FAIL"]}).to_csv(
        report, index=False, encoding="utf-8-sig"
    )

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
