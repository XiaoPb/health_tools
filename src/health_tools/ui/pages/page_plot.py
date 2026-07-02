"""数据可视化页面"""

import streamlit as st

from health_tools.core.plotter import DataPlotter
from health_tools.core.psd_plotter import PsdPlotter
from health_tools.ui.components.chip_selector import chip_select
from health_tools.ui.components.file_picker import dir_input, file_input, output_input
from health_tools.ui.components.result_display import show_plot
from health_tools.utils.csv_handler import read_csv_df

st.header("Plot - 数据可视化")

with st.sidebar:
    chip_rule = chip_select(key="plot_chip")

plot_type = st.selectbox("图表类型", ["time", "freq", "both", "stft", "psd"], key="plot_type")

if plot_type == "psd":
    input_file = dir_input("输入离线结果目录", key="plot_input_psd")
else:
    input_file = file_input("输入 CSV 文件", key="plot_input")
output_path = output_input("输出目录 (可选)", key="plot_output")

if plot_type != "psd":
    sample_rate = st.number_input("采样率 (Hz)", value=100.0, min_value=1.0, key="plot_sr")

    c1, c2 = st.columns(2)
    window = c1.number_input("窗口大小 (秒)", value=10.0, min_value=1.0, key="plot_window")
    overlap = c2.slider("重叠率", 0.0, 0.99, 0.75, key="plot_overlap")

    with st.expander("高级选项"):
        fmt = st.selectbox("输出格式", ["png", "svg", "pdf"], key="plot_fmt")
        dpi = st.number_input("DPI", value=150, min_value=72, max_value=600, key="plot_dpi")
        bandpass = st.text_input("带通滤波 (low,high Hz)", key="plot_bp")
        remove_baseline = st.checkbox("去基线", value=False, key="plot_bl")
        baseline_method = st.selectbox(
            "基线方法", ["median", "mean", "polynomial"], key="plot_bl_m"
        )
        freq_bpm = st.checkbox("频率轴使用 BPM", value=False, key="plot_bpm")
        freq_range = st.text_input("频率范围 (low,high)", key="plot_fr")

# 读取文件并选择通道
channels_options = []
if input_file and plot_type != "psd":
    try:
        df = read_csv_df(input_file, chip_rule)
        channels_options = list(df.columns)
    except Exception as e:
        st.warning(f"读取文件失败: {e}")

selected_channels = None
if plot_type != "psd":
    selected_channels = st.multiselect("选择通道", channels_options, key="plot_ch")

if st.button("生成图表", type="primary", key="plot_run"):
    if input_file is None:
        st.error("请输入有效路径")
        st.stop()

    import tempfile
    from pathlib import Path

    if plot_type == "psd":
        save_dir = Path(output_path) if output_path else Path(tempfile.mkdtemp())
        save_dir.mkdir(parents=True, exist_ok=True)
        saved = PsdPlotter().plot(input_file, save_dir=save_dir, show_progress=False)
        if saved:
            st.success(f"生成 {len(saved)} 张PSD时频图: {save_dir}")
            for path in saved:
                st.image(str(path), caption=path.name)
        else:
            st.warning("未找到PSD数据文件")
        st.stop()

    try:
        df = read_csv_df(input_file, chip_rule)
    except Exception as e:
        st.error(f"读取文件失败: {e}")
        st.stop()

    bp_tuple = None
    if bandpass:
        parts = [float(x.strip()) for x in bandpass.split(",")]
        if len(parts) == 2:
            bp_tuple = tuple(parts)

    fr_tuple = None
    if freq_range:
        parts = [float(x.strip()) for x in freq_range.split(",")]
        if len(parts) == 2:
            fr_tuple = tuple(parts)

    plotter = DataPlotter(
        sample_rate=sample_rate,
        window=window,
        overlap=overlap,
        fmt=fmt,
        dpi=dpi,
        bandpass=bp_tuple,
        remove_baseline=remove_baseline,
        baseline_method=baseline_method,
        freq_bpm=freq_bpm,
        freq_range=fr_tuple,
    )

    channels = selected_channels or None

    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir) / f"plot.{fmt}"
        if plot_type == "time":
            fig = plotter.plot_time(df, out, channels=channels)
        elif plot_type == "freq":
            fig = plotter.plot_freq(df, out, channels=channels)
        elif plot_type == "both":
            fig = plotter.plot_time(df, out, channels=channels)
            if fig:
                show_plot(fig, "时域图")
            out2 = Path(tmpdir) / f"freq.{fmt}"
            fig = plotter.plot_freq(df, out2, channels=channels)
        elif plot_type == "stft":
            fig = plotter.plot_stft(df, out, channels=channels)

        if fig:
            show_plot(fig, f"{plot_type} 图")
