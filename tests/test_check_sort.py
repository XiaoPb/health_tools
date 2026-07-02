"""check报告分拣功能测试。"""

import csv
from pathlib import Path

from click.testing import CliRunner

from health_tools.commands.check import _sort_report_files


def _write_report(path: Path, rows: list[list[str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerows(rows)


def _read_csv(path: Path) -> list[list[str]]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.reader(f))


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

    assert stats == {"normal": 1, "abnormal": 1, "skipped": 0}
    assert (output / "normal" / "ok.csv").read_text(encoding="utf-8") == "ok"
    assert (output / "abnormal" / "sub" / "bad.csv").read_text(encoding="utf-8") == "bad"
    assert not (src / "ok.csv").exists()
    assert not (src / "sub" / "bad.csv").exists()

    normal_rows = _read_csv(output / "normal_files.csv")
    abnormal_rows = _read_csv(output / "abnormal_files.csv")
    assert normal_rows[1][0:2] == ["ok.csv", "ok.csv"]
    assert normal_rows[1][3] == "已移动"
    assert abnormal_rows[1][0:2] == ["bad.csv", "sub/bad.csv"]
    assert abnormal_rows[1][3] == "已移动"


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

    assert stats == {"normal": 0, "abnormal": 0, "skipped": 1}
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
    assert "无可检查的文件" in result.output
    assert not (tmp_path / "check_report.csv").exists()


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
