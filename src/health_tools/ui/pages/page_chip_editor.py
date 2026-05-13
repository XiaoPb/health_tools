"""新增芯片规则页面"""

import pandas as pd
import streamlit as st
import yaml

from health_tools.config import (
    get_user_rules_dir,
    init_config_dir,
    sync_builtin_rules,
)

st.header("新增芯片规则")

# 确保规则目录已初始化
rules_dir = get_user_rules_dir()
if rules_dir is None:
    st.info("首次使用，正在初始化规则目录...")
    init_config_dir()
    sync_builtin_rules()
    rules_dir = get_user_rules_dir()
    st.success(f"规则目录已初始化: {rules_dir}")

chip_dir = rules_dir / "chip" if rules_dir else None
if chip_dir:
    existing = [f.stem for f in chip_dir.glob("*.yaml")]
    if existing:
        st.caption(f"已有芯片规则: {', '.join(existing)}")

st.divider()

# 基本信息
st.subheader("基本信息")
c1, c2 = st.columns(2)
chip_name = c1.text_input("芯片名称", placeholder="如 gh3220", key="new_chip_name")
version = c2.text_input("版本", value="1.0", key="new_chip_ver")

# CSV 格式
st.subheader("CSV 格式")
c1, c2, c3 = st.columns(3)
info_row = c1.number_input("信息行 (0=无)", value=0, min_value=0, key="nc_info")
header_row = c2.number_input("列名行", value=1, min_value=0, key="nc_header")
data_start_row = c3.number_input("数据起始行", value=2, min_value=1, key="nc_data")
c1, c2 = st.columns(2)
delimiter = c1.text_input("分隔符", value=",", key="nc_delim")
encoding = c2.selectbox("编码", ["utf-8", "gbk", "latin-1"], key="nc_enc")

# 列定义
st.subheader("列定义")
st.caption("每行一个列名，支持 {start-end} 范围展开语法，如 CH{0-15}")
columns_text = st.text_area(
    "列名列表",
    height=150,
    placeholder="TimeStamp\nFRAME_ID\nCH{0-15}",
    key="nc_columns",
)

# 产测列
st.subheader("产测计算列")
st.caption("用于 SNR/CTR/Noise 计算的列，支持范围展开")
factory_columns_text = st.text_area(
    "产测列",
    height=80,
    placeholder="CH{0-15}",
    key="nc_fac_cols",
)

# 产测配置
st.subheader("产测配置")
sample_rate = st.number_input("采样率 (Hz)", value=100.0, min_value=1.0, key="nc_sr")

st.markdown("**SNR**")
c1, c2, c3 = st.columns(3)
snr_head = c1.number_input("跳过头部(s)", value=10.0, key="nc_snr_h")
snr_tail = c2.number_input("跳过尾部(s)", value=10.0, key="nc_snr_t")
snr_min = c3.number_input("最小时长(s)", value=90.0, key="nc_snr_m")

st.markdown("**CTR**")
c1, c2, c3 = st.columns(3)
ctr_head = c1.number_input("跳过头部(s)", value=1.0, key="nc_ctr_h")
ctr_tail = c2.number_input("跳过尾部(s)", value=0.0, key="nc_ctr_t")
ctr_min = c3.number_input("最小时长(s)", value=2.0, key="nc_ctr_m")

st.markdown("**Noise**")
c1, c2, c3 = st.columns(3)
noise_head = c1.number_input("跳过头部(s)", value=2.0, key="nc_noise_h")
noise_tail = c2.number_input("跳过尾部(s)", value=0.0, key="nc_noise_t")
noise_min = c3.number_input("最小时长(s)", value=4.0, key="nc_noise_m")

# ADC / chip_info
st.subheader("芯片参数 (chip_info)")
c1, c2, c3, c4 = st.columns(4)
adc_full_scale = c1.number_input("adc_full_scale", value=8388608, key="nc_adc_fs")
adc_offset = c2.number_input("adc_offset", value=0, key="nc_adc_off")
adc_vref = c3.number_input("adc_vref", value=1.8, key="nc_adc_vref")
tia_ratio = c4.number_input("tia_ratio", value=2.0, key="nc_tia")

# gain_tia_map
st.subheader("增益映射 (gain_tia_map)")
st.caption("增益等级 → TIA 电阻 (KΩ)")

gain_default = pd.DataFrame({"等级": list(range(7)), "电阻(KΩ)": [10, 25, 50, 100, 250, 500, 1000]})
gain_edited = st.data_editor(gain_default, num_rows="dynamic", key="nc_gain_map")

# chip_info 扩展字段 (gain/led_current)
st.subheader("增益/电流提取配置")
with st.expander("gain 配置"):
    gain_source = st.text_input("source 列", placeholder="AGC_INFO_CH{0-15}", key="nc_g_src")
    gain_bits = st.text_input("bits", value="[3:0]", key="nc_g_bits")

with st.expander("led_current_sum 配置"):
    led_mode = st.radio(
        "电流模式", ["直接提取 (led_current_sum)", "累加 drv 通道"], key="nc_led_mode"
    )
    if led_mode == "直接提取 (led_current_sum)":
        led_source = st.text_input("source 列", placeholder="AGC_INFO_CH{0-15}", key="nc_l_src")
        led_bits = st.text_input("bits", value="[29:16]", key="nc_l_bits")
        led_unit = st.text_input("unit", value="0.1mA", key="nc_l_unit")
    else:
        st.markdown("**DRV 通道配置**")
        drv_data = pd.DataFrame(
            {
                "通道": ["drv0", "drv1"],
                "source": ["", ""],
                "bits": ["", ""],
                "unit": ["0.1mA", "0.1mA"],
            }
        )
        drv_edited = st.data_editor(drv_data, num_rows="dynamic", key="nc_drv")

st.divider()

# 预览和保存
if st.button("生成并保存", type="primary", key="nc_save"):
    if not chip_name:
        st.error("请输入芯片名称")
        st.stop()

    columns = [c.strip() for c in columns_text.strip().split("\n") if c.strip()]
    factory_cols = [c.strip() for c in factory_columns_text.strip().split("\n") if c.strip()]

    # 构建 YAML 数据
    rule_data = {
        "version": version,
        "chip": chip_name,
        "csv": {
            "info_row": int(info_row),
            "header_row": int(header_row),
            "data_start_row": int(data_start_row),
            "delimiter": delimiter,
            "encoding": encoding,
        },
        "columns": columns,
    }

    if factory_cols:
        rule_data["factory_columns"] = factory_cols

    rule_data["factory_config"] = {
        "sample_rate": sample_rate,
        "snr": {
            "skip_head_seconds": snr_head,
            "skip_tail_seconds": snr_tail,
            "min_duration_seconds": snr_min,
        },
        "ctr": {
            "skip_head_seconds": ctr_head,
            "skip_tail_seconds": ctr_tail,
            "min_duration_seconds": ctr_min,
        },
        "noise": {
            "skip_head_seconds": noise_head,
            "skip_tail_seconds": noise_tail,
            "min_duration_seconds": noise_min,
        },
    }

    # gain_tia_map
    gain_map = {}
    for _, row in gain_edited.iterrows():
        gain_map[int(row["等级"])] = int(row["电阻(KΩ)"])
    rule_data["gain_tia_map"] = {"unit": "KΩ", "map": gain_map}

    # chip_info
    chip_info = {
        "adc_full_scale": int(adc_full_scale),
        "adc_offset": int(adc_offset),
        "adc_vref": float(adc_vref),
        "tia_ratio": float(tia_ratio),
    }

    if gain_source:
        chip_info["gain"] = {
            "source": gain_source,
            "bits": gain_bits,
            "type": "int",
            "desc": "增益等级",
        }

    if led_mode == "直接提取 (led_current_sum)" and led_source:
        chip_info["led_current_sum"] = {
            "source": led_source,
            "bits": led_bits,
            "type": "int",
            "unit": led_unit,
            "desc": "LED总电流",
        }
    elif led_mode != "直接提取 (led_current_sum)":
        chip_info["led_current_sum"] = {"optional": True}
        for _, row in drv_edited.iterrows():
            name = str(row["通道"]).strip()
            src = str(row["source"]).strip()
            bits_val = str(row["bits"]).strip()
            unit_val = str(row["unit"]).strip()
            if name and src and bits_val:
                chip_info[f"led_current_{name}"] = {
                    "source": src,
                    "bits": bits_val,
                    "type": "int",
                    "unit": unit_val,
                    "desc": f"{name}通道电流",
                }

    rule_data["chip_info"] = chip_info

    # 预览
    yaml_content = yaml.dump(
        rule_data, default_flow_style=False, allow_unicode=True, sort_keys=False
    )
    st.subheader("YAML 预览")
    st.code(yaml_content, language="yaml")

    # 保存
    if chip_dir:
        out_file = chip_dir / f"{chip_name}.yaml"
        if out_file.exists():
            st.warning(f"文件已存在: {out_file}，将覆盖")
        out_file.write_text(yaml_content, encoding="utf-8")
        st.success(f"已保存: {out_file}")
    else:
        st.error("规则目录不可用")
