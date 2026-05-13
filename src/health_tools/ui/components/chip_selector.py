"""芯片选择组件"""

from typing import Optional

import streamlit as st

from health_tools.models.rules import ChipRule
from health_tools.rules.loader import RuleLoader

BUILTIN_CHIPS = ["(无)", "gh3220", "gh3036", "gh3036_evk"]


def chip_select(key: str = "chip_select") -> Optional[ChipRule]:
    chip_name = st.selectbox("芯片类型", BUILTIN_CHIPS, key=key)
    if chip_name == "(无)":
        return None
    try:
        return RuleLoader.load_chip_rule(chip_name)
    except Exception as e:
        st.error(f"加载芯片规则失败: {e}")
        return None


def get_chip_adc_params(chip_rule: Optional[ChipRule]) -> dict:
    if chip_rule and chip_rule.chip_info:
        return {
            "adc_full_scale": float(chip_rule.chip_info.get("adc_full_scale", 8388608)),
            "adc_offset": float(chip_rule.chip_info.get("adc_offset", 0)),
            "adc_vref": float(chip_rule.chip_info.get("adc_vref", 1.8)),
            "tia_ratio": float(chip_rule.chip_info.get("tia_ratio", 2.0)),
        }
    return {
        "adc_full_scale": 8388608.0,
        "adc_offset": 0.0,
        "adc_vref": 1.8,
        "tia_ratio": 2.0,
    }
