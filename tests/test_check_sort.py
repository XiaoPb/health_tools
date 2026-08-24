"""check报告分拣功能测试。"""

import csv
from pathlib import Path

from click.testing import CliRunner

from health_tools.api.check_operation import (
    _discover_check_inputs,
    _is_check_report_csv,
    _sort_report,
)
from health_tools.commands.check import _sort_report_files


def _write_report(path: Path, rows: list[list[str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerows(rows)


def _read_csv(path: Path) -> list[list[str]]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.reader(f))


def test_check_report_header_detection_ignores_file_name(tmp_path):
    full = tmp_path / "renamed_full.csv"
    compact = tmp_path / "renamed_compact.csv"
    source = tmp_path / "source.csv"
    _write_report(
        full,
        [["文件名", "芯片", "总异常(结果)", "场景分类", "主要异常项", "文件相对路径"]],
    )
    _write_report(
        compact,
        [["文件名", "场景分类", "文件相对路径", "芯片", "检查项", "状态", "通道", "说明"]],
    )
    _write_report(source, [["文件名", "芯片", "TimeStamp", "FRAME_ID"]])

    assert _is_check_report_csv(full)
    assert _is_check_report_csv(compact)
    assert not _is_check_report_csv(source)
    assert _discover_check_inputs(tmp_path) == sorted([compact, full, source])


def test_sort_report_moves_files_and_keeps_relative_paths(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "ok.csv").write_text("ok", encoding="utf-8")
    (src / "sub").mkdir()
    (src / "sub" / "bad.csv").write_text("bad", encoding="utf-8")
    report = src / "check_report.csv"
    _write_report(
        report,
        [
            ["文件名", "芯片", "总异常(结果)", "文件相对路径"],
            ["ok.csv", "gh3220", "PASS", "ok.csv"],
            ["bad.csv", "gh3220", "FAIL", "sub/bad.csv"],
        ],
    )

    output = tmp_path / "sorted"
    stats = _sort_report_files(report, output)

    assert stats == {"normal": 1, "total_fail": 1, "skipped": 0}
    assert (output / "normal" / "ok.csv").read_text(encoding="utf-8") == "ok"
    assert (output / "abnormal" / "total_fail" / "sub" / "bad.csv").read_text(
        encoding="utf-8"
    ) == "bad"
    assert not (src / "ok.csv").exists()
    assert not (src / "sub" / "bad.csv").exists()

    normal_rows = _read_csv(output / "normal_files.csv")
    abnormal_rows = _read_csv(output / "abnormal_files.csv")
    assert normal_rows[1][0:2] == ["ok.csv", "ok.csv"]
    assert normal_rows[1][3] == "已移动"
    assert abnormal_rows[1][0:2] == ["bad.csv", "sub/bad.csv"]
    assert abnormal_rows[1][3] == "已移动"
    assert abnormal_rows[1][5] == "total_fail"


def test_sort_report_uses_priority_and_separates_acc_status(tmp_path):
    src = tmp_path / "src"
    paths = [
        "scene/frame.csv",
        "scene/range.csv",
        "scene/acc_fail.csv",
        "scene/acc_warning.csv",
        "scene/timestamp.csv",
        "scene/center.csv",
        "scene/reference.csv",
        "scene/frame_warning.csv",
        "scene/agc.csv",
        "scene/ipd.csv",
        "scene/normal.csv",
    ]
    for relative in paths:
        path = src / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")
    report = src / "check_report.csv"
    header = [
        "文件名",
        "总异常(结果)",
        "帧完整性(结果)",
        "数据范围(结果)",
        "ACC异常(结果)",
        "时间戳间隔(结果)",
        "数据居中(结果)",
        "AGC变化(结果)",
        "心率金标(结果)",
        "Ipd转换(结果)",
        "场景分类",
        "文件相对路径",
    ]
    rows = [
        [
            "frame.csv",
            "FAIL",
            "FAIL",
            "FAIL",
            "FAIL",
            "FAIL",
            "FAIL",
            "FAIL",
            "FAIL",
            "FAIL",
            "scene",
            paths[0],
        ],
        [
            "range.csv",
            "FAIL",
            "PASS",
            "FAIL",
            "FAIL",
            "FAIL",
            "FAIL",
            "FAIL",
            "FAIL",
            "FAIL",
            "scene",
            paths[1],
        ],
        [
            "acc_fail.csv",
            "FAIL",
            "PASS",
            "PASS",
            "FAIL",
            "FAIL",
            "FAIL",
            "FAIL",
            "FAIL",
            "FAIL",
            "scene",
            paths[2],
        ],
        [
            "acc_warning.csv",
            "PASS",
            "PASS",
            "PASS",
            "WARNING",
            "PASS",
            "WARNING",
            "PASS",
            "PASS",
            "PASS",
            "scene",
            paths[3],
        ],
        [
            "timestamp.csv",
            "FAIL",
            "PASS",
            "PASS",
            "PASS",
            "FAIL",
            "FAIL",
            "FAIL",
            "FAIL",
            "PASS",
            "scene",
            paths[4],
        ],
        [
            "center.csv",
            "FAIL",
            "PASS",
            "PASS",
            "PASS",
            "PASS",
            "FAIL",
            "PASS",
            "FAIL",
            "FAIL",
            "scene",
            paths[5],
        ],
        [
            "reference.csv",
            "FAIL",
            "PASS",
            "PASS",
            "PASS",
            "PASS",
            "PASS",
            "FAIL",
            "FAIL",
            "FAIL",
            "scene",
            paths[6],
        ],
        [
            "frame_warning.csv",
            "PASS",
            "WARNING",
            "PASS",
            "PASS",
            "PASS",
            "PASS",
            "PASS",
            "PASS",
            "PASS",
            "scene",
            paths[7],
        ],
        [
            "agc.csv",
            "FAIL",
            "PASS",
            "PASS",
            "PASS",
            "PASS",
            "PASS",
            "FAIL",
            "PASS",
            "FAIL",
            "scene",
            paths[8],
        ],
        [
            "ipd.csv",
            "FAIL",
            "PASS",
            "PASS",
            "PASS",
            "PASS",
            "PASS",
            "PASS",
            "PASS",
            "FAIL",
            "scene",
            paths[9],
        ],
        [
            "normal.csv",
            "PASS",
            "PASS",
            "WARNING",
            "PASS",
            "WARNING",
            "WARNING",
            "PASS",
            "PASS",
            "PASS",
            "scene",
            paths[10],
        ],
    ]
    _write_report(report, [header, *rows])

    stats = _sort_report_files(report, tmp_path / "sorted")

    assert stats == {
        "frame": 1,
        "range": 1,
        "acc_fail": 1,
        "acc_warning": 1,
        "timestamp": 1,
        "center": 1,
        "reference": 1,
        "frame_warning": 1,
        "agc": 1,
        "ipd": 1,
        "normal": 1,
        "skipped": 0,
    }
    expected = {
        "frame": paths[0],
        "range": paths[1],
        "acc_fail": paths[2],
        "acc_warning": paths[3],
        "timestamp": paths[4],
        "center": paths[5],
        "reference": paths[6],
        "frame_warning": paths[7],
        "agc": paths[8],
        "ipd": paths[9],
    }
    for category, relative in expected.items():
        assert (tmp_path / "sorted" / "abnormal" / category / relative).exists()
        assert (tmp_path / "sorted" / "abnormal_files.csv").exists()
        assert not (tmp_path / "sorted" / f"{category}_files.csv").exists()
    assert (tmp_path / "sorted" / "normal" / paths[10]).exists()
    assert (tmp_path / "sorted" / "normal_files.csv").exists()


def test_api_sort_report_uses_same_priority_rules(tmp_path):
    src = tmp_path / "src"
    source = src / "nested" / "sample.csv"
    source.parent.mkdir(parents=True)
    source.write_text("data", encoding="utf-8")
    report = src / "check_report.csv"
    _write_report(
        report,
        [
            [
                "文件名",
                "总异常(结果)",
                "帧完整性(结果)",
                "数据范围(结果)",
                "文件相对路径",
            ],
            ["sample.csv", "FAIL", "FAIL", "FAIL", "nested/sample.csv"],
        ],
    )

    stats = _sort_report(report, tmp_path / "sorted")

    assert stats == {"frame": 1, "skipped": 0}
    assert (tmp_path / "sorted/abnormal/frame/nested/sample.csv").exists()


def test_api_sort_report_accepts_custom_issue_priority(tmp_path):
    src = tmp_path / "src"
    source = src / "nested" / "sample.csv"
    source.parent.mkdir(parents=True)
    source.write_text("data", encoding="utf-8")
    report = src / "check_report.csv"
    _write_report(
        report,
        [
            ["文件名", "总异常(结果)", "帧完整性(结果)", "数据范围(结果)", "文件相对路径"],
            ["sample.csv", "FAIL", "FAIL", "FAIL", "nested/sample.csv"],
        ],
    )

    stats = _sort_report(report, tmp_path / "sorted", ("range_fail", "frame_fail"))

    assert stats == {"range": 1, "skipped": 0}
    assert (tmp_path / "sorted/abnormal/range/nested/sample.csv").exists()


def test_sort_report_places_reference_fail_before_ipd(tmp_path):
    src = tmp_path / "src"
    source = src / "nested" / "sample.csv"
    source.parent.mkdir(parents=True)
    source.write_text("data", encoding="utf-8")
    report = src / "check_report.csv"
    _write_report(
        report,
        [
            [
                "文件名",
                "总异常(结果)",
                "心率金标(结果)",
                "Ipd转换(结果)",
                "文件相对路径",
            ],
            ["sample.csv", "FAIL", "FAIL", "FAIL", "nested/sample.csv"],
        ],
    )

    stats = _sort_report(report, tmp_path / "sorted")

    assert stats == {"reference": 1, "skipped": 0}
    assert (tmp_path / "sorted/abnormal/reference/nested/sample.csv").exists()


def test_sort_report_uses_unknown_failed_check_name_as_category(tmp_path):
    src = tmp_path / "src"
    source = src / "nested" / "sample.csv"
    source.parent.mkdir(parents=True)
    source.write_text("data", encoding="utf-8")
    report = src / "check_report.csv"
    _write_report(
        report,
        [
            ["文件名", "总异常(结果)", "自定义质量(结果)", "文件相对路径"],
            ["sample.csv", "FAIL", "FAIL", "nested/sample.csv"],
        ],
    )

    stats = _sort_report(report, tmp_path / "sorted")

    assert stats == {"自定义质量": 1, "skipped": 0}
    assert (tmp_path / "sorted/abnormal/自定义质量/nested/sample.csv").exists()


def test_sort_report_fallback_order_does_not_depend_on_csv_column_order(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "sample.csv").write_text("data", encoding="utf-8")
    report = src / "check_report.csv"
    _write_report(
        report,
        [
            [
                "文件名",
                "总异常(结果)",
                "自定义乙(结果)",
                "Ipd转换(结果)",
                "自定义甲(结果)",
                "文件相对路径",
            ],
            ["sample.csv", "FAIL", "FAIL", "FAIL", "FAIL", "sample.csv"],
        ],
    )
    stats = _sort_report(report, tmp_path / "sorted")
    assert stats == {"ipd": 1, "skipped": 0}


def test_sort_report_sanitizes_unknown_check_category(tmp_path):
    src = tmp_path / "src"
    source = src / "sample.csv"
    src.mkdir()
    source.write_text("data", encoding="utf-8")
    report = src / "check_report.csv"
    _write_report(
        report,
        [
            ["文件名", "总异常(结果)", "../自定义:质量(结果)", "文件相对路径"],
            ["sample.csv", "FAIL", "FAIL", "sample.csv"],
        ],
    )

    stats = _sort_report(report, tmp_path / "sorted")

    assert stats == {"自定义_质量": 1, "skipped": 0}
    assert (tmp_path / "sorted/abnormal/自定义_质量/sample.csv").exists()


def test_sort_report_places_unclassified_total_failure_last(tmp_path):
    src = tmp_path / "src"
    source = src / "sample.csv"
    src.mkdir()
    source.write_text("data", encoding="utf-8")
    report = src / "check_report.csv"
    _write_report(
        report,
        [
            ["文件名", "总异常(结果)", "文件相对路径"],
            ["sample.csv", "FAIL", "sample.csv"],
        ],
    )

    stats = _sort_report(report, tmp_path / "sorted")

    assert stats == {"total_fail": 1, "skipped": 0}
    assert not source.exists()
    assert (tmp_path / "sorted/abnormal/total_fail/sample.csv").exists()


def test_sort_report_places_accuracy_marks_after_frame_warning_before_ipd(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    rows = [
        ("frame_warning.csv", "WARNING", "frame_warning"),
        ("online_low.csv", "PASS", "accuracy_online_low"),
        ("comp_low.csv", "PASS", "accuracy_comp_low"),
        ("online_gap.csv", "PASS", "accuracy_online_below_comp"),
        ("ipd.csv", "FAIL", ""),
    ]
    for name, _, _ in rows:
        (src / name).write_text(name, encoding="utf-8")
    report = src / "check_report.csv"
    header = [
        "文件名",
        "总异常(结果)",
        "帧完整性(结果)",
        "Ipd转换(结果)",
        "准确度标定分类",
        "准确度标定说明",
        "文件相对路径",
    ]
    report_rows = [
        [
            name,
            status,
            "WARNING" if category == "frame_warning" else "PASS",
            "FAIL" if category == "" else "PASS",
            category,
            category,
            name,
        ]
        for name, status, category in rows
    ]
    _write_report(report, [header, *report_rows])

    stats = _sort_report_files(report, tmp_path / "sorted")

    assert list(stats) == [
        "skipped",
        "frame_warning",
        "accuracy_online_low",
        "accuracy_comp_low",
        "accuracy_online_below_comp",
        "ipd",
    ]
    for name, _, category in rows:
        expected = "frame_warning" if category == "frame_warning" else category or "ipd"
        assert (tmp_path / "sorted" / "abnormal" / expected / name).exists()


def test_sort_report_skips_existing_target(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "ok.csv").write_text("new", encoding="utf-8")
    report = src / "check_report.csv"
    _write_report(
        report,
        [
            ["文件名", "芯片", "总异常(结果)", "文件相对路径"],
            ["ok.csv", "gh3220", "PASS", "ok.csv"],
        ],
    )
    output = tmp_path / "sorted"
    (output / "normal").mkdir(parents=True)
    (output / "normal" / "ok.csv").write_text("old", encoding="utf-8")

    stats = _sort_report_files(report, output)

    assert stats == {"skipped": 1}
    assert (src / "ok.csv").read_text(encoding="utf-8") == "new"
    assert (output / "normal" / "ok.csv").read_text(encoding="utf-8") == "old"
    rows = _read_csv(output / "normal_files.csv")
    assert rows[1][3] == "跳过"
    assert "目标文件已存在" in rows[1][4]


def test_sort_report_requires_relative_path_column(tmp_path):
    report = tmp_path / "check_report.csv"
    _write_report(report, [["文件名", "芯片", "总异常(结果)"], ["ok.csv", "gh3220", "PASS"]])

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        cwd_report = Path("check_report.csv")
        cwd_report.write_text(report.read_text(encoding="utf-8-sig"), encoding="utf-8-sig")
        result = runner.invoke(
            __import__("health_tools.commands.check", fromlist=["check_cmd"]).check_cmd,
            ["--sort", "--sort-output", "sorted"],
        )

    assert result.exit_code == 1
    assert "文件相对路径" in result.output


def test_sort_report_defaults_to_current_directory_report(tmp_path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path("ok.csv").write_text("ok", encoding="utf-8")
        _write_report(
            Path("check_report.csv"),
            [
                ["文件名", "芯片", "总异常(结果)", "文件相对路径"],
                ["ok.csv", "gh3220", "PASS", "ok.csv"],
            ],
        )
        result = runner.invoke(
            __import__("health_tools.commands.check", fromlist=["check_cmd"]).check_cmd,
            ["--sort", "--sort-output", "sorted"],
        )

        assert result.exit_code == 0
        assert Path("sorted/normal/ok.csv").read_text(encoding="utf-8") == "ok"


def test_check_skips_csv_when_columns_do_not_match_rule(tmp_path):
    csv_file = tmp_path / "bad.csv"
    csv_file.write_text("Version: GH3036\nfoo,bar\n1,2\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        __import__("health_tools.commands.check", fromlist=["check_cmd"]).check_cmd,
        ["-i", str(csv_file), "-c", "gh3036", "-v"],
    )

    assert result.exit_code == 0
    assert "跳过（列结构不符合规则" in result.output
    assert "检查报告已保存" in result.output
    assert (tmp_path / "check_report.csv").exists()


def test_check_help_center_ratio_default_is_five_percent():
    runner = CliRunner()
    result = runner.invoke(
        __import__("health_tools.commands.check", fromlist=["check_cmd"]).check_cmd,
        ["--help"],
    )

    assert result.exit_code == 0
    assert "数据居中异常允许比例 (%, 默认5)" in result.output
    assert "数据范围异常允许比例 (%, 默认1)" in result.output
    assert "帧丢失允许比例 (%, 默认1)" in result.output
    assert "Ipd超差允许比例 (%, 默认1)" in result.output
    assert "ACC异常帧允许比例 (%, 默认1)" in result.output
    assert "--acc-axis" in result.output
    assert "ACC单轴异常也计入结果" in result.output
