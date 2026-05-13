"""文件信息页面"""

import streamlit as st
import yaml

from health_tools.ui.components.chip_selector import chip_select
from health_tools.ui.components.file_picker import file_input
from health_tools.utils.csv_handler import read_csv_df

st.header("Info - 文件信息")

with st.sidebar:
    chip_rule = chip_select(key="info_chip")

input_file = file_input("文件路径", key="info_input")

show_stats = st.checkbox("显示统计信息", value=True, key="info_stats")
preview_rows = st.number_input("预览行数", value=10, min_value=1, max_value=100, key="info_preview")

if input_file:
    suffix = input_file.suffix.lower()

    st.markdown(f"**文件**: `{input_file}`")
    st.markdown(f"**大小**: {input_file.stat().st_size / 1024:.1f} KB")

    if suffix in (".yaml", ".yml"):
        try:
            with open(input_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            st.subheader("YAML 结构")
            st.json(data)
        except Exception as e:
            st.error(f"读取 YAML 失败: {e}")

    elif suffix == ".csv":
        try:
            df = read_csv_df(input_file, chip_rule)
            st.markdown(f"**行数**: {len(df)}  **列数**: {len(df.columns)}")
            st.markdown(f"**列名**: {', '.join(df.columns[:30])}")

            if show_stats:
                st.subheader("统计信息")
                st.dataframe(df.describe(), use_container_width=True)

            st.subheader(f"数据预览 (前 {preview_rows} 行)")
            st.dataframe(df.head(preview_rows), use_container_width=True)
        except Exception as e:
            st.error(f"读取 CSV 失败: {e}")
    else:
        st.info("支持 CSV 和 YAML 文件")
