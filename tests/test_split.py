"""split 命令对不符合格式的 CSV 跳过而非中断测试。"""

from pathlib import Path

from health_tools.core.splitter import DataSplitter


def test_split_file_result_skips_missing_split_column(tmp_path: Path):
    bad = tmp_path / "bad.csv"
    bad.write_text("foo,bar\n1,2\n3,4\n", encoding="utf-8")

    result = DataSplitter().split_file_result(bad, tmp_path / "out", by_column="FRAME_ID")

    assert result.status == "SKIP"
    assert result.reason == "列缺失"
    assert "FRAME_ID" in result.detail


def test_split_by_time_missing_column_returns_skip(tmp_path: Path):
    bad = tmp_path / "bad.csv"
    bad.write_text("foo,bar\n1,2\n", encoding="utf-8")

    result = DataSplitter().split_file_result(
        bad, tmp_path / "out", by_time=60, time_column="TimeStamp"
    )

    assert result.status == "SKIP"
    assert result.reason == "列缺失"


def test_split_directory_skips_bad_file_and_processes_good_one(tmp_path: Path):
    from collections import Counter

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "good.csv").write_text("FRAME_ID,x\n0,1\n0,2\n1,3\n", encoding="utf-8")
    (input_dir / "bad.csv").write_text("foo,bar\n1,2\n", encoding="utf-8")
    output_dir = tmp_path / "output"

    splitter = DataSplitter()
    files = splitter.split_directory(input_dir, output_dir, by_column="FRAME_ID")

    statuses = Counter(result.status for result in splitter.last_collector.results)
    assert statuses["OK"] == 1
    assert statuses["SKIP"] == 1
    assert len(files) == 2  # good.csv 按 FRAME_ID 切成 2 段，bad.csv 被跳过


def test_run_split_directory_skips_bad_csv(tmp_path: Path):
    from health_tools.api import SplitRequest, run_split

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "good.csv").write_text("FRAME_ID,x\n0,1\n0,2\n1,3\n", encoding="utf-8")
    (input_dir / "bad.csv").write_text("foo,bar\n1,2\n", encoding="utf-8")

    result = run_split(SplitRequest(input_dir, tmp_path / "output", by_column="FRAME_ID"))

    assert result.ok_count == 1
    assert result.skip_count == 1
    assert len(result.artifacts) == 2
