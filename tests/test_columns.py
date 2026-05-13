"""列名展开工具测试。"""

from health_tools.utils.columns import expand_columns


def test_brace_syntax():
    result = expand_columns(["ch{0-3}"])
    assert result == ["ch0", "ch1", "ch2", "ch3"]


def test_brace_with_brackets_literal():
    result = expand_columns(["rawdata[{0-2}]"])
    assert result == ["rawdata[0]", "rawdata[1]", "rawdata[2]"]


def test_brackets_preserved_as_literal():
    result = expand_columns(["ch[0-3]"])
    assert result == ["ch[0-3]"]


def test_no_expansion():
    result = expand_columns(["timestamp", "value"])
    assert result == ["timestamp", "value"]


def test_mixed_columns():
    result = expand_columns(["timestamp", "ch{0-2}", "flag"])
    assert result == ["timestamp", "ch0", "ch1", "ch2", "flag"]


def test_brace_in_middle():
    result = expand_columns(["data{0-1}_raw"])
    assert result == ["data0_raw", "data1_raw"]
