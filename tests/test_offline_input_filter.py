"""离线跑库输入过滤测试。"""

import shutil
from pathlib import Path

import pytest

from health_tools.core.offline_input_filter import (
    OfflineInputFilterError,
    filter_offline_inputs,
    move_offline_input,
)
from health_tools.models.rules import ChipRule


@pytest.fixture
def chip_rule() -> ChipRule:
    return ChipRule(
        chip="test",
        csv={"info_row": 1, "header_row": 2, "data_start_row": 3, "delimiter": ","},
        columns=["TimeStamp", "FRAME_ID", "CH{0-1}"],
    )


@pytest.fixture
def ref_chip_rule() -> ChipRule:
    return ChipRule(
        chip="test-ref",
        csv={"info_row": 1, "header_row": 2, "data_start_row": 3, "delimiter": ","},
        columns=["TimeStamp", "FRAME_ID", "REF_RESULT{0-15}", "CH{0-1}"],
    )


def _write_csv(path: Path, header: str, info: str = "Version: test") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{info}\n{header}\n1,2,3,4\n", encoding="utf-8")


def _ref_header(ref_names=None):
    if ref_names is None:
        ref_names = [f"reference_{index}" for index in range(16)]
    return ",".join(["TimeStamp", "FRAME_ID", *ref_names, "CH0", "CH1"])


def test_filter_accepts_exact_header_and_utf8_bom(chip_rule, tmp_path):
    input_dir = tmp_path / "test1"
    _write_csv(input_dir / "sample.csv", "\ufeffTimeStamp,FRAME_ID,CH0,CH1")

    result = filter_offline_inputs(input_dir, chip_rule)

    assert result.scanned_count == 1
    assert result.accepted_count == 1
    assert result.moved_count == 0
    assert (input_dir / "sample.csv").exists()


def test_filter_accepts_any_nonempty_names_at_all_ref_positions(ref_chip_rule, tmp_path):
    input_dir = tmp_path / "ref_inputs"
    ref_names = [f"golden_{index}" for index in range(16)]
    source = input_dir / "nested" / "sample.csv"
    _write_csv(source, _ref_header(ref_names))

    result = filter_offline_inputs(input_dir, ref_chip_rule)

    assert result.scanned_count == 1
    assert result.accepted_count == 1
    assert result.moved_count == 0
    assert source.exists()


@pytest.mark.parametrize(
    "case, header",
    [
        (
            "ref_count_insufficient",
            _ref_header([f"golden_{index}" for index in range(15)]),
        ),
        (
            "ref_count_exceeded",
            _ref_header([f"golden_{index}" for index in range(17)]),
        ),
        (
            "ref_position_misplaced",
            ",".join(
                [
                    "TimeStamp",
                    *[f"golden_{index}" for index in range(8)],
                    "FRAME_ID",
                    *[f"golden_{index}" for index in range(8, 16)],
                    "CH0",
                    "CH1",
                ]
            ),
        ),
        (
            "empty_ref_name",
            _ref_header(["" if index == 7 else f"golden_{index}" for index in range(16)]),
        ),
        (
            "non_ref_column_mismatch",
            ",".join(
                ["timestamp", "FRAME_ID", *[f"golden_{index}" for index in range(16)], "CH0", "CH1"]
            ),
        ),
    ],
)
def test_filter_moves_invalid_ref_headers_with_reason(ref_chip_rule, tmp_path, case, header):
    input_dir = tmp_path / "ref_inputs"
    source = input_dir / "nested" / case / "sample.csv"
    _write_csv(source, header)

    result = filter_offline_inputs(input_dir, ref_chip_rule)

    target = tmp_path / "ref_inputs_mv" / "nested" / case / "sample.csv"
    assert result.accepted_count == 0
    assert result.moved_count == 1
    assert not source.exists()
    assert target.exists()
    assert result.moved_files[0].target == target
    assert result.moved_files[0].reason == "表头与芯片规则不一致"


def test_filter_moves_unclosed_header_quote_as_parse_failure(ref_chip_rule, tmp_path):
    input_dir = tmp_path / "ref_inputs"
    source = input_dir / "nested" / "broken.csv"
    _write_csv(source, '"TimeStamp,FRAME_ID,broken')

    result = filter_offline_inputs(input_dir, ref_chip_rule)

    target = tmp_path / "ref_inputs_mv" / "nested" / "broken.csv"
    assert result.accepted_count == 0
    assert result.moved_count == 1
    assert not source.exists()
    assert target.exists()
    assert result.moved_files[0].target == target
    assert result.moved_files[0].reason == "CSV表头解析失败"


@pytest.mark.parametrize(
    "header",
    [
        "TimeStamp,FRAME_ID,CH0",
        "TimeStamp,FRAME_ID,CH0,CH1,EXTRA",
        "FRAME_ID,TimeStamp,CH0,CH1",
        "timestamp,FRAME_ID,CH0,CH1",
        "TimeStamp, FRAME_ID,CH0,CH1",
    ],
)
def test_filter_moves_headers_that_are_not_exact(chip_rule, tmp_path, header):
    input_dir = tmp_path / "test1"
    source = input_dir / "lzh" / "sample" / "sample.CSV"
    _write_csv(source, header)

    result = filter_offline_inputs(input_dir, chip_rule)

    target = tmp_path / "test1_mv" / "lzh" / "sample" / "sample.CSV"
    assert result.accepted_count == 0
    assert result.moved_count == 1
    assert not source.exists()
    assert target.exists()
    assert result.moved_files[0].reason == "表头与芯片规则不一致"


def test_filter_moves_short_and_invalid_encoding_files(chip_rule, tmp_path):
    input_dir = tmp_path / "test1"
    input_dir.mkdir()
    (input_dir / "short.csv").write_text("Version: test\n", encoding="utf-8")
    (input_dir / "invalid.csv").write_bytes(b"Version: test\n\xff,FRAME_ID,CH0,CH1\n")

    result = filter_offline_inputs(input_dir, chip_rule)

    assert result.scanned_count == 2
    assert result.accepted_count == 0
    assert result.moved_count == 2
    assert {item.reason for item in result.moved_files} == {"文件行数不足", "文件编码错误"}


def test_filter_uses_unique_backup_name_without_overwriting(chip_rule, tmp_path):
    input_dir = tmp_path / "test1"
    source = input_dir / "sample.csv"
    _write_csv(source, "bad")
    backup = tmp_path / "test1_mv" / "sample.csv"
    backup.parent.mkdir()
    backup.write_text("old", encoding="utf-8")

    result = filter_offline_inputs(input_dir, chip_rule)

    assert backup.read_text(encoding="utf-8") == "old"
    assert (backup.parent / "sample_1.csv").exists()
    assert result.moved_files[0].target == backup.parent / "sample_1.csv"


def test_move_offline_input_preserves_relative_path_and_reason(tmp_path):
    input_dir = tmp_path / "test1"
    source = input_dir / "nested" / "sample.csv"
    _write_csv(source, "bad")

    moved = move_offline_input(source, input_dir, "表头错误")

    assert moved.source == source
    assert moved.target == tmp_path / "test1_mv" / "nested" / "sample.csv"
    assert moved.reason == "表头错误"
    assert not source.exists()
    assert moved.target.exists()


def test_move_offline_input_uses_unique_target(tmp_path):
    input_dir = tmp_path / "test1"
    source = input_dir / "sample.csv"
    _write_csv(source, "bad")
    backup = tmp_path / "test1_mv" / "sample.csv"
    backup.parent.mkdir()
    backup.write_text("old", encoding="utf-8")

    moved = move_offline_input(source, input_dir, "表头错误")

    assert moved.target == backup.parent / "sample_1.csv"
    assert backup.read_text(encoding="utf-8") == "old"


def test_move_offline_input_wraps_os_error(monkeypatch, tmp_path):
    input_dir = tmp_path / "test1"
    source = input_dir / "bad.csv"
    _write_csv(source, "bad")

    def fail_move(src, dst):
        raise OSError("拒绝访问")

    monkeypatch.setattr(shutil, "move", fail_move)

    with pytest.raises(OfflineInputFilterError, match="移动不合规文件失败"):
        move_offline_input(source, input_dir, "表头错误")

    assert source.exists()


def test_filter_stops_when_move_fails(monkeypatch, chip_rule, tmp_path):
    input_dir = tmp_path / "test1"
    source = input_dir / "bad.csv"
    _write_csv(source, "bad")

    def fail_move(src, dst):
        raise OSError("拒绝访问")

    monkeypatch.setattr(shutil, "move", fail_move)

    with pytest.raises(OfflineInputFilterError, match="移动不合规文件失败"):
        filter_offline_inputs(input_dir, chip_rule)

    assert source.exists()
