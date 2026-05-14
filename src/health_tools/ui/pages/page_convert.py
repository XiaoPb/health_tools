"""格式转换页面"""

from typing import Dict

import pandas as pd
import streamlit as st

from health_tools.core.converter import DataConverter
from health_tools.models.rules import ConvertRule
from health_tools.rules.loader import RuleLoader
from health_tools.ui.components.chip_selector import chip_select
from health_tools.ui.components.file_picker import output_input, path_input
from health_tools.ui.components.result_display import save_and_show
from health_tools.ui.components.rule_builder import csv_format_form
from health_tools.ui.components.rule_saver import load_rule_selector, save_rule_ui
from health_tools.utils.csv_handler import read_csv_df

st.header("Convert - 格式转换")

with st.sidebar:
    chip_rule = chip_select(key="cv_chip")

# 加载历史规则
rule_file = load_rule_selector("convert", key="cv_rule_sel")

loaded_convert_rule = None
if rule_file:
    try:
        loaded_convert_rule = RuleLoader.load_convert_rule(rule_file)
    except Exception as e:
        st.warning(f"加载规则失败: {e}")

input_path = path_input("输入文件/目录", key="cv_input")
output_path = output_input("输出路径", key="cv_output")

# CSV 格式（从加载的规则填充默认值）
csv_defaults = loaded_convert_rule.csv if loaded_convert_rule else None
csv_config = csv_format_form(defaults=csv_defaults)

# 读取源文件列名用于辅助映射
source_columns = []
if input_path and input_path.is_file():
    try:
        preview_df = read_csv_df(input_path, chip_rule)
        source_columns = list(preview_df.columns)
        with st.expander("源文件预览 (前5行)"):
            st.dataframe(preview_df.head(), use_container_width=True)
    except Exception as e:
        st.warning(f"读取预览失败: {e}")

target_columns = chip_rule.columns if chip_rule else []

# 列映射（从规则加载）
st.markdown("**列映射** (源列名 → 目标列名)")
if loaded_convert_rule and loaded_convert_rule.column_mapping:
    mapping_items = list(loaded_convert_rule.column_mapping.items())
    mapping_df = pd.DataFrame(
        {"源列名": [k for k, v in mapping_items], "目标列名": [v for k, v in mapping_items]}
    )
else:
    default_rows = max(len(source_columns), 5)
    mapping_df = pd.DataFrame(
        {"源列名": source_columns[:default_rows], "目标列名": target_columns[:default_rows]}
    )
    if len(mapping_df) < default_rows:
        extra = pd.DataFrame(
            {
                "源列名": [""] * (default_rows - len(mapping_df)),
                "目标列名": [""] * (default_rows - len(mapping_df)),
            }
        )
        mapping_df = pd.concat([mapping_df, extra], ignore_index=True)

edited_mapping = st.data_editor(
    mapping_df, num_rows="dynamic", key="cv_mapping", use_container_width=True
)

with st.expander("高级选项"):
    st.markdown("**前值填充** (选择需要填充的源列)")
    ff_default = loaded_convert_rule.forward_fill if loaded_convert_rule else []
    ff_options = source_columns if source_columns else ff_default
    forward_fill_cols = st.multiselect("前值填充列", ff_options, default=ff_default, key="cv_ff")

    st.markdown("**频率扩展** (列名: 重复次数)")
    if loaded_convert_rule and loaded_convert_rule.expand_repeat:
        expand_items = [
            {"列名": k, "重复次数": v} for k, v in loaded_convert_rule.expand_repeat.items()
        ]
    else:
        expand_items = [{"列名": "", "重复次数": 1}]
    expand_df = pd.DataFrame(expand_items)
    edited_expand = st.data_editor(expand_df, num_rows="dynamic", key="cv_expand")

    st.markdown("**计算列** (列名: 公式)")
    if loaded_convert_rule and loaded_convert_rule.computed:
        computed_items = [{"列名": k, "公式": v} for k, v in loaded_convert_rule.computed.items()]
    else:
        computed_items = [{"列名": "", "公式": ""}]
    computed_df = pd.DataFrame(computed_items)
    edited_computed = st.data_editor(computed_df, num_rows="dynamic", key="cv_computed")

    merge = st.checkbox("合并目录中所有文件", key="cv_merge")
    split_rows = st.number_input("分割行数 (0=不分割)", value=0, min_value=0, key="cv_split")

if st.button("执行转换", type="primary", key="cv_run"):
    if input_path is None:
        st.error("请输入有效路径")
        st.stop()

    column_mapping: Dict[str, str] = {}
    for _, row in edited_mapping.iterrows():
        src = str(row["源列名"]).strip()
        tgt = str(row["目标列名"]).strip()
        if src and tgt:
            column_mapping[src] = tgt

    expand_repeat: Dict[str, int] = {}
    for _, row in edited_expand.iterrows():
        col = str(row["列名"]).strip()
        n = int(row["重复次数"])
        if col and n > 1:
            expand_repeat[col] = n

    computed: Dict[str, str] = {}
    for _, row in edited_computed.iterrows():
        col = str(row["列名"]).strip()
        formula = str(row["公式"]).strip()
        if col and formula:
            computed[col] = formula

    rule = ConvertRule(
        column_mapping=column_mapping,
        forward_fill=forward_fill_cols,
        expand_repeat=expand_repeat,
        computed=computed,
        csv=csv_config,
        target_chip=chip_rule.chip if chip_rule else None,
    )

    chip_columns = chip_rule.columns if chip_rule else None
    converter = DataConverter(rule, chip_columns=chip_columns)

    if input_path.is_file():
        df = read_csv_df(input_path, chip_rule)
        result_df = converter.convert(df)
        save_and_show(result_df, output_path, title="转换结果")
    elif input_path.is_dir():
        csv_files = sorted(input_path.glob("*.csv"))
        if not csv_files:
            st.warning("目录中无 CSV 文件")
            st.stop()
        all_dfs = []
        for f in csv_files:
            try:
                df = read_csv_df(f, chip_rule)
                all_dfs.append(converter.convert(df))
            except Exception:
                continue
        if merge and all_dfs:
            result_df = pd.concat(all_dfs, ignore_index=True)
            save_and_show(result_df, output_path, title="合并转换结果")
        elif all_dfs:
            st.success(f"转换完成: {len(all_dfs)} 个文件")
            save_and_show(all_dfs[0], None, title=f"预览: {csv_files[0].name}")

# --- 保存规则 ---
st.divider()

# 构建当前配置
current_cv_data: Dict = {}
if chip_rule:
    current_cv_data["target_chip"] = chip_rule.chip
if csv_config:
    current_cv_data["csv"] = csv_config

cur_mapping: Dict[str, str] = {}
for _, row in edited_mapping.iterrows():
    src = str(row["源列名"]).strip()
    tgt = str(row["目标列名"]).strip()
    if src and tgt:
        cur_mapping[src] = tgt
if cur_mapping:
    current_cv_data["column_mapping"] = cur_mapping

if forward_fill_cols:
    current_cv_data["forward_fill"] = forward_fill_cols

cur_expand: Dict[str, int] = {}
for _, row in edited_expand.iterrows():
    col = str(row["列名"]).strip()
    n = int(row["重复次数"])
    if col and n > 1:
        cur_expand[col] = n
if cur_expand:
    current_cv_data["expand_repeat"] = cur_expand

cur_computed: Dict[str, str] = {}
for _, row in edited_computed.iterrows():
    col = str(row["列名"]).strip()
    formula = str(row["公式"]).strip()
    if col and formula:
        cur_computed[col] = formula
if cur_computed:
    current_cv_data["computed"] = cur_computed

save_rule_ui("convert", current_cv_data, key_prefix="cv")
