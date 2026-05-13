"""产测计算页面 (SNR/CTR/Noise)"""

import pandas as pd
import streamlit as st

from health_tools.core.factory import ChipInfoExtractor, FactoryCalculator
from health_tools.ui.components.chip_selector import chip_select, get_chip_adc_params
from health_tools.ui.components.file_picker import output_input, path_input
from health_tools.ui.components.result_display import save_and_show
from health_tools.ui.components.rule_builder import factory_config_form
from health_tools.utils.csv_handler import read_csv_df

st.header("Factory - 产测计算 (SNR/CTR/Noise)")

with st.sidebar:
    chip_rule = chip_select(key="fac_chip")

input_path = path_input("输入文件/目录", key="fac_input")
output_path = output_input("输出路径 (可选)", key="fac_output")

adc_params = get_chip_adc_params(chip_rule)

with st.expander("ADC 参数", expanded=False):
    c1, c2, c3, c4 = st.columns(4)
    adc_full_scale = c1.number_input(
        "adc_full_scale", value=adc_params["adc_full_scale"], format="%.0f", key="fac_adc_fs"
    )
    adc_offset = c2.number_input(
        "adc_offset", value=adc_params["adc_offset"], format="%.0f", key="fac_adc_off"
    )
    adc_vref = c3.number_input("adc_vref", value=adc_params["adc_vref"], key="fac_adc_vref")
    tia_ratio = c4.number_input("tia_ratio", value=adc_params["tia_ratio"], key="fac_tia")

fc = chip_rule.factory_config if chip_rule else {}
sample_rate = st.number_input("采样率 (Hz)", value=float(fc.get("sample_rate", 100)), key="fac_sr")

c1, c2 = st.columns(2)
gain = c1.number_input("增益 (KΩ, 0=自动提取)", value=0.0, min_value=0.0, key="fac_gain")
current = c2.number_input("灯电流 (mA, 0=自动提取)", value=0.0, min_value=0.0, key="fac_current")

with st.expander("时长配置", expanded=False):
    snr_cfg, ctr_cfg, noise_cfg = factory_config_form(chip_rule)

# PLACEHOLDER_FACTORY_EXECUTE
if st.button("执行计算", type="primary", key="fac_run"):
    if input_path is None:
        st.error("请输入有效路径")
        st.stop()

    calculator = FactoryCalculator(
        gain=gain if gain > 0 else None,
        current=current if current > 0 else None,
        sample_rate=sample_rate,
        adc_full_scale=adc_full_scale,
        adc_offset=adc_offset,
        adc_vref=adc_vref,
        tia_ratio=tia_ratio,
        snr_config=snr_cfg,
        ctr_config=ctr_cfg,
        noise_config=noise_cfg,
    )

    extractor = None
    if chip_rule and chip_rule.chip_info:
        extractor = ChipInfoExtractor(chip_rule.chip_info, chip_rule.gain_tia_map)

    factory_columns = chip_rule.factory_columns if chip_rule else None

    all_dfs = []
    if input_path.is_dir():
        csv_files = sorted(input_path.glob("*.csv"))
        if not csv_files:
            st.warning("目录中无 CSV 文件")
            st.stop()
        progress = st.progress(0)
        for idx, f in enumerate(csv_files):
            try:
                df = read_csv_df(f, chip_rule)
            except Exception:
                continue
            ch_list = [c for c in factory_columns if c in df.columns] if factory_columns else None
            results = calculator.calculate(df, ch_list, extractor=extractor)
            if results:
                file_df = calculator.to_dataframe(results, file_name=f.name)
                all_dfs.append(file_df)
            progress.progress((idx + 1) / len(csv_files))
        progress.empty()
    else:
        df = read_csv_df(input_path, chip_rule)
        ch_list = [c for c in factory_columns if c in df.columns] if factory_columns else None
        results = calculator.calculate(df, ch_list, extractor=extractor)
        if results:
            all_dfs.append(calculator.to_dataframe(results, file_name=input_path.name))

    if not all_dfs:
        st.warning("无有效数据通道")
        st.stop()

    result_df = pd.concat(all_dfs, ignore_index=True)
    save_and_show(result_df, output_path, title="SNR/CTR/Noise 计算结果")

    with st.expander("计算公式"):
        st.code(
            f"adc_full_scale={adc_full_scale:.0f}  adc_offset={adc_offset:.0f}  "
            f"adc_vref={adc_vref}  tia_ratio={tia_ratio}\n"
            "SNR(dB) = 20 * log10(Mean / Std_filtered)\n"
            "Noise(uV) = 6 * Std_filtered * adc_vref * 1e6 / adc_full_scale\n"
            "rawdata_uv = (value - adc_offset) / adc_full_scale * adc_vref * 1e6\n"
            "ipd_pA = rawdata_uv / (tia_ratio * RF) * 1000\n"
            "CTR(nA/mA) = ipd_pA / 1000 / iled"
        )
