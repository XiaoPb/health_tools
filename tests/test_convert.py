from pathlib import Path

from health_tools.core.converter import DataConverter
from health_tools.models.rules import ConvertRule


def test_convert_with_extra_source_alignment(tmp_path: Path):
    source_file = tmp_path / "sample.csv"
    source_file.write_text(
        "type,time,value\nHR,16:42:05,1\nHR,16:42:06,2\n",
        encoding="utf-8",
    )

    extra_file = tmp_path / "sample.txt"
    extra_file.write_text(
        "time,polar\n16:42:05,90\n16:42:06,91\n",
        encoding="utf-8",
    )

    rule = ConvertRule(
        column_mapping={"time": "TimeStamp", "value": "VALUE", "polar": "REF_RESULT0"}
    )
    rule.extra_source = {
        "suffix": ".txt",
        "csv": {"header_row": 1, "data_start_row": 2, "delimiter": ","},
        "align": {"left_on": "time", "right_on": "time"},
        "column_mapping": {"polar": "polar"},
    }

    converter = DataConverter(rule)
    import pandas as pd

    df = pd.read_csv(source_file)
    result = converter.convert(df, source_file=source_file)

    assert list(result["REF_RESULT0"]) == [90, 91]
    assert list(result["TimeStamp"]) == ["16:42:05", "16:42:06"]


def test_convert_with_extra_source_custom_align_columns(tmp_path: Path):
    source_file = tmp_path / "sample.csv"
    source_file.write_text(
        "device_time,value\n16:42:05,1\n16:42:06,2\n",
        encoding="utf-8",
    )

    extra_file = tmp_path / "gold.ref.csv"
    extra_file.write_text(
        "ref_time,hr\n16:42:05,100\n16:42:06,101\n",
        encoding="utf-8",
    )

    rule = ConvertRule(
        column_mapping={"device_time": "TimeStamp", "value": "VALUE", "gold_hr": "REF_RESULT0"}
    )
    rule.extra_source = {
        "pattern": "*.ref.csv",
        "csv": {"header_row": 1, "data_start_row": 2, "delimiter": ","},
        "align": {"left_on": "device_time", "right_on": "ref_time"},
        "column_mapping": {"hr": "gold_hr"},
    }

    converter = DataConverter(rule)
    import pandas as pd

    df = pd.read_csv(source_file)
    result = converter.convert(df, source_file=source_file)

    assert list(result["REF_RESULT0"]) == [100, 101]


def test_extra_source_pattern_skips_source_file_and_checks_required_columns(tmp_path: Path):
    source_file = tmp_path / "raw.csv"
    source_file.write_text("time,value\n15:06:01,1\n", encoding="utf-8")

    bad_extra = tmp_path / "bad_gold.csv"
    bad_extra.write_text("foo,bar\n15:06:01,99\n", encoding="utf-8")

    good_extra = tmp_path / "guest_6_27_26.csv"
    good_extra.write_text("时间, SpO2\n中国标准时间 15:06:01,97\n", encoding="utf-8")

    rule = ConvertRule(column_mapping={"time": "TimeStamp", "value": "VALUE", "gold_spo2": "REF"})
    rule.extra_source = {
        "pattern": "*.csv",
        "required_columns": ["时间"],
        "any_required_columns": ["SpO2", "O2 饱和度"],
        "csv": {"header_row": 1, "data_start_row": 2, "delimiter": ","},
        "align": {"left_on": "time", "right_on": "时间", "right_extract": r"(\d{2}:\d{2}:\d{2})"},
        "column_mapping": {"SpO2": "gold_spo2", "O2 饱和度": "gold_spo2"},
    }

    converter = DataConverter(rule)
    import pandas as pd

    df = pd.read_csv(source_file)
    result = converter.convert(df, source_file=source_file)

    assert list(result["REF"]) == [97]


def test_extra_source_align_extracts_time_from_chinese_timestamp(tmp_path: Path):
    source_file = tmp_path / "raw.csv"
    source_file.write_text("time,value\n15:06:01,1\n15:06:02,2\n", encoding="utf-8")

    extra_file = tmp_path / "guest_gold.csv"
    extra_file.write_text(
        "时间,O2 饱和度\n中国标准时间 15:06:01,97\n中国标准时间 15:06:02,98\n",
        encoding="utf-8",
    )

    rule = ConvertRule(column_mapping={"time": "TimeStamp", "gold_spo2": "REF_RESULT0"})
    rule.extra_source = {
        "pattern": "*.csv",
        "required_columns": ["时间"],
        "any_required_columns": ["SpO2", "O2 饱和度"],
        "csv": {"header_row": 1, "data_start_row": 2, "delimiter": ","},
        "align": {"left_on": "time", "right_on": "时间", "right_extract": r"(\d{2}:\d{2}:\d{2})"},
        "column_mapping": {"SpO2": "gold_spo2", "O2 饱和度": "gold_spo2"},
    }

    converter = DataConverter(rule)
    import pandas as pd

    df = pd.read_csv(source_file)
    result = converter.convert(df, source_file=source_file)

    assert list(result["REF_RESULT0"]) == [97, 98]


def test_converter_returns_no_columns_when_rule_sources_do_not_match():
    import pandas as pd

    rule = ConvertRule(column_mapping={"time": "TimeStamp", "value": "VALUE"})
    converter = DataConverter(rule)
    df = pd.DataFrame({"foo": [1], "bar": [2]})

    result = converter.convert(df)

    assert result.empty
    assert list(result.columns) == []


def test_forward_fill_uses_previous_nonzero_value():
    import pandas as pd

    rule = ConvertRule(column_mapping={"frame": "FRAME_ID"})
    rule.forward_fill = ["FRAME_ID"]
    converter = DataConverter(rule)
    df = pd.DataFrame({"frame": [0, 10, 0, 0, 13]})

    result = converter.convert(df)

    assert list(result["FRAME_ID"]) == [0, 10, 10, 10, 13]


def test_convert_file_skips_output_when_rule_sources_do_not_match(tmp_path: Path):
    from health_tools.commands.convert import _convert_file

    input_file = tmp_path / "invalid.csv"
    output_file = tmp_path / "out.csv"
    input_file.write_text("foo,bar\n1,2\n", encoding="utf-8")

    rule = ConvertRule(column_mapping={"time": "TimeStamp", "value": "VALUE"})
    converter = DataConverter(rule)

    _convert_file(input_file, output_file, converter, None, None, verbose=False)

    assert not output_file.exists()


def test_merge_and_convert_skips_files_that_do_not_match_rule(tmp_path: Path):
    from health_tools.commands.convert import _merge_and_convert

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "valid.csv").write_text("time,value\n1,10\n", encoding="utf-8")
    (input_dir / "invalid.csv").write_text("foo,bar\n9,99\n", encoding="utf-8")
    output_file = tmp_path / "merged.csv"

    rule = ConvertRule(column_mapping={"time": "TimeStamp", "value": "VALUE"})
    converter = DataConverter(rule)

    _merge_and_convert(input_dir, output_file, converter, None, None, None, None, verbose=False)

    import pandas as pd

    result = pd.read_csv(output_file)
    assert list(result.columns) == ["TimeStamp", "VALUE"]
    assert result.to_dict("records") == [{"TimeStamp": 1, "VALUE": 10}]
