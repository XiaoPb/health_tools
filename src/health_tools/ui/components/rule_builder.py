"""规则参数表单生成器"""

from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st


def factory_config_form(
    chip_rule=None,
) -> Tuple[Optional[Dict], Optional[Dict], Optional[Dict]]:
    fc = chip_rule.factory_config if chip_rule else {}

    st.markdown("**SNR 配置**")
    snr_default = fc.get("snr", {})
    c1, c2, c3 = st.columns(3)
    snr_head = c1.number_input(
        "跳过头部(s)", value=float(snr_default.get("skip_head_seconds", 10)), key="snr_head"
    )
    snr_tail = c2.number_input(
        "跳过尾部(s)", value=float(snr_default.get("skip_tail_seconds", 10)), key="snr_tail"
    )
    snr_min = c3.number_input(
        "最小时长(s)", value=float(snr_default.get("min_duration_seconds", 90)), key="snr_min"
    )

    st.markdown("**CTR 配置**")
    ctr_default = fc.get("ctr", {})
    c1, c2, c3 = st.columns(3)
    ctr_head = c1.number_input(
        "跳过头部(s)", value=float(ctr_default.get("skip_head_seconds", 1)), key="ctr_head"
    )
    ctr_tail = c2.number_input(
        "跳过尾部(s)", value=float(ctr_default.get("skip_tail_seconds", 0)), key="ctr_tail"
    )
    ctr_min = c3.number_input(
        "最小时长(s)", value=float(ctr_default.get("min_duration_seconds", 2)), key="ctr_min"
    )

    st.markdown("**Noise 配置**")
    noise_default = fc.get("noise", {})
    c1, c2, c3 = st.columns(3)
    noise_head = c1.number_input(
        "跳过头部(s)", value=float(noise_default.get("skip_head_seconds", 2)), key="noise_head"
    )
    noise_tail = c2.number_input(
        "跳过尾部(s)", value=float(noise_default.get("skip_tail_seconds", 0)), key="noise_tail"
    )
    noise_min = c3.number_input(
        "最小时长(s)", value=float(noise_default.get("min_duration_seconds", 4)), key="noise_min"
    )

    snr_cfg = {
        "skip_head_seconds": snr_head,
        "skip_tail_seconds": snr_tail,
        "min_duration_seconds": snr_min,
    }
    ctr_cfg = {
        "skip_head_seconds": ctr_head,
        "skip_tail_seconds": ctr_tail,
        "min_duration_seconds": ctr_min,
    }
    noise_cfg = {
        "skip_head_seconds": noise_head,
        "skip_tail_seconds": noise_tail,
        "min_duration_seconds": noise_min,
    }
    return snr_cfg, ctr_cfg, noise_cfg


def column_mapping_form(source_columns: List[str], target_columns: List[str]) -> Dict[str, str]:
    st.markdown("**列映射**")
    mapping_data = pd.DataFrame(
        {"源列名": source_columns[:20], "目标列名": [""] * min(20, len(source_columns))}
    )
    edited = st.data_editor(mapping_data, num_rows="dynamic", key="col_mapping")
    result = {}
    for _, row in edited.iterrows():
        src = str(row["源列名"]).strip()
        tgt = str(row["目标列名"]).strip()
        if src and tgt:
            result[src] = tgt
    return result


def csv_format_form(defaults: Optional[Dict] = None) -> Dict[str, Any]:
    d = defaults or {}
    st.markdown("**输入 CSV 格式**")
    c1, c2, c3 = st.columns(3)
    info_row = c1.number_input(
        "信息行", value=int(d.get("info_row", 0)), min_value=0, key="csv_info"
    )
    header_row = c2.number_input(
        "列名行", value=int(d.get("header_row", 1)), min_value=0, key="csv_header"
    )
    data_start = c3.number_input(
        "数据起始行", value=int(d.get("data_start_row", 2)), min_value=1, key="csv_data"
    )
    delimiter = st.text_input("分隔符", value=d.get("delimiter", ","), key="csv_delim")
    return {
        "info_row": info_row,
        "header_row": header_row,
        "data_start_row": data_start,
        "delimiter": delimiter,
    }
