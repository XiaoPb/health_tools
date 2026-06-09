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
