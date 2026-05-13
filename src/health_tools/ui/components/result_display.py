"""结果展示组件"""

import io
from typing import Optional

import pandas as pd
import streamlit as st


def show_dataframe(df: pd.DataFrame, title: str = "结果"):
    st.subheader(title)
    st.dataframe(df, use_container_width=True)
    csv_data = df.to_csv(index=False).encode("utf-8")
    st.download_button("下载 CSV", csv_data, file_name=f"{title}.csv", mime="text/csv")


def show_plot(fig, title: str = "图表"):
    st.subheader(title)
    st.pyplot(fig)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    buf.seek(0)
    st.download_button("下载 PNG", buf, file_name=f"{title}.png", mime="image/png")


def show_log(messages: list, title: str = "执行日志"):
    with st.expander(title, expanded=False):
        for msg in messages:
            st.text(msg)


def show_metric_cards(metrics: dict):
    cols = st.columns(len(metrics))
    for col, (label, value) in zip(cols, metrics.items()):
        col.metric(label, value)


def save_and_show(
    df: pd.DataFrame, output_path: Optional[str], title: str = "结果", file_prefix: str = "result"
):
    show_dataframe(df, title)
    if output_path:
        from pathlib import Path

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out, index=False)
        st.success(f"已保存: {out}")
