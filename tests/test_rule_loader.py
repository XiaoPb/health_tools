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


def test_load_convert_rule_preserves_split_config(tmp_path):
    rule_file = tmp_path / "convert" / "split.yaml"
    rule_file.parent.mkdir(parents=True, exist_ok=True)
    rule_file.write_text(
        "version: '1.0'\n"
        "column_mapping:\n  time: TimeStamp\n"
        "split:\n"
        "  by_time: 60\n"
        "  time_column: TimeStamp\n",
        encoding="utf-8",
    )

    rule = RuleLoader.load_convert_rule(str(rule_file))

    assert rule.split == {"by_time": 60, "time_column": "TimeStamp"}


def test_load_convert_rule_with_null_split_loads_empty_dict(tmp_path):
    rule_file = tmp_path / "convert" / "null_split.yaml"
    rule_file.parent.mkdir(parents=True, exist_ok=True)
    rule_file.write_text(
        "version: '1.0'\n" "column_mapping:\n  time: TimeStamp\n" "split: null\n",
        encoding="utf-8",
    )

    rule = RuleLoader.load_convert_rule(str(rule_file))

    assert rule.split == {}


def test_load_convert_rule_preserves_classify_block(tmp_path):
    rule_file = tmp_path / "convert" / "classify.yaml"
    rule_file.parent.mkdir(parents=True, exist_ok=True)
    rule_file.write_text(
        "version: '1.0'\n"
        "column_mapping:\n  time: TimeStamp\n"
        "classify:\n"
        "  default: unclassified\n"
        "  extract:\n"
        "    - name: spo2_median\n"
        "      function: calculate_median\n"
        "      params:\n"
        "        column: REF_RESULT5\n"
        "  classify:\n"
        "    - target: normal\n"
        "      condition: 'spo2_median >= 95'\n",
        encoding="utf-8",
    )

    rule = RuleLoader.load_convert_rule(str(rule_file))

    assert rule.classify["default"] == "unclassified"
    assert rule.classify["extract"][0]["name"] == "spo2_median"
    assert rule.classify["extract"][0]["function"] == "calculate_median"
    assert rule.classify["classify"][0] == {"target": "normal", "condition": "spo2_median >= 95"}


def test_load_convert_rule_preserves_classify_full_schema(tmp_path):
    rule_file = tmp_path / "convert" / "classify_full.yaml"
    rule_file.parent.mkdir(parents=True, exist_ok=True)
    rule_file.write_text(
        "version: '1.0'\n"
        "column_mapping:\n  time: TimeStamp\n"
        "classify:\n"
        "  filename:\n"
        "    regex: '(\\d{8})_(\\w+)_(\\w+)\\.csv'\n"
        "    fields: [date, chip, project]\n"
        "  data_columns:\n"
        "    - name: motion\n"
        "      source: filename\n"
        "      match:\n"
        "        sit: [sit]\n"
        "        walk: [walk]\n"
        "  structure:\n"
        "    sit: ''\n"
        "    walk: ''\n"
        "  rules:\n"
        "    - target: '{project}/{motion}'\n"
        "  rename: '{date}_{project}_{filename}'\n"
        "  default: unclassified\n",
        encoding="utf-8",
    )

    rule = RuleLoader.load_convert_rule(str(rule_file))
    classify = rule.classify

    assert classify["filename"]["fields"] == ["date", "chip", "project"]
    assert classify["data_columns"][0]["match"] == {"sit": ["sit"], "walk": ["walk"]}
    assert classify["structure"] == {"sit": "", "walk": ""}
    assert classify["rules"] == [{"target": "{project}/{motion}"}]
    assert classify["rename"] == "{date}_{project}_{filename}"
