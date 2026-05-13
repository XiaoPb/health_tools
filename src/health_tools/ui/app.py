"""GHealth Tools 可视化界面"""

import streamlit as st

st.set_page_config(
    page_title="GHealth Tools",
    page_icon="💓",
    layout="wide",
    initial_sidebar_state="expanded",
)


def main():
    pages = {
        "产测计算": [st.Page("pages/page_factory.py", title="Factory (SNR/CTR/Noise)")],
        "数据处理": [
            st.Page("pages/page_convert.py", title="Convert (格式转换)"),
            st.Page("pages/page_parse.py", title="Parse (日志解析)"),
            st.Page("pages/page_split.py", title="Split (数据分割)"),
            st.Page("pages/page_process.py", title="Process (批量处理)"),
        ],
        "分析可视化": [
            st.Page("pages/page_plot.py", title="Plot (数据可视化)"),
            st.Page("pages/page_evaluate.py", title="Evaluate (准确率评估)"),
            st.Page("pages/page_classify.py", title="Classify (数据分类)"),
        ],
        "工具": [
            st.Page("pages/page_info.py", title="Info (文件信息)"),
        ],
    }

    nav = st.navigation(pages)
    nav.run()


if __name__ == "__main__":
    main()
