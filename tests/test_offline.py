"""offline 命令构建测试。"""

from pathlib import Path

from health_tools.core import offline


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
