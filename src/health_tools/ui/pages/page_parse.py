"""日志解析页面"""

import streamlit as st

from health_tools.core.parser import LogParser
from health_tools.models.rules import ParseRule
from health_tools.rules.loader import RuleLoader
from health_tools.ui.components.chip_selector import chip_select
from health_tools.ui.components.file_picker import file_input, output_input
from health_tools.ui.components.result_display import save_and_show

st.header("Parse - 日志解析")

with st.sidebar:
    chip_rule = chip_select(key="parse_chip")

input_file = file_input("输入日志文件", key="parse_input")
output_path = output_input("输出 CSV 路径", key="parse_output")

parse_rule = None
if chip_rule:
    try:
        parse_rule = RuleLoader.load_parse_rule(chip_rule.chip)
    except Exception:
        pass

regex_default = parse_rule.regex if parse_rule else ""
columns_default = ",".join(parse_rule.columns) if parse_rule else ""

regex = st.text_input("正则表达式", value=regex_default, key="parse_regex")
columns_str = st.text_input("列名 (逗号分隔)", value=columns_default, key="parse_cols")

c1, c2 = st.columns(2)
separator = c1.text_input("分隔符", value=",", key="parse_sep")
encoding = c2.selectbox("编码", ["utf-8", "gbk", "auto"], key="parse_enc")

if st.button("执行解析", type="primary", key="parse_run"):
    if input_file is None:
        st.error("请输入有效文件")
        st.stop()
    if not regex:
        st.error("请输入正则表达式")
        st.stop()

    columns = [c.strip() for c in columns_str.split(",") if c.strip()]
    rule = ParseRule(regex=regex, columns=columns, separator=separator)
    chip_columns = chip_rule.columns if chip_rule else None
    parser = LogParser(rule, chip_columns=chip_columns)

    enc = encoding if encoding != "auto" else "utf-8"
    result_df = parser.parse_file(input_file, encoding=enc)

    if result_df is None or result_df.empty:
        st.warning("未匹配到任何数据")
        st.stop()

    st.success(f"解析成功: {len(result_df)} 行")
    save_and_show(result_df, output_path, title="解析结果")
