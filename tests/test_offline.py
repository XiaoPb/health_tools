"""offline 命令构建测试。"""

from pathlib import Path

import numpy as np
from matplotlib.axes import Axes

from health_tools.core import psd_plotter
from health_tools.core import offline
from health_tools.core.vshb import read_vshb_result


def _make_runner(
    monkeypatch,
    tmp_path: Path,
    commands: dict,
    chip: str = "gh3036",
    hba_fs=None,
    scene_en=None,
    ch_num=None,
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


def test_build_command_falls_back_to_builtin_format(monkeypatch, tmp_path):
    runner = _make_runner(monkeypatch, tmp_path, {}, hba_fs=25, scene_en=1, ch_num=2)

    cmd = runner._build_command("input", "output")

    assert cmd.endswith(' 0 -1 "input" "output" csv 25 1 2 2 3 4 5 6 7 8 45 61 46')


def test_build_column_indices_from_chip_rule():
    indices = offline.build_column_indices("gh3036")

    assert indices["accx"] == 2
    assert indices["accy"] == 3
    assert indices["accz"] == 4
    assert indices["ppg_ch0"] == 5
    assert indices["ppg_ch3"] == 8
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
    }


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
    }


def test_vshb_parser_falls_back_to_legacy_positions(tmp_path):
    vshb = tmp_path / "sample_result.vshb"
    row = ["0"] * 31
    row[0] = "3"
    row[1] = "93"
    row[2] = "90"
    row[30] = "91"
    vshb.write_text(",".join(row) + "\n", encoding="utf-8")

    df = offline.VshbParser().parse(vshb)

    assert df.iloc[0].to_dict() == {
        "time": 3,
        "offline": 93,
        "ref": 90,
        "online": 91,
    }


def test_vshb_reader_keeps_psd_legacy_online_column(tmp_path):
    vshb = tmp_path / "sample_result.vshb"
    vshb.write_text("4,103,100,101,999\n", encoding="utf-8")

    df = read_vshb_result(vshb, positional_online_col=-2)

    assert df.iloc[0].to_dict() == {
        "time": 4,
        "offline": 103,
        "ref": 100,
        "online": 101,
    }


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
