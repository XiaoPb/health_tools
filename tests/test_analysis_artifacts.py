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
