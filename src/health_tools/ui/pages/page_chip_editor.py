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
csv_info = st.text_input("信息标识 (可选)", placeholder="如 Version: GH3220", key="nc_csv_info")

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
st.caption("ADC 基本参数")
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

# chip_info 提取字段（动态表格）
st.subheader("信号提取字段 (chip_info 扩展)")
st.caption(
    "每行定义一个提取字段。name 为字段名，source 为源列名（支持 {start-end} 展开），"
    "bits 为位段（如 [3:0]，整列使用留空），type 为数据类型（int/float），"
    "unit 为单位，desc 为描述，optional 勾选表示该字段标记为可选（无需提取）"
)
chip_info_default = pd.DataFrame(
    {
        "name": [
            "gain",
            "bg_cancel_level",
            "dc_cancel_level",
            "dc_cancel_code",
            "led_current_sum",
            "led_current_drv0",
            "led_current_drv1",
            "led_current_drv3",
            "led_current_drv4",
            "ipd_pA",
        ],
        "source": ["", "", "", "", "", "", "", "", "", ""],
        "bits": ["[3:0]", "[5:4]", "[7:6]", "[31:23]", "[29:16]", "[15:8]", "[23:12]", "", "", ""],
        "type": ["int", "int", "int", "int", "int", "int", "int", "int", "int", "float"],
        "unit": ["", "", "", "", "0.1mA", "0.1mA", "0.1mA", "", "", "pA"],
        "desc": [
            "增益等级",
            "背景抵消等级",
            "DC抵消等级",
            "DC抵消校准码",
            "LED总电流",
            "DRV0通道电流",
            "DRV1通道电流",
            "DRV3通道电流",
            "DRV4通道电流",
            "光电流值",
        ],
        "optional": [False, False, False, False, False, False, False, True, True, False],
    }
)
chip_info_edited = st.data_editor(
    chip_info_default,
    num_rows="dynamic",
    key="nc_chip_info_fields",
    use_container_width=True,
)

st.divider()

# 预览和保存
if st.button("生成并保存", type="primary", key="nc_save"):
    if not chip_name:
        st.error("请输入芯片名称")
        st.stop()

    columns = [c.strip() for c in columns_text.strip().split("\n") if c.strip()]
    factory_cols = [c.strip() for c in factory_columns_text.strip().split("\n") if c.strip()]

    # 构建 YAML 数据
    csv_cfg = {
        "info_row": int(info_row),
        "header_row": int(header_row),
        "data_start_row": int(data_start_row),
        "delimiter": delimiter,
        "encoding": encoding,
    }
    if csv_info.strip():
        csv_cfg["info"] = csv_info.strip()

    rule_data = {
        "version": version,
        "chip": chip_name,
        "csv": csv_cfg,
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

    for _, row in chip_info_edited.iterrows():
        name = str(row["name"]).strip()
        if not name:
            continue
        if row["optional"]:
            chip_info[name] = {"optional": True}
        else:
            source = str(row["source"]).strip()
            bits_val = str(row["bits"]).strip()
            type_val = str(row["type"]).strip()
            unit_val = str(row["unit"]).strip()
            desc_val = str(row["desc"]).strip()
            if not source:
                continue
            field = {"source": source, "type": type_val or "int", "desc": desc_val}
            if bits_val:
                field["bits"] = bits_val
            else:
                field["bits"] = None
            if unit_val:
                field["unit"] = unit_val
            chip_info[name] = field

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
