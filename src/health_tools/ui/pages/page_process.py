"""批量处理页面"""

import streamlit as st

from health_tools.core.processor import BatchProcessor
from health_tools.ui.components.chip_selector import chip_select
from health_tools.ui.components.file_picker import dir_input, output_input

st.header("Process - 批量处理")

with st.sidebar:
    chip_rule = chip_select(key="proc_chip")

input_dir = dir_input("输入目录", key="proc_input")
output_path = output_input("输出目录", key="proc_output")

c1, c2 = st.columns(2)
pattern = c1.text_input("文件匹配模式", value="*.csv", key="proc_pattern")
workers = c2.number_input("并行线程数", value=4, min_value=1, max_value=16, key="proc_workers")

frame_split = st.checkbox("按帧分割", key="proc_split")
frame_column = st.text_input("帧列名", value="FRAME_ID", key="proc_frame_col")

if st.button("执行处理", type="primary", key="proc_run"):
    if input_dir is None:
        st.error("请输入有效输入目录")
        st.stop()
    if not output_path:
        st.error("请输入输出目录")
        st.stop()

    from pathlib import Path

    out_dir = Path(output_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    processor = BatchProcessor(chip_rule)
    results = processor.process_directory(
        input_dir,
        out_dir,
        pattern=pattern,
        recursive=True,
        max_workers=workers,
        frame_split=frame_split,
        frame_column=frame_column,
        verbose=False,
    )

    if results:
        success = sum(1 for r in results if r.get("success"))
        fail = len(results) - success
        st.success(f"处理完成: {success} 成功, {fail} 失败")
    else:
        st.warning("无处理结果")
