"""offline 命令构建测试。"""

import subprocess
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest
from click.testing import CliRunner
from matplotlib.axes import Axes
from PIL import Image

import health_tools.api.offline_operation as offline_api
from health_tools.cli import main
from health_tools.commands import offline as offline_command
from health_tools.core import offline, psd_plotter
from health_tools.core.vshb import read_vshb_result
from health_tools.rules.loader import RuleLoader


def test_offline_config_migrates_dot_to_default_tools_path(monkeypatch):
    monkeypatch.setattr(offline, "load_config", lambda: {"offline_tools_path": "."})

    config = offline.get_offline_config()

    assert config.tools_path == offline.OFFLINE_TOOLS_DIR


def test_offline_config_resolves_relative_path_from_config_dir(monkeypatch):
    monkeypatch.setattr(offline, "load_config", lambda: {"offline_tools_path": "tools"})

    config = offline.get_offline_config()

    assert config.tools_path == (offline.CONFIG_DIR / "tools").resolve()


def test_scan_versions_keeps_default_version_category_together(tmp_path):
    for category, version in (("exclusive", "v1"), ("medium", "v2")):
        executable = tmp_path / "gh3300" / category / version / offline.EXE_NAME
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"exe")

    result = offline.scan_versions(tmp_path)

    assert result["gh3300"]["default"] == "v2"
    assert result["gh3300"]["default_category"] == "medium"


def _make_runner(
    monkeypatch,
    tmp_path: Path,
    commands: dict,
    chip: str = "gh3036",
    hba_fs=None,
    scene_en=None,
    ch_num=None,
    ppg_offset=0,
    ppg_maps=(),
):
    exe_path = tmp_path / chip / "exclusive" / "v1" / offline.EXE_NAME
    exe_path.parent.mkdir(parents=True)
    exe_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(offline, "find_exe", lambda chip_name, version=None: exe_path)
    monkeypatch.setattr(
        offline,
        "get_offline_config",
        lambda: offline.OfflineConfig(tools_path=tmp_path, versions={}, commands=commands),
    )
    return offline.OfflineRunner(
        chip=chip,
        version="v1",
        hba_fs=hba_fs,
        scene_en=scene_en,
        ch_num=ch_num,
        ppg_offset=ppg_offset,
        ppg_maps=ppg_maps,
    )


def _write_valid_chip_csv(path: Path, chip: str = "gh3036") -> None:
    rule = RuleLoader.load_chip_rule(chip)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"Version: {chip.upper()}\n{rule.delimiter.join(rule.columns)}\n"
        f"{rule.delimiter.join(['0'] * len(rule.columns))}\n",
        encoding=rule.encoding,
    )


def test_build_command_uses_configured_cmd_arg_order(monkeypatch, tmp_path):
    runner = _make_runner(
        monkeypatch,
        tmp_path,
        {
            "gh3036": {
                "v1": {
                    "cmd_arg": [
                        "start_idx",
                        "end_idx",
                        "input_dir",
                        "output_dir",
                        "csv",
                        "hba_fs",
                        "scene_en",
                        "datatype",
                        "ch_num",
                        "accx",
                        "accy",
                        "accz",
                        "ppg_ch0",
                        "ppg_ch1",
                        "ppg_ch2",
                        "ppg_ch3",
                        "polar",
                        "mcu_out",
                        "comp_out",
                    ],
                    "cmd_default": {"start_idx": 0, "end_idx": -1, "datatype": 0},
                }
            }
        },
        hba_fs=25,
        scene_en=1,
        ch_num=2,
    )

    cmd = runner._build_command("in dir", "out dir")

    assert cmd.endswith('"in dir" "out dir" csv 25 1 0 2 2 3 4 5 6 7 8 45 61 46')


def test_build_command_maps_sparse_declared_ppg_channels_with_offset(monkeypatch, tmp_path):
    runner = _make_runner(
        monkeypatch,
        tmp_path,
        {
            "gh3036": {
                "v1": {
                    "cmd_arg": ["ppg_ch0", "ppg_ch4"],
                    "cmd_default": {},
                }
            }
        },
        ppg_offset=2,
    )

    cmd = runner._build_command("input", "output")

    assert cmd.endswith("7 11")
    assert runner.ppg_mapping == {"ppg_ch0": 7, "ppg_ch4": 11}


def test_build_command_supports_all_declared_ppg_channels(monkeypatch, tmp_path):
    cmd_arg = [f"ppg_ch{channel}" for channel in range(32)]
    runner = _make_runner(
        monkeypatch,
        tmp_path,
        {
            "gh3036": {
                "v1": {
                    "cmd_arg": cmd_arg,
                    "cmd_default": {},
                }
            }
        },
    )

    cmd = runner._build_command("input", "output")

    assert cmd.endswith(" ".join(str(index) for index in range(5, 37)))
    assert len(runner.ppg_mapping) == 32


def test_build_command_applies_named_and_zero_based_ppg_overrides(monkeypatch, tmp_path):
    runner = _make_runner(
        monkeypatch,
        tmp_path,
        {
            "gh3220": {
                "v1": {
                    "cmd_arg": ["{ppg_ch0}", "ppg_ch3"],
                    "cmd_default": {},
                }
            }
        },
        chip="gh3220",
        ppg_maps=("ppg_ch0=CH4", "ppg_ch3=12"),
    )

    cmd = runner._build_command("input", "output")

    assert cmd.endswith("9 12")
    assert runner.ppg_mapping == {"ppg_ch0": 9, "ppg_ch3": 12}


def test_repeated_ppg_override_uses_last_value(monkeypatch, tmp_path):
    runner = _make_runner(
        monkeypatch,
        tmp_path,
        {
            "gh3036": {
                "v1": {
                    "cmd_arg": ["ppg_ch0"],
                    "cmd_default": {},
                }
            }
        },
        ppg_maps=("ppg_ch0=Ipd4", "ppg_ch0=12"),
    )

    cmd = runner._build_command("input", "output")

    assert cmd.endswith("12")
    assert runner.ppg_mapping == {"ppg_ch0": 12}


def test_undeclared_ppg_override_is_ignored_without_parsing_value(monkeypatch, tmp_path):
    runner = _make_runner(
        monkeypatch,
        tmp_path,
        {
            "gh3036": {
                "v1": {
                    "cmd_arg": ["ppg_ch0"],
                    "cmd_default": {},
                }
            }
        },
        ppg_maps=("ppg_ch7=NOT_A_COLUMN",),
    )

    cmd = runner._build_command("input", "output")

    assert cmd.endswith("5")
    assert runner.ppg_warnings == ["ppg_ch7 未在 cmd_arg 中声明，设置未生效"]


@pytest.mark.parametrize(
    ("ppg_maps", "match"),
    [
        (("bad",), "格式"),
        (("ppg_ch32=1",), "0..31"),
        (("ppg_ch0=NOT_A_COLUMN",), "列名不存在"),
        (("ppg_ch0=-1",), "索引超出范围"),
        (("ppg_ch0=999",), "索引超出范围"),
    ],
)
def test_declared_ppg_override_rejects_invalid_value(monkeypatch, tmp_path, ppg_maps, match):
    runner = _make_runner(
        monkeypatch,
        tmp_path,
        {
            "gh3036": {
                "v1": {
                    "cmd_arg": ["ppg_ch0"],
                    "cmd_default": {},
                }
            }
        },
        ppg_maps=ppg_maps,
    )

    with pytest.raises(offline.OfflineConfigError, match=match):
        runner._build_command("input", "output")


def test_declared_ppg_channel_rejects_offset_beyond_detected_channels(monkeypatch, tmp_path):
    runner = _make_runner(
        monkeypatch,
        tmp_path,
        {
            "gh3036": {
                "v1": {
                    "cmd_arg": ["ppg_ch31"],
                    "cmd_default": {},
                }
            }
        },
        ppg_offset=1,
    )

    with pytest.raises(offline.OfflineConfigError, match="无法映射"):
        runner._build_command("input", "output")


def test_cmd_arg_rejects_ppg_channel_above_supported_range(monkeypatch, tmp_path):
    runner = _make_runner(
        monkeypatch,
        tmp_path,
        {
            "gh3036": {
                "v1": {
                    "cmd_arg": ["ppg_ch32"],
                    "cmd_default": {},
                }
            }
        },
    )

    with pytest.raises(offline.OfflineConfigError, match="0..31"):
        runner._build_command("input", "output")


def test_build_command_supports_cmd_arg_under_offline_versions(monkeypatch, tmp_path):
    exe_path = tmp_path / "gh3036" / "exclusive" / "v1" / offline.EXE_NAME
    exe_path.parent.mkdir(parents=True)
    exe_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(offline, "find_exe", lambda chip_name, version=None: exe_path)
    monkeypatch.setattr(
        offline,
        "get_offline_config",
        lambda: offline.OfflineConfig(
            tools_path=tmp_path,
            versions={
                "gh3036": {
                    "versions": {"exclusive": ["v1"]},
                    "default": "v1",
                    "cmd_arg": ["start_idx", "input_dir", "polar"],
                    "cmd_default": {"start_idx": 9},
                }
            },
            commands={},
        ),
    )

    runner = offline.OfflineRunner("gh3036")
    cmd = runner._build_command("input", "output")

    assert cmd.endswith("9 input 45")


def test_build_command_omits_args_not_listed_in_cmd_arg(monkeypatch, tmp_path):
    runner = _make_runner(
        monkeypatch,
        tmp_path,
        {
            "gh3036": {
                "v1": {
                    "cmd_arg": ["input_dir", "output_dir", "ch_num", "accx", "{ppg_ch0}"],
                    "cmd_default": {"start_idx": 0, "end_idx": -1, "datatype": 0},
                }
            }
        },
        ch_num=2,
    )

    cmd = runner._build_command("input", "output")

    assert cmd.endswith("input output 2 2 5")
    assert " -1 " not in cmd
    assert " csv " not in cmd


def test_cmd_default_applies_when_cli_option_is_not_set(monkeypatch, tmp_path):
    runner = _make_runner(
        monkeypatch,
        tmp_path,
        {
            "gh3036": {
                "v1": {
                    "cmd_arg": ["hba_fs", "scene_en", "ch_num", "datatype"],
                    "cmd_default": {"hba_fs": 100, "scene_en": 3, "ch_num": 4, "datatype": 9},
                }
            }
        },
    )

    cmd = runner._build_command("input", "output")

    assert cmd.endswith("100 3 4 9")


def test_missing_template_value_is_kept_as_literal(monkeypatch, tmp_path):
    runner = _make_runner(
        monkeypatch,
        tmp_path,
        {
            "gh3036": {
                "v1": {
                    "cmd_arg": ["input_dir", "datatype"],
                    "cmd_default": {},
                }
            }
        },
    )

    cmd = runner._build_command("input", "output")

    assert cmd.endswith("input datatype")


def test_cli_option_overrides_cmd_default(monkeypatch, tmp_path):
    runner = _make_runner(
        monkeypatch,
        tmp_path,
        {
            "gh3036": {
                "v1": {
                    "cmd_arg": ["hba_fs", "scene_en", "ch_num"],
                    "cmd_default": {"hba_fs": 100, "scene_en": 3, "ch_num": 4},
                }
            }
        },
        hba_fs=25,
        scene_en=1,
        ch_num=2,
    )

    cmd = runner._build_command("input", "output")

    assert cmd.endswith("25 1 2")


def test_local_cmd_setting_replaces_global_config(monkeypatch, tmp_path):
    runner = _make_runner(
        monkeypatch,
        tmp_path,
        {
            "gh3036": {
                "v1": {
                    "cmd_arg": ["input_dir", "output_dir"],
                    "cmd_default": {"scene_en": 9},
                }
            }
        },
    )
    (runner.tool_dir / "cmd_setting.yaml").write_text(
        "cmd_arg: [scene_en, input_dir]\ncmd_default:\n  scene_en: 3\n",
        encoding="utf-8",
    )

    cmd = runner._build_command("in dir", "out dir")

    assert cmd.endswith('3 "in dir"')
    assert "out dir" not in cmd


@pytest.mark.parametrize(
    "content",
    [
        "cmd_arg: [input_dir\n",
        "- input_dir\n",
        "cmd_default: {}\n",
        "cmd_arg: input_dir\n",
        "cmd_arg: [input_dir]\ncmd_default: []\n",
    ],
)
def test_invalid_local_cmd_setting_is_rejected(monkeypatch, tmp_path, content):
    runner = _make_runner(monkeypatch, tmp_path, {})
    (runner.tool_dir / "cmd_setting.yaml").write_text(content, encoding="utf-8")

    with pytest.raises(offline.OfflineConfigError, match="cmd_setting.yaml"):
        runner._build_command("input", "output")


def test_build_command_falls_back_to_builtin_format(monkeypatch, tmp_path):
    runner = _make_runner(
        monkeypatch,
        tmp_path,
        {},
        hba_fs=25,
        scene_en=1,
        ch_num=2,
        ppg_offset=4,
        ppg_maps=("ppg_ch0=CH4",),
    )

    cmd = runner._build_command("input", "output")

    assert cmd.endswith(' 0 -1 "input" "output" csv 25 1 2 2 3 4 5 6 7 8 45 61 46')
    assert runner.ppg_warnings == [
        "当前命令模板未声明 PPG 通道，--ppg-offset 未生效",
        "ppg_ch0 未在 cmd_arg 中声明，设置未生效",
    ]


def test_offline_run_result_success_on_zero_return(monkeypatch, tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    (input_dir / "sample.csv").write_text("x\n1\n", encoding="utf-8")
    runner = _make_runner(monkeypatch, tmp_path, {})

    def fake_run(cmd, shell, timeout):
        (output_dir / "000000_sample_result.vshb").write_text("1,2,3\n", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(offline.subprocess, "run", fake_run)

    result = runner.run(input_dir, output_dir, settle_timeout=0)

    assert result.success is True
    assert result.returncode == 0
    assert result.input_count == 1
    assert result.result_count == 1
    assert result.warning is None


def test_offline_run_result_fails_on_nonzero_without_results(monkeypatch, tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    (input_dir / "sample.csv").write_text("x\n1\n", encoding="utf-8")
    runner = _make_runner(monkeypatch, tmp_path, {})

    monkeypatch.setattr(
        offline.subprocess,
        "run",
        lambda cmd, shell, timeout: subprocess.CompletedProcess(cmd, 7),
    )

    result = runner.run(input_dir, output_dir, settle_timeout=0)

    assert result.success is False
    assert result.returncode == 7
    assert result.input_count == 1
    assert result.result_count == 0
    assert result.missing_count == 1
    assert result.error == "外部工具返回异常，且结果文件不完整"


def test_offline_run_result_warns_on_nonzero_with_complete_results(monkeypatch, tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    for name in ["a.csv", "b.csv"]:
        (input_dir / name).write_text("x\n1\n", encoding="utf-8")
    runner = _make_runner(monkeypatch, tmp_path, {})

    def fake_run(cmd, shell, timeout):
        (output_dir / "000000_a_result.vshb").write_text("1,2,3\n", encoding="utf-8")
        (output_dir / "000001_b_result.vshb").write_text("1,2,3\n", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 9)

    monkeypatch.setattr(offline.subprocess, "run", fake_run)

    result = runner.run(input_dir, output_dir, settle_timeout=0)

    assert result.success is True
    assert result.returncode == 9
    assert result.result_count == 2
    assert result.warning == "外部工具返回异常，但结果文件已生成完整"


def test_offline_run_result_reports_timeout(monkeypatch, tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    (input_dir / "sample.csv").write_text("x\n1\n", encoding="utf-8")
    runner = _make_runner(monkeypatch, tmp_path, {})

    def fake_run(cmd, shell, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr(offline.subprocess, "run", fake_run)

    result = runner.run(input_dir, output_dir, timeout=1, settle_timeout=0)

    assert result.success is False
    assert result.timed_out is True
    assert result.returncode is None
    assert result.error == "离线工具执行超时"


def test_offline_verbose_prints_run_diagnostics(monkeypatch, tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    _write_valid_chip_csv(input_dir / "sample.csv")
    exe_path = tmp_path / "gh3036" / "exclusive" / "v1" / offline.EXE_NAME
    exe_path.parent.mkdir(parents=True)
    exe_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(offline, "find_exe", lambda chip_name, version=None: exe_path)
    monkeypatch.setattr(
        offline,
        "get_offline_config",
        lambda: offline.OfflineConfig(
            tools_path=tmp_path,
            versions={"gh3036": {"versions": {"exclusive": ["v1"]}, "default": "v1"}},
            commands={},
        ),
    )

    def fake_run(cmd, shell, timeout):
        (output_dir / "v1" / "000000_sample_result.vshb").write_text("1,2,3\n", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(offline.subprocess, "run", fake_run)

    result = CliRunner().invoke(
        main,
        [
            "offline",
            "-i",
            str(input_dir),
            "-o",
            str(output_dir),
            "-c",
            "gh3036",
            "--no-plot",
            "--no-accuracy",
            "--verbose",
            "--settle-timeout",
            "0",
        ],
    )

    assert result.exit_code == 0
    assert "诊断:" in result.output
    assert "命令:" in result.output
    assert "返回码: 0" in result.output
    assert "输入CSV: 1" in result.output
    assert "结果VSHB: 1" in result.output


def test_offline_filters_once_before_multi_version_run(monkeypatch, tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _write_valid_chip_csv(input_dir / "sample.csv")
    exe_paths = {}
    for version in ["v1", "v2"]:
        exe_path = tmp_path / "gh3036" / "exclusive" / version / offline.EXE_NAME
        exe_path.parent.mkdir(parents=True)
        exe_path.write_text("", encoding="utf-8")
        exe_paths[version] = exe_path

    monkeypatch.setattr(
        offline_command,
        "_resolve_versions",
        lambda *args: ["v1", "v2"],
    )
    monkeypatch.setattr(
        offline_command,
        "_validate_version_exes",
        lambda *args: exe_paths,
    )
    filter_calls = []
    monkeypatch.setattr(
        offline_command,
        "_filter_input_files",
        lambda input_path, chip: filter_calls.append((input_path, chip)),
    )
    monkeypatch.setattr(offline_command, "_validate_local_cmd_configs", lambda exes: None)
    monkeypatch.setattr(
        offline_command,
        "_run_single_offline_version",
        lambda **kwargs: None,
    )

    class FakeRunner:
        ppg_warnings = []

        def __init__(self, chip, version=None, **kwargs):
            self.version = version

        def resolve_ppg_mapping(self):
            return {}

        def run(self, input_path, output_path, **kwargs):
            output_path.mkdir(parents=True, exist_ok=True)
            return offline.OfflineRunResult(success=True)

    monkeypatch.setattr(offline, "find_exe", lambda chip, version=None: exe_paths[version])
    monkeypatch.setattr(offline, "OfflineRunner", FakeRunner)
    monkeypatch.setattr(
        offline_api,
        "_filter_input_files",
        lambda input_path, chip: filter_calls.append((input_path, chip)),
    )
    monkeypatch.setattr(
        offline,
        "reorganize_output",
        lambda input_path, output_path, show_progress=False: output_path,
    )
    monkeypatch.setattr("health_tools.core.psd_plotter.PsdPlotter.plot", lambda *args, **kwargs: [])
    monkeypatch.setattr(offline, "calculate_offline_accuracy", lambda *args, **kwargs: None)

    result = CliRunner().invoke(
        main,
        ["offline", "-i", str(input_dir), "-c", "gh3036", "--versions", "v1,v2"],
    )

    assert result.exit_code == 0
    assert filter_calls == [(input_dir, "gh3036")]


def test_offline_no_run_skips_input_filter(monkeypatch, tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    filter_calls = []
    monkeypatch.setattr(
        offline_command,
        "_filter_input_files",
        lambda *args: filter_calls.append(args),
    )
    monkeypatch.setattr(
        offline_command,
        "_run_single_offline_version",
        lambda **kwargs: None,
    )

    result = CliRunner().invoke(
        main,
        [
            "offline",
            "-i",
            str(input_dir),
            "-o",
            str(output_dir),
            "--no-run",
            "--no-plot",
            "--no-accuracy",
        ],
    )

    assert result.exit_code == 0
    assert filter_calls == []


def test_offline_default_timeout_uses_filtered_file_count(monkeypatch, tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    for index in range(52):
        (input_dir / f"sample_{index}.csv").write_text("x\n", encoding="utf-8")
    exe_path = tmp_path / "gh3036" / "exclusive" / "v1" / offline.EXE_NAME
    exe_path.parent.mkdir(parents=True)
    exe_path.write_text("", encoding="utf-8")
    timeouts = []

    monkeypatch.setattr(
        offline_command,
        "_validate_version_exes",
        lambda *args: {None: exe_path},
    )
    monkeypatch.setattr(offline_command, "_validate_local_cmd_configs", lambda exes: None)

    def remove_one_file(input_path, chip):
        (input_path / "sample_51.csv").unlink()

    monkeypatch.setattr(offline_command, "_filter_input_files", remove_one_file)
    monkeypatch.setattr(
        offline_command,
        "_run_single_offline_version",
        lambda **kwargs: timeouts.append(kwargs["timeout"]),
    )

    class FakeRunner:
        ppg_warnings = []

        def __init__(self, *args, **kwargs):
            pass

        def resolve_ppg_mapping(self):
            return {}

        def run(self, input_path, output_path, timeout=300, **kwargs):
            timeouts.append(timeout)
            output_path.mkdir(parents=True, exist_ok=True)
            return offline.OfflineRunResult(success=True)

    monkeypatch.setattr(offline, "find_exe", lambda *args: exe_path)
    monkeypatch.setattr(offline, "OfflineRunner", FakeRunner)

    def api_remove_one_file(input_path, chip):
        remove_one_file(input_path, chip)
        return None

    monkeypatch.setattr(offline_api, "_filter_input_files", api_remove_one_file)
    monkeypatch.setattr(
        offline,
        "reorganize_output",
        lambda input_path, output_path, show_progress=False: output_path,
    )
    monkeypatch.setattr("health_tools.core.psd_plotter.PsdPlotter.plot", lambda *args, **kwargs: [])
    monkeypatch.setattr(offline, "calculate_offline_accuracy", lambda *args, **kwargs: None)

    result = CliRunner().invoke(main, ["offline", "-i", str(input_dir), "-c", "gh3036"])

    assert result.exit_code == 0
    assert timeouts == [320]


def test_filter_input_files_stops_when_no_csv_is_accepted(monkeypatch, tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "bad.csv").write_text("bad\n", encoding="utf-8")

    with pytest.raises(SystemExit):
        offline_command._filter_input_files(input_dir, "gh3036")

    assert not (input_dir / "bad.csv").exists()
    assert (tmp_path / "input_mv" / "bad.csv").exists()


def test_offline_validates_ppg_mapping_before_filtering_input(monkeypatch, tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _write_valid_chip_csv(input_dir / "sample.csv")
    exe_path = tmp_path / "gh3036" / "exclusive" / "v1" / offline.EXE_NAME
    exe_path.parent.mkdir(parents=True)
    exe_path.write_text("", encoding="utf-8")
    filter_calls = []

    monkeypatch.setattr(offline, "find_exe", lambda chip, version=None: exe_path)
    monkeypatch.setattr(
        offline,
        "get_offline_config",
        lambda: offline.OfflineConfig(
            tools_path=tmp_path,
            versions={},
            commands={
                "gh3036": {
                    "v1": {
                        "cmd_arg": ["input_dir", "ppg_ch0"],
                        "cmd_default": {},
                    }
                }
            },
        ),
    )
    monkeypatch.setattr(
        offline_command,
        "_filter_input_files",
        lambda *args: filter_calls.append(args),
    )

    result = CliRunner().invoke(
        main,
        [
            "offline",
            "-i",
            str(input_dir),
            "-c",
            "gh3036",
            "--version",
            "v1",
            "--ppg-map",
            "ppg_ch0=NOT_A_COLUMN",
        ],
    )

    assert result.exit_code == 1
    assert "PPG映射列名不存在" in result.output
    assert filter_calls == []
    assert (input_dir / "sample.csv").exists()


def test_offline_ppg_options_are_passed_to_runner(monkeypatch, tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    output_dir = tmp_path / "output"
    exe_path = tmp_path / "gh3036" / "exclusive" / "v1" / offline.EXE_NAME
    exe_path.parent.mkdir(parents=True)
    exe_path.write_text("", encoding="utf-8")
    seen = {}

    class FakeRunner:
        resolved_version = "v1"
        ppg_mapping = {"ppg_ch0": 9}
        ppg_warnings = []

        def __init__(self, chip, version=None, **kwargs):
            seen.update(kwargs)

        def resolve_ppg_mapping(self):
            return self.ppg_mapping

        def run(self, input_path, output_path, timeout=300, settle_timeout=10):
            output_path.mkdir(parents=True, exist_ok=True)
            return offline.OfflineRunResult(success=True)

    monkeypatch.setattr(offline, "find_exe", lambda chip, version=None: exe_path)
    monkeypatch.setattr(offline, "OfflineRunner", FakeRunner)
    monkeypatch.setattr(offline_command, "_filter_input_files", lambda *args: None)
    monkeypatch.setattr(offline_api, "_filter_input_files", lambda *args: None)
    monkeypatch.setattr(offline, "reorganize_output", lambda *args, **kwargs: output_dir)

    result = CliRunner().invoke(
        main,
        [
            "offline",
            "-i",
            str(input_dir),
            "-o",
            str(output_dir),
            "-c",
            "gh3036",
            "--version",
            "v1",
            "--ppg-offset",
            "4",
            "--ppg-map",
            "ppg_ch0=CH4",
            "--no-plot",
            "--no-accuracy",
        ],
    )

    assert result.exit_code == 0
    assert seen["ppg_offset"] == 4
    assert seen["ppg_maps"] == ("ppg_ch0=CH4",)
    assert "PPG列映射" in result.output


def test_multi_version_ppg_mapping_uses_each_effective_cmd_arg(monkeypatch, tmp_path):
    exe_paths = {}
    commands = {"gh3036": {}}
    for version, cmd_arg in {"v1": ["ppg_ch0"], "v2": ["ppg_ch1"]}.items():
        exe_path = tmp_path / "gh3036" / "exclusive" / version / offline.EXE_NAME
        exe_path.parent.mkdir(parents=True)
        exe_path.write_text("", encoding="utf-8")
        exe_paths[version] = exe_path
        commands["gh3036"][version] = {"cmd_arg": cmd_arg, "cmd_default": {}}

    monkeypatch.setattr(offline, "find_exe", lambda chip, version=None: exe_paths[version])
    monkeypatch.setattr(
        offline,
        "get_offline_config",
        lambda: offline.OfflineConfig(tools_path=tmp_path, versions={}, commands=commands),
    )

    prepared = offline_command._prepare_offline_runners(
        version_exes=exe_paths,
        chip_name="gh3036",
        hba_fs=None,
        scene_en=None,
        ch_num=None,
        ref_col=None,
        ppg_offset=0,
        ppg_maps=("ppg_ch0=Ipd4",),
    )

    assert prepared["v1"].ppg_mapping == {"ppg_ch0": 9}
    assert prepared["v1"].ppg_warnings == []
    assert prepared["v2"].ppg_mapping == {"ppg_ch1": 6}
    assert prepared["v2"].ppg_warnings == ["ppg_ch0 未在 cmd_arg 中声明，设置未生效"]


def test_build_column_indices_from_chip_rule():
    indices = offline.build_column_indices("gh3036")

    assert indices["accx"] == 2
    assert indices["accy"] == 3
    assert indices["accz"] == 4
    assert indices["ppg_ch0"] == 5
    assert indices["ppg_ch3"] == 8
    assert indices["ppg_ch31"] == 36
    assert indices["polar"] == 45
    assert indices["mcu_out"] == 61
    assert indices["comp_out"] == 46


def test_merge_scanned_versions_preserves_existing_default():
    scanned = {
        "gh3220": {
            "versions": {"exclusive": ["v1", "v2"]},
            "default": "v2",
            "default_category": "exclusive",
        }
    }
    existing = {"gh3220": {"default": "v1", "default_category": "exclusive"}}

    merged = offline.merge_scanned_versions(scanned, existing)

    assert merged["gh3220"]["default"] == "v1"
    assert merged["gh3220"]["default_category"] == "exclusive"


def test_merge_scanned_versions_preserves_chip_command_config():
    scanned = {
        "gh3036": {
            "versions": {"exclusive": ["v1"]},
            "default": "v1",
            "default_category": "exclusive",
        }
    }
    existing = {
        "gh3036": {
            "default": "v1",
            "default_category": "exclusive",
            "cmd_arg": ["input_dir", "polar"],
            "cmd_default": {"scene_en": 0},
        }
    }

    merged = offline.merge_scanned_versions(scanned, existing)

    assert merged["gh3036"]["cmd_arg"] == ["input_dir", "polar"]
    assert merged["gh3036"]["cmd_default"] == {"scene_en": 0}


def test_merge_scanned_versions_replaces_missing_default():
    scanned = {
        "gh3220": {
            "versions": {"exclusive": ["v2"]},
            "default": "v2",
            "default_category": "exclusive",
        }
    }
    existing = {"gh3220": {"default": "v1", "default_category": "exclusive"}}

    merged = offline.merge_scanned_versions(scanned, existing)

    assert merged["gh3220"]["default"] == "v2"


def test_reorganize_output_recurses_nested_result_files(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    nested_dir = output_dir / "raw" / "nested"
    input_dir.mkdir()
    nested_dir.mkdir(parents=True)
    (input_dir / "sample.csv").write_text("x\n1\n", encoding="utf-8")
    result_file = nested_dir / "000000_sample_result.vshb"
    result_file.write_text(
        "1,80,79,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,80,1,99,0,0,0,81\n",
        encoding="utf-8",
    )

    reorg_dir = offline.reorganize_output(input_dir, output_dir)

    moved = reorg_dir / "000000_sample_result.vshb"
    assert moved.exists()
    assert not result_file.exists()
    assert offline.calculate_offline_accuracy(reorg_dir) is not None


def test_reorganize_output_skips_existing_reorganized_files(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    reorg_dir = output_dir / "数据整理"
    input_dir.mkdir()
    reorg_dir.mkdir(parents=True)
    (input_dir / "sample.csv").write_text("x\n1\n", encoding="utf-8")
    existing = reorg_dir / "000000_sample_result.vshb"
    existing.write_text(
        "1,80,79,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,80,1,99,0,0,0,81\n",
        encoding="utf-8",
    )

    returned = offline.reorganize_output(input_dir, output_dir)

    assert returned == reorg_dir
    assert existing.exists()


def test_reorganize_output_keeps_same_index_result_files_together(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    sample_dir = input_dir / "a"
    sample1_dir = input_dir / "b"
    sample_dir.mkdir(parents=True)
    sample1_dir.mkdir(parents=True)
    (sample_dir / "sample.csv").write_text("x\n1\n", encoding="utf-8")
    (sample1_dir / "sample1.csv").write_text("x\n1\n", encoding="utf-8")

    output_dir.mkdir()
    for name in [
        "000000_sample0.prepsd",
        "000000_sample_result.vshb",
        "000001_sample10.prepsd",
        "000001_sample1_result.vshb",
    ]:
        (output_dir / name).write_text("1,2,3\n", encoding="utf-8")

    reorg_dir = offline.reorganize_output(input_dir, output_dir)

    assert (reorg_dir / "a" / "000000_sample0.prepsd").exists()
    assert (reorg_dir / "a" / "000000_sample_result.vshb").exists()
    assert (reorg_dir / "b" / "000001_sample10.prepsd").exists()
    assert (reorg_dir / "b" / "000001_sample1_result.vshb").exists()
    assert not (reorg_dir / "a" / "000001_sample10.prepsd").exists()
    assert not (reorg_dir / "b" / "000000_sample0.prepsd").exists()


def test_reorganize_output_skips_paths_unsupported_by_offline_tool(monkeypatch, tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    skipped = input_dir / "a" / "skip.csv"
    handled = input_dir / "b" / "handled.csv"
    skipped.parent.mkdir()
    handled.parent.mkdir()
    skipped.write_text("x\n1\n", encoding="utf-8")
    handled.write_text("x\n1\n", encoding="utf-8")
    (output_dir / "000000_handled_result.vshb").write_text("1,2,3\n", encoding="utf-8")

    monkeypatch.setattr(
        offline,
        "_is_offline_tool_path_supported",
        lambda path: path.name != "skip.csv",
    )

    reorg_dir = offline.reorganize_output(input_dir, output_dir)

    assert (reorg_dir / "b" / "000000_handled_result.vshb").exists()
    assert not (reorg_dir / "a" / "000000_handled_result.vshb").exists()


def test_vshb_parser_uses_named_header_layout_fw_before_algo(tmp_path):
    vshb = tmp_path / "sample_result.vshb"
    vshb.write_text(
        "second, polar, fw_hr, comp_hr, algo_hr, algo_validscore, "
        "acc_x_std, acc_y_std, acc_z_std\n"
        "1,70,71,72,73,90,0.1,0.2,0.3\n",
        encoding="utf-8",
    )

    df = offline.VshbParser().parse(vshb)

    assert df.iloc[0].to_dict() == {
        "time": 1,
        "offline": 73,
        "ref": 70,
        "online": 71,
        "comp": 72,
    }


def test_vshb_parser_uses_named_header_layout_algo_before_fw(tmp_path):
    vshb = tmp_path / "sample_result.vshb"
    vshb.write_text(
        "second, polar, algo_hr, cmp_hr, fw_hr, scence,out_flag, valid_level, "
        "valid_score, rms_std, acc_x_std, acc_y_std, acc_z_std\n"
        "2,80,83,82,81,0,1,3,95,0.4,0.1,0.2,0.3\n",
        encoding="utf-8",
    )

    df = offline.VshbParser().parse(vshb)

    assert df.iloc[0].to_dict() == {
        "time": 2,
        "offline": 83,
        "ref": 80,
        "online": 81,
        "comp": 82,
    }


def test_vshb_parser_accepts_comp_header_alias(tmp_path):
    vshb = tmp_path / "sample_result.vshb"
    vshb.write_text(
        "second,polar,algo_hr,comp,fw_hr\n3,90,93,92,91\n",
        encoding="utf-8",
    )

    df = offline.VshbParser().parse(vshb)

    assert df.iloc[0]["comp"] == 92


def test_vshb_parser_allows_missing_comp_header(tmp_path):
    vshb = tmp_path / "sample_result.vshb"
    vshb.write_text(
        "second,polar,algo_hr,fw_hr\n4,90,93,91\n",
        encoding="utf-8",
    )

    df = offline.VshbParser().parse(vshb)

    assert len(df) == 1
    assert pd.isna(df.iloc[0]["comp"])


def test_vshb_parser_keeps_header_columns_with_trailing_commas(tmp_path):
    vshb = tmp_path / "sample_result.vshb"
    vshb.write_text(
        "second, polar, algo_hr, cmp_hr, fw_hr, scence,out_flag, valid_level, "
        "valid_score, rms_std, acc_x_std, acc_y_std, acc_z_std\n"
        "20,71,75,0,60,0,1,0,0.00,2.49,22.85,9.43,7.31,\n",
        encoding="utf-8",
    )

    df = offline.VshbParser().parse(vshb)

    assert df.iloc[0].to_dict() == {
        "time": 20,
        "offline": 75,
        "ref": 71,
        "online": 60,
        "comp": 0,
    }


def test_vshb_parser_falls_back_to_legacy_positions(tmp_path):
    vshb = tmp_path / "sample_result.vshb"
    row = ["0"] * 31
    row[0] = "3"
    row[1] = "93"
    row[2] = "90"
    row[3] = "92"
    row[30] = "91"
    vshb.write_text(",".join(row) + "\n", encoding="utf-8")

    df = offline.VshbParser().parse(vshb)

    assert df.iloc[0].to_dict() == {
        "time": 3,
        "offline": 93,
        "ref": 90,
        "online": 91,
        "comp": 92,
    }


def test_offline_accuracy_uses_online_vs_offline_when_polar_missing(tmp_path):
    result_dir = tmp_path / "result"
    result_dir.mkdir()
    rows = []
    for time, offline_hr, online_hr in [(1, 100, 103), (2, 101, 108), (3, 102, 114)]:
        row = ["0"] * 31
        row[0] = str(time)
        row[1] = str(offline_hr)
        row[2] = "0"
        row[30] = str(online_hr)
        rows.append(",".join(row))
    (result_dir / "sample_result.vshb").write_text("\n".join(rows) + "\n", encoding="utf-8")

    report = offline.calculate_offline_accuracy(result_dir)

    assert report is not None
    first = report.iloc[0].to_dict()
    assert first["reference"] == "offline"
    assert first["samples"] == 3
    assert first["MAE(online_vs_offline)"] == 7.33
    assert "MAE(offline)" not in report.columns
    assert "MAE(online)" not in report.columns


def test_offline_accuracy_includes_15_bpm_and_hides_zero_comp(tmp_path):
    result_dir = tmp_path / "result"
    result_dir.mkdir()
    (result_dir / "sample_result.vshb").write_text(
        "second,polar,algo_hr,comp_hr,fw_hr\n" "1,100,104,0,103\n" "2,100,112,0,108\n",
        encoding="utf-8",
    )

    report = offline.calculate_offline_accuracy(result_dir)

    assert report is not None
    assert "±15BPM(online)" in report.columns
    assert "±15BPM(offline)" in report.columns
    assert not any(column.endswith("(comp)") for column in report.columns)


def test_offline_accuracy_summarizes_mixed_reference_metrics_separately(tmp_path):
    result_dir = tmp_path / "result"
    result_dir.mkdir()

    with_ref = ["1,100,100,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,100,1,99,0,0,0,102"]
    no_ref_rows = []
    for time, offline_hr, online_hr in [(1, 100, 104), (2, 101, 107)]:
        row = ["0"] * 31
        row[0] = str(time)
        row[1] = str(offline_hr)
        row[2] = "0"
        row[30] = str(online_hr)
        no_ref_rows.append(",".join(row))

    (result_dir / "with_ref_result.vshb").write_text("\n".join(with_ref) + "\n", encoding="utf-8")
    (result_dir / "no_ref_result.vshb").write_text("\n".join(no_ref_rows) + "\n", encoding="utf-8")

    report = offline.calculate_offline_accuracy(result_dir)

    assert report is not None
    total = report[report["file"] == "TOTAL"].iloc[0]
    assert total["samples"] == 3
    assert total["MAE(online)"] == 2.0
    assert total["MAE(online_vs_offline)"] == 5.0


def test_offline_accuracy_adds_comp_metrics_and_skips_zero_comp(tmp_path):
    result_dir = tmp_path / "result"
    result_dir.mkdir()
    header = "second,polar,algo_hr,comp_hr,fw_hr"
    (result_dir / "valid_comp_result.vshb").write_text(
        f"{header}\n1,100,101,102,103\n2,100,102,104,105\n",
        encoding="utf-8",
    )
    (result_dir / "zero_comp_result.vshb").write_text(
        f"{header}\n1,100,101,0,103\n2,100,102,0,105\n",
        encoding="utf-8",
    )

    report = offline.calculate_offline_accuracy(result_dir)

    assert report is not None
    valid_row = report[report["file"] == "valid_comp"].iloc[0]
    zero_row = report[report["file"] == "zero_comp"].iloc[0]
    total = report[report["file"] == "TOTAL"].iloc[0]
    assert valid_row["MAE(comp)"] == 3.0
    assert pd.isna(zero_row["MAE(comp)"])
    assert total["MAE(comp)"] == 3.0


def test_vshb_reader_keeps_psd_legacy_online_column(tmp_path):
    vshb = tmp_path / "sample_result.vshb"
    vshb.write_text("4,103,100,101,999\n", encoding="utf-8")

    df = read_vshb_result(vshb, positional_online_col=-2)

    assert df.iloc[0].to_dict() == {
        "time": 4,
        "offline": 103,
        "ref": 100,
        "online": 101,
        "comp": 101,
    }


def test_psd_overlay_uses_column_30_for_headerless_online(tmp_path):
    vshb = tmp_path / "sample_result.vshb"
    row = ["0"] * 33
    row[0] = "8"
    row[1] = "116"
    row[2] = "115"
    row[3] = "118"
    row[30] = "117"
    row[-2] = "0"
    vshb.write_text(",".join(row) + "\n", encoding="utf-8")

    overlay = psd_plotter._load_vshb_overlay(vshb)

    assert overlay["time"].tolist() == [8]
    assert overlay["offline"].tolist() == [116]
    assert overlay["ref"].tolist() == [115]
    assert overlay["online"].tolist() == [117]
    assert overlay["comp"].tolist() == [118]


def test_psd_metrics_include_5_10_15_bpm_and_mae():
    ref = np.array([100, 100, 100, 100], dtype=float)
    pred = np.array([103, 107, 112, 120], dtype=float)

    metrics = psd_plotter._calc_metrics(ref, pred)
    line = psd_plotter._format_metric_line("Online", metrics)

    assert metrics == {
        "within_5": 25.0,
        "within_10": 50.0,
        "within_15": 75.0,
        "mae": 10.5,
    }
    assert line == "Online: ±5bpm=25.0%  ±10bpm=50.0%  ±15bpm=75.0%  MAE=10.5"


def test_psd_metric_text_uses_online_vs_offline_when_polar_missing():
    polar = np.array([0, 0, 0], dtype=float)
    offline_hr = np.array([100, 100, 100], dtype=float)
    online_hr = np.array([103, 107, 112], dtype=float)
    comp_hr = np.array([101, 102, 103], dtype=float)

    rows = psd_plotter._metric_text_rows(polar, offline_hr, online_hr, comp_hr)

    assert rows == ["Online vs Offline: ±5bpm=33.3%  ±10bpm=66.7%  ±15bpm=100.0%  MAE=7.33"]


def test_psd_metric_text_uses_polar_when_available():
    polar = np.array([100, 100, 100], dtype=float)
    offline_hr = np.array([101, 102, 103], dtype=float)
    online_hr = np.array([103, 107, 112], dtype=float)
    comp_hr = np.array([102, 104, 106], dtype=float)

    rows = psd_plotter._metric_text_rows(polar, offline_hr, online_hr, comp_hr)

    assert rows[0].startswith("Offline vs Polar:")
    assert rows[1].startswith("Online vs Polar:")
    assert rows[2].startswith("Comp vs Polar:")


def test_psd_metric_text_skips_zero_comp():
    polar = np.array([100, 100, 100], dtype=float)
    offline_hr = np.array([101, 102, 103], dtype=float)
    online_hr = np.array([103, 107, 112], dtype=float)
    comp_hr = np.array([0, 0, 0], dtype=float)

    rows = psd_plotter._metric_text_rows(polar, offline_hr, online_hr, comp_hr)

    assert len(rows) == 2
    assert all(not row.startswith("Comp vs Polar:") for row in rows)


def test_psd_metric_text_uses_global_ready_boundary_and_keeps_middle_zero():
    polar = np.array([80, 81, 82, 0, 84, 85, 86], dtype=float)
    online_hr = np.array([0, 81, 87, 0, 89, 85, 0], dtype=float)
    offline_hr = np.array([0, 0, 82, 0, 84, 0, 0], dtype=float)
    comp_hr = np.zeros(7, dtype=float)

    strict_rows = psd_plotter._metric_text_rows(
        polar,
        offline_hr,
        online_hr,
        comp_hr,
        accuracy_thresholds=(5.0,),
    )
    inclusive_rows = psd_plotter._metric_text_rows(
        polar,
        offline_hr,
        online_hr,
        comp_hr,
        accuracy_thresholds=(5.0,),
        accuracy_inclusive=True,
    )

    assert strict_rows == [
        "Offline vs Polar: ±5bpm=100.0%  MAE=0.0",
        "Online vs Polar: ±5bpm=33.3%  MAE=3.33",
    ]
    assert inclusive_rows[1] == "Online vs Polar: ±5bpm=100.0%  MAE=3.33"


def test_psd_metric_text_preserves_high_precision_threshold_names():
    rows = psd_plotter._metric_text_rows(
        np.array([100, 100], dtype=float),
        np.array([101.0000001, 101.0000002], dtype=float),
        np.array([101.0000001, 101.0000002], dtype=float),
        np.zeros(2, dtype=float),
        accuracy_thresholds=(1.0000001, 1.0000002),
    )

    assert "±1.0000001bpm=" in rows[0]
    assert "±1.0000002bpm=" in rows[0]


def test_offline_accuracy_uses_global_boundary_and_per_comparison_samples(tmp_path):
    result_dir = tmp_path / "result"
    result_dir.mkdir()
    header = "second,polar,algo_hr,comp_hr,fw_hr"
    rows = [
        "1,80,0,0,0",
        "2,81,0,0,81",
        "3,82,82,0,87",
        "4,0,0,0,0",
        "5,84,84,0,89",
        "6,85,0,0,85",
        "7,86,0,0,0",
    ]
    (result_dir / "sample_result.vshb").write_text(
        header + "\n" + "\n".join(rows) + "\n",
        encoding="utf-8",
    )

    report = offline.calculate_offline_accuracy(
        result_dir,
        accuracy_thresholds=(5.0,),
    )

    assert report is not None
    first = report.iloc[0]
    assert first["samples"] == 3
    assert first["samples(offline)"] == 3
    assert first["samples(online)"] == 3
    assert first["±5BPM(offline)"] == 100.0
    assert first["±5BPM(online)"] == 33.33
    assert not any(column.endswith("(comp)") for column in report.columns)


def test_offline_accuracy_weights_each_comparison_by_its_own_samples(tmp_path):
    result_dir = tmp_path / "result"
    result_dir.mkdir()
    header = "second,polar,algo_hr,comp_hr,fw_hr"
    (result_dir / "first_result.vshb").write_text(
        header + "\n1,100,100,0,100\n2,100,100,0,nan\n3,100,100,0,110\n",
        encoding="utf-8",
    )
    (result_dir / "second_result.vshb").write_text(
        header + "\n1,100,100,0,110\n2,100,100,0,110\n3,100,100,0,110\n",
        encoding="utf-8",
    )

    report = offline.calculate_offline_accuracy(result_dir)

    assert report is not None
    total = report.loc[report["file"] == "TOTAL"].iloc[0]
    assert total["samples"] == 6
    assert total["samples(offline)"] == 6
    assert total["samples(online)"] == 5
    assert total["MAE(offline)"] == 0.0
    assert total["MAE(online)"] == 8.0


def test_psd_hr_overlays_draws_cyan_dashed_comp():
    ax = Mock()
    second = np.array([1, 2], dtype=float)
    offline_hr = np.array([100, 101], dtype=float)
    online_hr = np.array([101, 102], dtype=float)
    polar_hr = np.array([99, 100], dtype=float)
    comp_hr = np.array([102, 103], dtype=float)

    psd_plotter._plot_hr_overlays(ax, second, offline_hr, online_hr, polar_hr, comp_hr)

    assert len(ax.plot.call_args_list) == 4
    assert ax.plot.call_args_list[3].kwargs == {
        "color": "#00E5FF",
        "linestyle": "--",
        "linewidth": 2,
    }
    ax.legend.assert_called_once_with(
        ["pred(offline)", "mcu(online)", "polar(ref)", "comp"], loc="upper right"
    )


def test_psd_hr_overlays_skips_zero_comp():
    ax = Mock()
    values = np.array([100, 101], dtype=float)

    psd_plotter._plot_hr_overlays(ax, values, values, values, values, np.zeros(2))

    assert len(ax.plot.call_args_list) == 3
    ax.legend.assert_called_once_with(
        ["pred(offline)", "mcu(online)", "polar(ref)"], loc="upper right"
    )


def test_psd_hr_overlays_draws_comp_without_polar():
    ax = Mock()
    values = np.array([100, 101], dtype=float)

    psd_plotter._plot_hr_overlays(ax, values, values, values, np.zeros(2), values)

    assert len(ax.plot.call_args_list) == 3
    ax.legend.assert_called_once_with(["pred(offline)", "mcu(online)", "comp"], loc="upper right")


def test_psd_subplot_top_reserves_space_for_rms_metrics():
    assert psd_plotter._subplot_top(4, True, 2) == 0.88
    assert psd_plotter._subplot_top(4, True, 3) == 0.84
    assert psd_plotter._subplot_top(2, True, 2) == 0.80
    assert psd_plotter._subplot_top(2, True, 3) == 0.76
    assert psd_plotter._subplot_top(4, False, 0) == 0.88


def test_psd_plotter_skips_overlay_when_vshb_read_fails(monkeypatch, tmp_path):
    result_dir = tmp_path / "result"
    output_dir = tmp_path / "out"
    result_dir.mkdir()
    (result_dir / "sample_result.vshb").write_text("bad vshb\n", encoding="utf-8")
    np.savetxt(result_dir / "sample0.prepsd", np.arange(16).reshape(4, 4), delimiter=",")
    plot_calls = []

    def fake_read_vshb_result(*args, **kwargs):
        raise ValueError("读取失败")

    original_plot = Axes.plot

    def record_plot(self, *args, **kwargs):
        plot_calls.append((args, kwargs))
        return original_plot(self, *args, **kwargs)

    monkeypatch.setattr(psd_plotter, "read_vshb_result", fake_read_vshb_result)
    monkeypatch.setattr(Axes, "plot", record_plot)

    saved = psd_plotter.PsdPlotter().plot(result_dir, save_dir=output_dir)

    assert len(saved) == 1
    assert saved[0].exists()
    assert saved[0].name == "sample.png"
    assert plot_calls == []


def test_psd_plotter_axis_mode_reads_acc_xyz(monkeypatch, tmp_path):
    result_dir = tmp_path / "result"
    output_dir = tmp_path / "out"
    result_dir.mkdir()
    (result_dir / "sample_result.vshb").write_text("bad vshb\n", encoding="utf-8")
    for name in ["sample0.prepsd", "sample.accxpsd", "sample.accypsd", "sample.acczpsd"]:
        (result_dir / name).write_text("1,2\n3,4\n", encoding="utf-8")
    loaded = []

    def fake_load_csv(path):
        loaded.append(path.name)
        return np.arange(16).reshape(4, 4)

    monkeypatch.setattr(psd_plotter, "_load_csv_like_matlab", fake_load_csv)
    monkeypatch.setattr(
        psd_plotter, "_load_vshb_overlay", lambda path: psd_plotter._empty_overlay()
    )

    saved = psd_plotter.PsdPlotter().plot(result_dir, save_dir=output_dir)

    assert len(saved) == 1
    assert loaded == ["sample0.prepsd", "sample.accxpsd", "sample.accypsd", "sample.acczpsd"]


def test_psd_source_copy_is_optional_and_pixel_identical(tmp_path):
    result_dir = tmp_path / "result"
    nested_dir = result_dir / "scene"
    primary_dir = tmp_path / "primary"
    mirrored_primary_dir = tmp_path / "mirrored_primary"
    nested_dir.mkdir(parents=True)
    (nested_dir / "sample_result.vshb").write_text("bad vshb\n", encoding="utf-8")
    np.savetxt(nested_dir / "sample0.prepsd", np.arange(16).reshape(4, 4), delimiter=",")

    saved = psd_plotter.PsdPlotter().plot(result_dir, save_dir=primary_dir)

    source_copy = nested_dir / "sample.png"
    assert saved == [primary_dir / "sample.png"]
    assert not source_copy.exists()

    mirrored = psd_plotter.PsdPlotter().plot(
        result_dir,
        save_dir=mirrored_primary_dir,
        save_to_source=True,
    )

    assert mirrored == [mirrored_primary_dir / "sample.png"]
    assert source_copy.exists()
    primary_pixels = np.asarray(Image.open(mirrored[0]).convert("RGB"))
    source_pixels = np.asarray(Image.open(source_copy).convert("RGB"))
    assert np.array_equal(primary_pixels, source_pixels)


def test_psd_plotter_rms_mode_reads_accrms(monkeypatch, tmp_path):
    result_dir = tmp_path / "result"
    output_dir = tmp_path / "out"
    result_dir.mkdir()
    (result_dir / "sample_result.vshb").write_text("bad vshb\n", encoding="utf-8")
    for name in ["sample0.prepsd", "sample.accrmspsd", "sample.accxpsd"]:
        (result_dir / name).write_text("1,2\n3,4\n", encoding="utf-8")
    loaded = []

    def fake_load_csv(path):
        loaded.append(path.name)
        return np.arange(16).reshape(4, 4)

    monkeypatch.setattr(psd_plotter, "_load_csv_like_matlab", fake_load_csv)
    monkeypatch.setattr(
        psd_plotter, "_load_vshb_overlay", lambda path: psd_plotter._empty_overlay()
    )

    saved = psd_plotter.PsdPlotter().plot(result_dir, save_dir=output_dir, acc_mode="rms")

    assert len(saved) == 1
    assert loaded == ["sample0.prepsd", "sample.accrmspsd"]
