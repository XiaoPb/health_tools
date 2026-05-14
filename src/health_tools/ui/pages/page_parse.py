"""日志解析页面"""

import pandas as pd
import streamlit as st

from health_tools.core.parser import LogParser
from health_tools.models.rules import ParseRule
from health_tools.rules.loader import RuleLoader
from health_tools.ui.components.chip_selector import chip_select
from health_tools.ui.components.file_picker import file_input, output_input
from health_tools.ui.components.result_display import save_and_show
from health_tools.ui.components.rule_saver import load_rule_selector, save_rule_ui

st.header("Parse - 日志解析")

with st.sidebar:
    chip_rule = chip_select(key="parse_chip")

# 加载历史规则
rule_file = load_rule_selector("parse", key="parse_rule_sel")

if rule_file and "parse_loaded_rule" not in st.session_state:
    st.session_state["parse_loaded_rule"] = rule_file

if rule_file and st.session_state.get("parse_loaded_rule") != rule_file:
    st.session_state["parse_loaded_rule"] = rule_file

loaded_rule = None
if rule_file:
    try:
        loaded_rule = RuleLoader.load_parse_rule(rule_file)
    except Exception as e:
        st.warning(f"加载规则失败: {e}")

# 从芯片规则加载（优先级低于手动选择的规则）
if loaded_rule is None and chip_rule and not rule_file:
    try:
        loaded_rule = RuleLoader.load_parse_rule(chip_rule.chip)
    except Exception:
        pass

input_file = file_input("输入日志文件", key="parse_input")
output_path = output_input("输出 CSV 路径", key="parse_output")

# --- 主正则 ---
st.subheader("主正则 (可选)")
st.caption("适用于单一格式的日志，填写后作为默认解析规则")

regex_default = loaded_rule.regex if loaded_rule else ""
columns_default = ",".join(loaded_rule.columns) if loaded_rule else ""
sep_default = loaded_rule.separator if loaded_rule else ","

regex = st.text_input("正则表达式", value=regex_default, key="parse_regex")
columns_str = st.text_input("列名 (逗号分隔)", value=columns_default, key="parse_cols")

c1, c2 = st.columns(2)
separator = c1.text_input("分隔符", value=sep_default, key="parse_sep")
encoding = c2.selectbox("编码", ["utf-8", "gbk", "auto"], key="parse_enc")

# --- 多正则模式 (patterns) ---
st.subheader("多正则模式 (可选)")
st.caption("适用于混合格式日志，每行定义一个命名 pattern，解析时逐行尝试匹配")

patterns_default_data = []
if loaded_rule and loaded_rule.patterns:
    for name, pat in loaded_rule.patterns.items():
        patterns_default_data.append(
            {
                "name": name,
                "regex": pat.regex,
                "columns": ",".join(pat.columns),
                "separator": pat.separator,
            }
        )

if not patterns_default_data:
    patterns_default_data = [{"name": "", "regex": "", "columns": "", "separator": ","}]

patterns_df = pd.DataFrame(patterns_default_data)
patterns_edited = st.data_editor(
    patterns_df, num_rows="dynamic", key="parse_patterns", use_container_width=True
)

st.divider()

# --- 执行 ---
if st.button("执行解析", type="primary", key="parse_run"):
    if input_file is None:
        st.error("请输入有效文件")
        st.stop()
    if not regex and patterns_edited["regex"].str.strip().eq("").all():
        st.error("请至少填写主正则或一个 pattern")
        st.stop()

    columns = [c.strip() for c in columns_str.split(",") if c.strip()]

    patterns = {}
    for _, row in patterns_edited.iterrows():
        pname = str(row["name"]).strip()
        pregex = str(row["regex"]).strip()
        pcols_str = str(row["columns"]).strip()
        psep = str(row["separator"]).strip() or ","
        if pname and pregex and pcols_str:
            pcols = [c.strip() for c in pcols_str.split(",") if c.strip()]
            patterns[pname] = {"regex": pregex, "columns": pcols, "separator": psep}

    rule = ParseRule(regex=regex, columns=columns, separator=separator, patterns=patterns)
    chip_columns = chip_rule.columns if chip_rule else None
    parser = LogParser(rule, chip_columns=chip_columns)

    enc = encoding if encoding != "auto" else "utf-8"
    result_df = parser.parse_file(input_file, encoding=enc)

    if result_df is None or result_df.empty:
        st.warning("未匹配到任何数据")
        st.stop()

    st.success(f"解析成功: {len(result_df)} 行")
    save_and_show(result_df, output_path, title="解析结果")

# --- 保存规则 ---
st.divider()

# 构建当前配置数据
current_rule_data = {}
if regex:
    current_rule_data["regex"] = regex
cur_cols = [c.strip() for c in columns_str.split(",") if c.strip()]
if cur_cols:
    current_rule_data["columns"] = cur_cols
if separator != ",":
    current_rule_data["separator"] = separator

cur_patterns = {}
for _, row in patterns_edited.iterrows():
    pname = str(row["name"]).strip()
    pregex = str(row["regex"]).strip()
    pcols_str = str(row["columns"]).strip()
    psep = str(row["separator"]).strip() or ","
    if pname and pregex:
        pat_data = {"regex": pregex}
        if pcols_str:
            pat_data["columns"] = [c.strip() for c in pcols_str.split(",") if c.strip()]
        if psep != ",":
            pat_data["separator"] = psep
        cur_patterns[pname] = pat_data

if cur_patterns:
    current_rule_data["patterns"] = cur_patterns

save_rule_ui("parse", current_rule_data, key_prefix="parse")
