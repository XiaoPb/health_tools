"""规则加载器单元测试。"""

from health_tools.rules.loader import RuleLoader


def test_load_chip_rule_preserves_check_specific_columns(tmp_path):
    """芯片规则中的检查专用列配置应完整传入 ChipRule。"""
    rule_file = tmp_path / "custom.yaml"
    rule_file.write_text(
        """
chip: custom
csv:
  header_row: 1
  data_start_row: 2
columns:
  - time
  - framed_id
  - acc_x
  - acc_y
  - acc_z
  - ppg_ch{0-1}
frame_column: framed_id
acc_columns:
  x: acc_x
  y: acc_y
  z: acc_z
check_columns:
  data:
    - ppg_ch{0-1}
""",
        encoding="utf-8",
    )

    rule = RuleLoader.load_chip_rule(str(rule_file.with_suffix("")))

    assert rule.frame_column == "framed_id"
    assert rule.acc_columns == {"x": "acc_x", "y": "acc_y", "z": "acc_z"}
    assert rule.check_columns["data"] == ["ppg_ch0", "ppg_ch1"]
