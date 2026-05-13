"""数据分割页面"""

import streamlit as st

from health_tools.core.splitter import DataSplitter
from health_tools.ui.components.chip_selector import chip_select
from health_tools.ui.components.file_picker import output_input, path_input

st.header("Split - 数据分割")

with st.sidebar:
    chip_rule = chip_select(key="split_chip")

input_path = path_input("输入文件/目录", key="split_input")
output_path = output_input("输出目录", key="split_output")

split_mode = st.radio("分割方式", ["按行数", "按列值", "按时间"], key="split_mode")

by_size = None
by_column = None
column_value = 0.0
by_time = None
time_column = None

if split_mode == "按行数":
    by_size = st.number_input("每片行数", value=5000, min_value=100, key="split_size")
elif split_mode == "按列值":
    by_column = st.text_input("分割列名", value="FRAME_ID", key="split_col")
    column_value = st.number_input("分割值", value=0.0, key="split_val")
elif split_mode == "按时间":
    by_time = st.number_input("时间间隔 (秒)", value=60.0, min_value=1.0, key="split_time")
    time_column = st.text_input("时间列名", key="split_tcol")

if st.button("执行分割", type="primary", key="split_run"):
    if input_path is None:
        st.error("请输入有效路径")
        st.stop()
    if not output_path:
        st.error("请输入输出目录")
        st.stop()

    from pathlib import Path

    out_dir = Path(output_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    splitter = DataSplitter(chip_rule)

    if input_path.is_file():
        results = splitter.split_file(
            input_path,
            out_dir,
            by_column=by_column,
            column_value=column_value,
            by_size=by_size,
            by_time=by_time,
            time_column=time_column,
            verbose=False,
        )
    else:
        results = splitter.split_directory(
            input_path,
            out_dir,
            by_column=by_column,
            column_value=column_value,
            by_size=by_size,
            by_time=by_time,
            time_column=time_column,
            verbose=False,
        )

    if results:
        st.success(f"分割完成: 生成 {len(results)} 个文件")
        with st.expander("输出文件列表"):
            for f in results:
                st.text(str(f))
    else:
        st.warning("未生成任何文件")
