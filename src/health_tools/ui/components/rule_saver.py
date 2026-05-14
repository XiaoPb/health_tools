"""规则保存/加载公共组件"""

from typing import List, Optional

import streamlit as st
import yaml

from health_tools.config import get_user_rules_dir, init_config_dir, sync_builtin_rules
from health_tools.rules.loader import RuleLoader


def list_available_rules(rule_type: str) -> List[str]:
    """列出内置 + 用户规则目录下的所有 .yaml 文件名（去重）"""
    names = set()
    builtin_dir = RuleLoader.get_builtin_rules_path() / rule_type
    if builtin_dir.exists():
        names.update(f.name for f in builtin_dir.glob("*.yaml"))
    user_dir = get_user_rules_dir()
    if user_dir:
        user_type_dir = user_dir / rule_type
        if user_type_dir.exists():
            names.update(f.name for f in user_type_dir.glob("*.yaml"))
    return sorted(names)


def load_rule_selector(rule_type: str, key: str) -> Optional[str]:
    """规则选择下拉框，返回选中的规则文件名或 None（手动配置）"""
    options = ["(手动配置)"] + list_available_rules(rule_type)
    choice = st.selectbox("加载历史规则", options, key=key)
    if choice == "(手动配置)":
        return None
    return choice


def save_rule_ui(rule_type: str, rule_data: dict, key_prefix: str):
    """保存规则 UI 组件：名称输入 + 描述 + 保存按钮"""
    with st.expander("保存为规则文件"):
        c1, c2 = st.columns([1, 2])
        name = c1.text_input("规则名称", key=f"{key_prefix}_save_name", placeholder="my_rule")
        desc = c2.text_input("描述 (可选)", key=f"{key_prefix}_save_desc")

        if st.button("保存规则", key=f"{key_prefix}_save_btn"):
            if not name:
                st.error("请输入规则名称")
                return
            _do_save(rule_type, name, desc, rule_data)


def _do_save(rule_type: str, name: str, description: str, rule_data: dict):
    """执行保存"""
    rules_dir = get_user_rules_dir()
    if rules_dir is None:
        init_config_dir()
        sync_builtin_rules()
        rules_dir = get_user_rules_dir()

    if rules_dir is None:
        st.error("规则目录不可用")
        return

    type_dir = rules_dir / rule_type
    type_dir.mkdir(parents=True, exist_ok=True)

    if not name.endswith(".yaml"):
        name = f"{name}.yaml"

    data = {"version": "1.0"}
    if description:
        data["description"] = description
    data.update(rule_data)

    out_file = type_dir / name
    if out_file.exists():
        st.warning(f"文件已存在，将覆盖: {out_file.name}")

    yaml_content = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
    out_file.write_text(yaml_content, encoding="utf-8")
    st.success(f"已保存: {out_file}")
